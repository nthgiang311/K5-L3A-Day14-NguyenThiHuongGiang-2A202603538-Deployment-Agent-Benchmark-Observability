# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây lấy từ file JSON trong `reports/` (và CSV trong `benchmark-results/` khi có). Không có số ước lượng.

**Họ tên:** Nguyễn Thị Hương Giang
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 10 Pro + WSL2 Ubuntu (4 vCPU, 3,7 GB RAM cho WSL), Python 3.14 venv trong WSL, Docker Engine 29.9.3 trong WSL. Lúc đo, CPU máy host đang bận khoảng 77% và RAM trống chỉ khoảng 500 MB. Agent và `load_test.py` chạy trên cùng máy, nên latency khi tải cao bị ảnh hưởng bởi việc tranh CPU (xem nhận xét 2.1, 2.2).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất khoảng 150–250 ms mỗi call, cộng retrieval khoảng 20 ms. 500 ms để dư khoảng 2 lần cho mạng và hàng đợi mà người dùng vẫn thấy "tức thì". Dùng p95 vì average che mất tail latency. |
| Error rate `/ask` | < 2 % | Upstream mock lỗi khoảng 1% (`MOCK_ERROR_RATE=0.01`). Ngưỡng 2% cho error budget gấp đôi tỉ lệ lỗi nền, vượt mức này nghĩa là có sự cố thật. Alert Prometheus đặt lỏng hơn (5% trong 1 phút) để tránh báo động giả. |
| Accuracy trên golden dataset | ≥ 85 % | Thấp hơn 85% thì cứ khoảng 7 câu có 1 câu sai, không chấp nhận được với trợ lý kỹ thuật. Quality gate CI dùng 0.85 kèm điều kiện "không regression" so với baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

`python load_test.py --url http://localhost:8002 --requests 300 --concurrency C --out reports/load_v2_cC.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.56 | 201.6 | 530.3 | 1720.2 | 1.67% | ❌ (p95) |
| 10 | 15.41 | 303.5 | 3244.7 | 4532.4 | 0.33% | ❌ (p95) |
| 50 | 12.70 | 2341.5 | 12692.3 | 14758.9 | 1.00% | ❌ (p95) |
| 100 | 20.38 | 2766.9 | 9361.5 | 11741.0 | 1.33% | ❌ (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency. Từ 1 lên 10, RPS tăng khoảng 4,3 lần (3,56 → 15,41, chưa tới 10 lần). Từ 10 lên 50 và 100, RPS gần như đứng yên ở khoảng 13–20 req/s, còn p50/p95 tăng vọt lên hàng giây. Hệ thống đã bão hoà: agent chỉ có 1 process uvicorn, và trên máy này CPU (dùng chung với chính `load_test.py` cùng các tiến trình khác của host) là nút thắt. Khi vượt ngưỡng đó, request thêm vào chỉ phải xếp hàng chờ (theo định luật Little: latency ≈ concurrency / throughput, tức khoảng 100 / 20 ≈ 5 s, khớp bậc độ lớn với p50–p95 đo được). Ngay cả c=1 cũng fail SLO p95, vì khoảng 3% request "slow" (+1500 ms) rơi đúng vào vùng p95 khi mẫu chỉ có 300 request. Muốn tăng throughput phải scale ngang (thêm instance hoặc worker), không phải tăng concurrency phía client.

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 663.9 | 2293.7 | 3827.1 |
| 0.03 (mặc định) | 1310.4 | 3903.8 | 7502.1 |
| 0.1 | 433.2 | 1719.1 | 1844.9 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Ba lần chạy này **không** tăng đơn điệu theo `MOCK_SLOW_RATE`. Lý do: ba lần đo cách nhau vài phút, và tải CPU của máy host thay đổi giữa các lần (lần `0.03` chạy ngay sau loạt c=50/c=100 nên máy đang nóng nhất, RPS chỉ 14,13; lần `0.1` có RPS 39,41). Nhiễu do tranh CPU ở concurrency 20 lớn hơn tác động của slow rate, nên không thể kết luận định lượng từ ba hàng này. Cần đo lại khi máy rảnh, hoặc ở concurrency thấp hơn ngưỡng bão hoà.

Dù vậy, lần `0.1` (ít nhiễu nhất) cho thấy rõ hình dạng tail latency: **p50 = 221,3 ms nhưng p90 = 1691,9 ms**. Đúng khoảng 10% request bị cộng thêm khoảng 1500 ms, nên p90, p95 và p99 đều dồn về mức khoảng 1,7–1,8 s, trong khi avg chỉ 433 ms. **Percentile cao (p95/p99) là chỉ số nhạy nhất** với request chậm. Average trộn 90% request nhanh với 10% request chậm thành một con số "trông ổn" mà không người dùng nào thực sự gặp. Vì vậy SLO phải đặt theo p95/p99: mỗi phần trăm vượt ngưỡng tương ứng với một nhóm người dùng thật đang phải chờ.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.3 | 108.7 | 115.8 |
| Tổng cost (USD) | 0.000407 | 0.000756 | 0.000809 |
| Cost / câu đúng (USD) | 0.00040695 | 0.00003599 | 0.00003517 |
| Quality gate | FAIL | PASS (≥ 80%, baseline v1) | PASS (≥ 100%, baseline v2, 0 regression) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách đã sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| security-02 | `token`, `hết hạn`, `chữ ký` (score 0.00) | Thêm entry `(["jwt", "api key"], ...)` vào `KNOWLEDGE_BASE`, mô tả JWT là token có chữ ký số, có thời điểm hết hạn, khác API key cố định |
| scaling-03 | `cpu`, `memory`, `custom metrics` (score 0.00) | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)`, mô tả HPA scale theo CPU, memory hoặc custom metrics |

Từ khoá kích hoạt (`jwt`, `api key`, `hpa`, `kubernetes`) không xuất hiện trong câu hỏi nào khác của golden dataset, nên không cướp retrieval của câu khác. Kết quả: 2 câu được cải thiện, 0 regression. Cùng thay đổi đã chép sang `production/utils/mock_llm.py`.

**Quality gate trong CI:** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Kiểm chứng: chạy v1 với `--baseline reports/eval_v2.json` thì in `❌ FAIL`, có 20 câu regression, `exit=1`. Job `.github/workflows/quality-gate.yml` bật agent v2, chạy eval với `--min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`. Exit code khác 0 làm step fail, và nếu bật "Require status checks to pass" cho nhánh `main` thì PR không merge được.

**Trade-off chất lượng / chi phí / latency:** v2 tốn gấp khoảng 1,9 lần token mỗi câu (108,7 so với 57,3), vì prompt có thêm context retrieval, nên tổng cost gấp khoảng 1,86 lần. Đổi lại, accuracy tăng từ 4,3% lên 91,3%, nên **cost / câu đúng rẻ hơn khoảng 11 lần** ($0.000036 so với $0.000407). Latency eval gần như không đổi (p95 220,4 ms so với 222,4 ms), vì retrieval chỉ khoảng 20 ms. So theo "cost / câu" thì v2 tệ hơn, so theo "cost / câu đúng" thì v2 tốt hơn hẳn. Chỉ số thứ hai mới phản ánh giá trị thật người dùng nhận được.

---

## 4. Observability stack (production)

Stack được bật bằng `docker compose -p k5-day14-observability up -d --build` trong WSL2.

**Hai sự cố gặp phải và cách xử lý:**
1. Docker Hub trả `429 Too Many Requests` khi pull image ẩn danh. Xử lý: pull cùng tag qua `mirror.gcr.io` rồi `docker tag` lại tên gốc, không sửa `docker-compose.yml`.
2. Container agent crash loop với `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân: user `agent` được tạo với home là `/app` (`useradd -d /app`), nên Python tìm package trong `/app/.local`, trong khi stage builder copy package vào `/home/agent/.local`. Xử lý: thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile`. Kết quả Locust của lần chạy hỏng (100% lỗi 502/504) đã bị loại bỏ. Đây cũng là ví dụ thật cho Exercise 7.6D: lỗi 502/504 sinh ra ở Nginx, metric của agent không ghi nhận được.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png`. Chụp trong thí nghiệm A+B với tải nền 30 user: 13,4 req/s, error rate 21,69%, p95 1,91 s, 3 instance up. Ảnh phụ `screenshots/grafana-after-scale-test.png` là toàn cảnh hai đợt Locust scale 1 và scale 3.
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger: `screenshots/jaeger-error-trace.png` (HTTP 503, span `chat mock-llm-small` đánh dấu lỗi, có event `exception`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert **firing**: `screenshots/prometheus-alert-firing.png` (FIRING (2): `AgentHighErrorRate` và `AgentHighLatencyP95`)

**Trả lời Exercise 7.4:**

1. **p95 và avg:** trong đợt Locust 3 instance (CSV `scale_3_stats.csv`), avg là 2159 ms, p50 760 ms, nhưng p95 là 10 000 ms. Khoảng cách lớn giữa p50/avg và p95 cho thấy tail latency nặng: đa số request vài trăm ms, nhưng khoảng 5% request phải chờ rất lâu (xếp hàng khi CPU bão hoà, cộng request "slow" của mock).
2. **Nginx có chia đều không?** Có, theo round-robin. Ở Part 5 với cùng cơ chế `server agent:8000` + Docker DNS, 6 request liên tiếp lần lượt đi tới `172.19.0.3 → .4 → .5 → .3 → .4 → .5` (header `X-Served-By`). Stack này dùng cùng cấu hình `upstream` + `resolver`, nên traffic cũng được chia vòng tròn như vậy.
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Prompt gồm system prompt, tài liệu retrieval và câu hỏi, còn câu trả lời chỉ là một đoạn tài liệu ngắn. Đo thật trong Prometheus (`sum by (type)(rate(llm_tokens_total[1m]))`, lấy lúc chạy thí nghiệm E): input khoảng 694 token/s, output khoảng 375 token/s. Với v2, chênh lệch còn lớn hơn vì prompt có thêm tài liệu retrieval (eval: v2 tốn 108,7 token/câu so với 57,3 của v1).
4. **`curl http://localhost:8080/metrics`** trả **404**, vì `nginx.conf` chặn `/metrics` từ bên ngoài. Endpoint này chỉ dành cho Prometheus scrape trực tiếp từng container trong network nội bộ, để không lộ thông tin vận hành ra internet.

Kiểm tra nhanh qua Nginx: `POST /ask` trả `200`, kèm header `x-trace-id: 8a12bd85914e4283ce32b11e9bba8aa5` và `X-Served-By: 172.19.0.4:8000`.

Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` cho kết quả `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust 30 user, 3 instance agent. Thời gian đo bằng script hỏi `GET /api/v1/alerts` của Prometheus mỗi 2 giây, tính từ lúc chạy lệnh `docker compose up -d` với cấu hình mới (hoặc `docker pause`). A và B được áp dụng **cùng lúc** để có 2 alert firing cùng nhau.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending sau 56 s, **firing sau 117 s** | Error rate (21,69%, đỏ); Requests/s theo status (vàng = 503) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending sau 17 s, **firing sau 181 s** | Latency p50/p95/p99: p95/p99 vượt đường 1 s, p50 tăng ít |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | pending sau 38 s, **firing sau 158 s** (burn rate đo được $34,61/giờ, ngưỡng $2) | Cost burn rate (USD/giờ); LLM latency p95 theo model |
| D | `docker pause` 1 instance | `AgentInstanceDown` | pending sau 14 s, **firing sau 45 s** | Instances up (3 → 2) |
| E | `AGENT_VERSION=v1` | Không alert nào do v1 gây ra | Theo dõi 3 phút: error rate và p95 không pending. `LLMCostBurnRateHigh` vẫn firing là trạng thái **còn sót từ C** (cửa sổ `rate(...[5m])` còn dữ liệu của model lớn); `AgentInstanceDown` chỉ pending thoáng qua vì container được tạo lại | Không có panel nào đỏ. Theo thiết kế dashboard, chỉ panel retrieval hit ratio, tokens/s và bảng version thay đổi (không chụp ảnh riêng cho E) |

Thời gian tới lúc firing khớp với thiết kế rule: khoảng thời gian để cửa sổ `rate()` có đủ dữ liệu, cộng thời gian `for` (1m cho error rate, 2m cho p95 và cost, 30s cho instance down), cộng chu kỳ scrape/evaluate 5 s.

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 chỉ làm câu trả lời sai. Latency, error rate và mức sẵn sàng vẫn bình thường, nên mọi metric hạ tầng vẫn xanh. Cách phát hiện:

1. **Chặn trước khi deploy:** quality gate eval trên golden dataset trong CI (đã có ở mục 3). Bản v1 sẽ bị chặn ngay với exit code 1.
2. **Giám sát chất lượng khi đang chạy:** chạy eval định kỳ (synthetic, ví dụ mỗi 15 phút) lên production và xuất accuracy thành metric (`agent_eval_accuracy`) để alert khi tụt. Theo dõi các proxy metric như *retrieval hit ratio* (v1 tụt về 0) và *tokens/câu* giảm đột ngột.
3. **Tín hiệu từ người dùng:** nút 👍/👎, tỉ lệ hỏi lại, và LLM-as-judge chấm mẫu ngẫu nhiên từ traffic thật.

### 4.3 Debug bằng trace

Trace chậm nhất trong một lượt tải 30 user (stack mặc định 2 instance), tìm bằng Jaeger API (`/api/v3/traces`) rồi mở trong UI (`screenshots/jaeger-slow-trace.png`):

- `trace_id`: `736545c8207141d442822b65df99ccd3`
- Tổng thời gian: **2281 ms** (Jaeger UI làm tròn thành 2,3 s)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` (1720,8 ms, khoảng 75%)**, tức là LLM chậm (request rơi vào nhóm "slow" của mock), không phải code của agent. Các span còn lại: `agent.run` 1905,7 ms (bao gồm LLM), `agent.retrieve_context` 95,3 ms, và khoảng 375 ms còn lại nằm ngoài `agent.run` (nhận request, chờ event loop, ghi metric).
- Attributes của span LLM: `gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=76`, `gen_ai.usage.output_tokens=39`.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 736545c8…`):

```json
{"ts": "2026-11-25T10:39:33.125830+00:00", "level": "INFO", "service": "observable-agent", "instance": "02e5694ff131", "event": "llm_call", "trace_id": "736545c8207141d442822b65df99ccd3", "span_id": "0ff0f4dae9066ae3", "request_id": "e87a07b3ff26", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1660.6}
{"ts": "2026-11-25T10:39:33.321421+00:00", "level": "INFO", "service": "observable-agent", "instance": "02e5694ff131", "event": "http_request", "trace_id": "736545c8207141d442822b65df99ccd3", "span_id": "0ff0f4dae9066ae3", "request_id": "e87a07b3ff26", "method": "POST", "route": "/ask", "status": 200, "ms": 2199.7}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`): `trace_id` `78f61bec45871ac784e6c44c288ad90a`, 409 ms, trả HTTP 503. Span `chat mock-llm-small` (101 ms) có `error.type=upstream_unavailable` và event `exception`. Log tương ứng:

```json
{"ts": "2026-11-25T10:38:51.762179+00:00", "level": "INFO", "service": "observable-agent", "instance": "03298e85b6de", "event": "llm_error", "trace_id": "78f61bec45871ac784e6c44c288ad90a", "span_id": "29845d0085af21ea", "request_id": "fe7e2fcb9c9d", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Lúc tải 100 user, trace chậm nhất kéo dài 11 099 ms nhưng `agent.run` chỉ chiếm 2439 ms. Khoảng 8,6 s còn lại request phải chờ trước khi handler chạy, tức là thời gian xếp hàng do CPU bão hoà chứ không phải do LLM. Trace giúp phân biệt "LLM chậm" với "hệ thống quá tải".

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu lấy từ dòng `Aggregated` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (gồm cả `POST /ask` và `GET /health`).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 29.66 | 930 | 5500 | 10000 | 501 / 3415 (14.7%) |
| 3 | 26.90 | 760 | 10000 | 11000 | 502 / 3269 (15.4%) |

**Giải thích kết quả:** scale từ 1 lên 3 instance **không** cải thiện. RPS giảm nhẹ (29,66 → 26,90), p50 giảm nhẹ (930 → 760 ms) nhưng p95 tăng (5,5 s → 10 s), tỉ lệ lỗi gần như giữ nguyên (khoảng 15%). Theo `*_failures.csv`, phần lớn lỗi là **502 Bad Gateway** do Nginx không kết nối được tới agent (scale 1: 429 lỗi 502, dồn trong khoảng 15 giây 09:55:19–09:55:34; scale 3: 286 lỗi 502), tiếp theo là **504 Gateway Time-out** (45 và 203 lỗi), chỉ một ít là 503 do mock LLM lỗi (27 và 13 lỗi). Việc lỗi 502 dồn trong một khoảng ngắn cho thấy có lúc agent không nhận kết nối được, có thể do quá tải hoặc vướng giới hạn 0,5 CPU / 256 MB của container. Các lỗi này sinh ra ở Nginx nên metric của agent không ghi nhận. Nút thắt không nằm ở số instance agent mà ở **CPU của máy chạy lab**: Locust (100 user), Nginx, Prometheus, Grafana, Jaeger và tất cả agent cùng chạy trên một WSL2 4 vCPU, trong khi host Windows đã bận sẵn khoảng 77% CPU. Thêm agent chỉ chia nhỏ phần CPU vốn đã thiếu, và tạo thêm tiến trình phải tranh nhau. Trace ở mục 4.3 xác nhận điều này: phần lớn thời gian là chờ, không phải LLM. Ngoài ra, nút thắt thứ hai theo đề là LLM latency: mỗi request vẫn phải đợi mock LLM khoảng 150–250 ms (và 1,5 s với request slow) bất kể có bao nhiêu instance, nên scale ngang chỉ tăng throughput khi còn CPU trống. Muốn đo đúng hiệu quả scale thì phải chạy Locust ở máy khác, hoặc đặt giới hạn CPU rõ ràng và còn dư tài nguyên.

---

## 6. Kết luận

- 3 điều học được về benchmark và observability:
  1. **Average nói dối, percentile thì không.** Ở lần `MOCK_SLOW_RATE=0.1`, avg là 433 ms nhưng p90 đã là 1,69 s. SLO và alert phải đặt theo p95/p99.
  2. **Throughput có trần.** Tăng concurrency từ 10 lên 100 không tăng RPS (khoảng 15 → 20 req/s) mà chỉ đẩy p95 lên hàng giây (hàng đợi). Phải đo để biết trần đó nằm ở đâu, rồi scale ngang. Môi trường đo (CPU dùng chung với client) ảnh hưởng mạnh tới kết quả, nên phải ghi rõ môi trường đo.
  3. **Metric hạ tầng không bắt được lỗi chất lượng.** Đổi v1/v2 không làm thay đổi error rate, nhưng accuracy chênh 87 điểm %. Eval trên golden dataset với baseline và exit code trong CI là "alert" cho chất lượng. So sánh phiên bản phải dùng **cost / câu đúng** thay vì cost / câu.
- Nếu đưa agent lên production thật, mình sẽ thêm:
  - Metric `agent_eval_accuracy` từ eval định kỳ, kèm alert khi tụt dưới 85%.
  - Metric retrieval hit ratio, kèm alert khi giảm mạnh.
  - Giám sát ở tầng load balancer hoặc synthetic check từ bên ngoài, vì lỗi 502/504 do Nginx sinh ra không hiện trong metric của agent (chính sự cố crash loop ở mục 4 cho thấy điều này).
  - Alert theo error budget burn rate (nhiều cửa sổ 5m/1h) thay vì chỉ một ngưỡng.
  - Alert cost theo ngày, nối với cost guard 402 của Part 6.
