# Day 14 Lab — Mission Answers

> Mục nào đánh dấu **⏳** là bước cần chạy hoặc chụp thêm trước khi nộp. Không ghi số chưa đo.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret:** `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL` có cả mật khẩu `password123`. Push lên GitHub là lộ ngay, và muốn đổi key thì phải sửa code rồi deploy lại.
2. **Log ra secret:** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Key nằm trong log, ai đọc được log là có key.
3. **Dùng `print()` thay cho logging có cấu trúc:** không có level, không có timestamp, không parse hay lọc được trong log aggregator.
4. **Không có config management:** `DEBUG = True` và `MAX_TOKENS = 500` cố định trong code, không đổi được theo môi trường.
5. **Không có health check (`/health`, `/ready`):** platform không biết agent đã chết để restart, load balancer không biết instance chưa sẵn sàng.
6. **Port và host cố định:** `host="localhost"` nên container không nhận được kết nối từ ngoài; `port=8000` bỏ qua biến `PORT` mà Railway/Render cấp.
7. **`reload=True` trong production:** tốn tài nguyên theo dõi file, và có thể restart giữa chừng.
8. **Không xử lý shutdown:** SIGTERM cắt ngang request đang chạy.
9. **`/ask` nhận `question` qua query string, không validate:** không giới hạn độ dài, câu hỏi có thể lọt vào access log và URL.

### Exercise 1.2: Chạy bản basic

Chạy trong WSL2 (output thật):

```
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
HTTP 200
$ curl http://localhost:8000/health
{"detail":"Not Found"}
HTTP 404                         ← không có health check

--- log server ---
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this     ← secret bị in ra log
```

App chạy được, nhưng **không** production-ready: không có `/health`, secret lộ trong log, log là text thường.

Bản production (`01-localhost-vs-production/production`, `cp .env.example .env`) cho kết quả: `/health` → 200 `{"status":"ok","uptime_seconds":1.0,...}`, `/ready` → 200 `{"ready":true}`, `POST /ask` (JSON body) → 200. Khi nhận `kill -TERM`, uvicorn in `Shutting down` → `Waiting for application shutdown.` → `Application shutdown complete.`, tức là tắt êm.

### Exercise 1.3: Bảng so sánh

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code | Biến môi trường (`config.py` + `.env`) | Cùng một image chạy được ở dev, staging và prod; secret không vào git; đổi config không cần build lại |
| Secrets | Ghi thẳng trong code và in ra log | Đọc từ env, không bao giờ log | Tránh lộ key; rotate key chỉ cần đổi biến môi trường |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness) | Platform tự restart khi chết; LB chỉ route tới instance đã sẵn sàng |
| Logging | `print()` | JSON có cấu trúc qua `logging` | Parse, lọc, đếm được trong Loki/Datadog; liên kết được với trace |
| Shutdown | Đột ngột | Graceful (lifespan + bắt SIGTERM) | Request đang chạy được hoàn thành, không mất dữ liệu khi deploy hoặc scale-in |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud (platform cấp port) |
| Debug / reload | `DEBUG=True`, `reload=True` | Tắt theo `ENVIRONMENT` | Không lộ thông tin nội bộ, không tốn tài nguyên |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Debian đầy đủ có Python 3.11 và build tools (khoảng 1 GB).
2. **Working directory:** `/app`. Mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy trong thư mục này.
3. **Vì sao COPY `requirements.txt` trước:** để tận dụng layer cache. Layer `pip install` chỉ build lại khi `requirements.txt` đổi. Sửa code (`app.py`) chỉ làm build lại các layer phía sau, nên build nhanh hơn rất nhiều.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh hoặc tham số mặc định, bị ghi đè khi `docker run <image> <lệnh khác>`. `ENTRYPOINT` là executable cố định của container; tham số của `docker run` được nối thêm vào sau nó (muốn đổi phải dùng `--entrypoint`). Thường dùng `ENTRYPOINT` cho chương trình chính, `CMD` cho tham số mặc định.

### Exercise 2.2 và 2.3: Build và so sánh kích thước

Build từ gốc repo:

```bash
docker build -f 02-docker/develop/Dockerfile    -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images | grep my-agent
```

Kết quả đo trong WSL2 (`docker images my-agent` và `docker image inspect -f '{{.Size}}'`):

```
my-agent:develop  1.67GB   (1 667 779 714 bytes)
my-agent:advanced 240MB    (  239 815 643 bytes)
```

- Develop: **1668 MB** (1,67 GB)
- Production: **240 MB**
- Chênh lệch: nhỏ hơn **85,6%** (khoảng 7 lần)

Chạy container develop: `docker run -p 8000:8000 my-agent:develop`, rồi `curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"` trả `200 {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`.

Số đo liên quan: image agent Part 6 (multi-stage, `python:3.11-slim`, venv copy từ builder) là **273 MB** theo `check_production_ready.py` (mục Docker: image < 500 MB).

**Multi-stage trong `02-docker/production/Dockerfile`:**

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc` và `libpq-dev`, rồi `pip install --user` toàn bộ dependencies vào `/root/.local`.
- **Stage 2 (`runtime`):** từ `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ copy `/root/.local` từ builder cùng source code, rồi thêm `HEALTHCHECK` và `CMD uvicorn`.
- **Vì sao nhỏ hơn:** image cuối không chứa compiler, header, apt cache hay pip cache của stage builder. Base `slim` cũng nhỏ hơn base đầy đủ khoảng 900 MB.

### Exercise 2.4: Kiến trúc Docker Compose (`02-docker/production/docker-compose.yml`)

```
Client ──HTTP :80──▶ Nginx (reverse proxy / LB)
                        │  network "internal"
                        ▼
                     agent (FastAPI :8000)
                     ├──▶ redis:6379   (session, rate limit)
                     └──▶ qdrant:6333  (vector DB cho RAG)
```

Service được start: `agent`, `redis`, `qdrant`, `nginx`. Chỉ Nginx publish cổng ra host (80/443). Các service nói chuyện với nhau qua bridge network `internal`, dùng tên service làm DNS (`redis://redis:6379/0`, `http://qdrant:6333`). `agent` dùng `depends_on: condition: service_healthy` để chờ redis và qdrant healthy rồi mới start.

Chạy thật (`touch .env.local && docker compose -p k5-day14-docker up -d --build`):

```
agent  Up 27 seconds (healthy)
nginx  Up 26 seconds
qdrant Up 39 seconds (healthy)
redis  Up 39 seconds (healthy)

$ curl http://localhost/health
{"status":"ok","uptime_seconds":16.6,"version":"2.0.0","timestamp":"2026-11-25T10:32:49.801072"}   HTTP 200
$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}   HTTP 200
```

Thứ tự khởi động khớp với `depends_on`: redis và qdrant lên trước (39 s), agent sau (27 s, healthy), nginx cuối cùng.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- Nền tảng chính: ⏳ (Railway, dùng `06-lab-complete/railway.toml`, builder `DOCKERFILE`, `healthcheckPath = "/health"`)
- URL: ⏳ (ghi trong `DEPLOYMENT.md`)
- Ảnh: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` ⏳

### So sánh `railway.toml` và `render.yaml`

| | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| Định dạng | TOML, chỉ mô tả **một service** (build + deploy) | YAML, mô tả **cả hạ tầng**: nhiều service (web, Redis/Key Value…) trong một file |
| Build | `builder = "DOCKERFILE"` (hoặc NIXPACKS/RAILPACK tự đoán) | `runtime: docker` + `dockerfilePath`/`rootDir` (hoặc `runtime: python` + `buildCommand`) |
| Start | `startCommand` (nếu không có thì dùng `CMD` trong Dockerfile) | `startCommand` hoặc `CMD` trong Dockerfile |
| Health check | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries` | Render tự restart, không cấu hình trong file |
| Biến môi trường và secret | **Không** khai báo trong file; đặt bằng `railway variables` hoặc dashboard. Redis là plugin riêng, tham chiếu bằng `${{Redis.REDIS_URL}}` | Khai báo ngay trong `envVars`: giá trị thường dùng `value`, secret dùng `generateValue: true` (Render tự sinh) hoặc `sync: false` (nhập trên dashboard), Redis lấy qua `fromService … property: connectionString` |
| Region / plan | Chọn trên dashboard | `region`, `plan` trong file |
| Deploy | `railway up` từ máy (CLI upload thư mục) | Kết nối GitHub repo, tự deploy khi push (`autoDeploy`) |

Vì sao khác: Railway thiên về "deploy nhanh từ CLI", nên file chỉ giữ phần build/deploy, còn hạ tầng và secret quản lý trên dashboard. Render theo kiểu *Infrastructure as Code*: cả web service, Redis và cách sinh secret nằm trong một Blueprint, review được qua git. Vì vậy Render phải có cơ chế `generateValue`/`sync: false` để không ghi thẳng secret vào file.

### Exercise 3.3: Pipeline Cloud Run (`cloudbuild.yaml` + `service.yaml`)

Cloud Build chạy 4 bước nối tiếp nhau (`waitFor`):

1. **test:** trong `python:3.11-slim`, cài requirements và chạy `pytest tests/`. Test fail thì dừng cả pipeline.
2. **build:** `docker build`, gắn tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push:** đẩy mọi tag lên Container Registry.
4. **deploy:** `gcloud run deploy` image theo đúng `$COMMIT_SHA` ra `asia-southeast1`, với min 1 / max 10 instance, 512Mi, 1 CPU, timeout 60 s. `OPENAI_API_KEY` lấy từ Secret Manager (`--set-secrets`), không nằm trong code.

`service.yaml` là bản khai báo Knative tương đương: autoscaling 1–10 instance (target 80 request đồng thời mỗi instance, `containerConcurrency: 80`), secret qua `secretKeyRef`, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`.

---

## Part 4: API Security

Chạy trong WSL2 (output thật, đã che token).

### Exercise 4.1: API key (`04-api-gateway/develop`, `AGENT_API_KEY=secret-key-123 python app.py`)

- Key được kiểm tra trong dependency `verify_api_key()` (`APIKeyHeader(name="X-API-Key")`), được inject vào `/ask` qua `Depends(verify_api_key)`.
- Thiếu key trả **401**, sai key trả **403** (bản develop tách 2 mã; Part 6 của mình trả 401 cho cả hai trường hợp theo hợp đồng).
- Rotate key: đổi biến môi trường `AGENT_API_KEY` rồi restart hoặc redeploy, không phải sửa code. Muốn rotate không downtime thì cho phép tạm thời 2 key (cũ và mới) trong một khoảng chuyển tiếp.

```
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

Luồng JWT: `POST /auth/token` (username và password) cho ra token HS256 chứa `sub`, `role`, `exp` (60 phút). Client gửi `Authorization: Bearer <token>`. `verify_token()` kiểm tra chữ ký và hạn mà không cần tra DB.

```
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN_ĐÃ_CHE>","token_type":"bearer","expires_in_minutes":60,...}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window log. Mỗi user có một `deque` timestamp; bỏ các timestamp cũ hơn 60 s rồi đếm.
- **Giới hạn:** user 10 req/phút (`rate_limiter_user`), admin 100 req/phút (`rate_limiter_admin`).
- **Bypass cho admin:** app chọn limiter theo `role` trong JWT. Token có `role=admin` (tài khoản `teacher`) dùng limiter 100 req/phút.

Vòng 20 request với token `student` (request 1 ở 4.2 đã dùng 1 lượt, nên lượt thứ 10 tính cả request đó):

```
request 1..9  -> HTTP 200
request 10..20 -> HTTP 429
Body khi bị 429: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}

HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 58
```

### Exercise 4.4: Cost guard

Bản `04-api-gateway/production/cost_guard.py` giữ usage trong dict của process, nên mất khi restart và không chia sẻ được giữa các instance. Ở Part 6 (`06-lab-complete/app/cost_guard.py`), mình làm cost guard dựa trên **Redis**:

- `record_cost(input_tokens, output_tokens)` tính `cost = in/1000 × $0.00015 + out/1000 × $0.0006`, rồi `INCRBYFLOAT` vào 2 key `cost:daily:YYYY-MM-DD` (TTL 2 ngày) và `cost:monthly:YYYY-MM` (TTL 32 ngày). Key theo ngày và tháng nên **tự reset** khi sang ngày hoặc tháng mới, không cần cron.
- `check_budget()` được gọi **trước** khi gọi LLM: `MGET` 2 key, tổng ngày ≥ `DAILY_BUDGET_USD` hoặc tổng tháng ≥ `MONTHLY_BUDGET_USD` thì trả **402 Payment Required**.
- Cả hai ngưỡng đọc từ biến môi trường. Mọi worker và instance dùng chung một Redis nên budget là toàn cục. Dùng pipeline để các lệnh ghi đi cùng một lượt.
- `check_production_ready.py` xác nhận: với `DAILY_BUDGET_USD=0.000001`, agent trả **402 ở request thứ 1** (khi chạy test, Redis đã còn chi phí của các request trước đó).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health và readiness

- `/health` (liveness) luôn trả 200 khi process còn chạy, **không** phụ thuộc Redis. Nếu liveness phụ thuộc Redis, chỉ cần Redis chập chờn là platform restart mọi container, làm sự cố tệ thêm.
- `/ready` (readiness) kiểm tra dependency (Redis `PING`). Fail thì trả 503, LB ngừng gửi traffic tới instance đó nhưng **không** restart nó.
- Bản `05-scaling-reliability/develop` dùng cờ `_is_ready`: bật sau khi startup xong, tắt khi bắt đầu shutdown, để `/ready` trả 503 trong lúc khởi động và lúc tắt.
- Part 6: `check_production_ready.py` xác nhận `/ready` trả 200 khi có Redis và 503 khi Redis mất kết nối, trong khi `/health` vẫn 200.

### Exercise 5.2: Graceful shutdown

Bản develop dùng `lifespan` cùng middleware đếm `_in_flight_requests`. Khi shutdown, app đặt `_is_ready = False` rồi chờ (tối đa vài giây) tới khi số request đang chạy về 0 mới thoát. Ở Part 6, mình **không** tự đăng ký handler SIGTERM: uvicorn đã bắt SIGTERM, ngừng nhận kết nối mới, chờ request đang chạy xong (`--timeout-graceful-shutdown 8`), chạy phần sau `yield` của lifespan (ghi log `shutdown`, đóng Redis), rồi thoát với exit 0. `CMD` dùng `exec` để uvicorn là PID 1 và nhận được SIGTERM từ `docker stop`.

Kết quả (`check_production_ready.py`): gửi SIGTERM khi đang có request thì **request vẫn trả 200, exit code 0**; `docker stop` cho **exit code 0 trong 2,8 s**.

### Exercise 5.3: Stateless

`05-scaling-reliability/production/app.py` lưu session và history trong Redis (`session:<id>`, `SETEX` TTL 1 giờ), không giữ trong dict của process. Khi chạy nhiều instance sau load balancer, request thứ 2 của cùng user có thể rơi vào instance khác. Nếu state nằm trong RAM của instance 1 thì instance 2 không thấy, và history bị mất. Ở Part 6, rate limit (sorted set `ratelimit:<hash key>`) và cost (`cost:*`) đều nằm trong Redis. `check_production_ready.py` restart agent rồi gọi lại, **vẫn nhận 429**, chứng tỏ state không nằm trong memory. Key được hash SHA-256 nên API key không nằm dạng rõ trong Redis.

### Exercise 5.4 và 5.5: Load balancing và test stateless

Nginx (`05-scaling-reliability/production/nginx.conf`) dùng `upstream agent_cluster { server agent:8000; }` với `resolver 127.0.0.11 valid=10s`: Docker DNS trả về IP của cả 3 container `agent`, Nginx chia request round-robin. `proxy_next_upstream error timeout http_503` tự chuyển sang instance khác khi một instance lỗi. Header `X-Served-By` cho biết instance nào đã phục vụ.

Chạy thật: `docker compose -p k5-day14-scaling up -d --build --scale agent=3` (3 agent + redis + nginx), rồi `python test_stateless.py`:

```
Session ID: 625b5d83-df78-4e61-ba61-5137662b5e72
Request 1: [instance-7bcb37]  Q: What is Docker?
Request 2: [instance-f948e0]  Q: Why do we need containers?
Request 3: [instance-1015d3]  Q: What is Kubernetes?
Request 4: [instance-7bcb37]  Q: How does load balancing work?
Request 5: [instance-f948e0]  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-f948e0', 'instance-7bcb37', 'instance-1015d3'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

Cùng một session đi qua cả 3 instance theo vòng tròn, mà history vẫn đủ 10 tin nhắn (5 câu hỏi, 5 câu trả lời), vì mọi instance đều đọc và ghi `session:<id>` trong Redis.

Phân tán tải (6 request `POST /chat` liên tiếp, đọc header `X-Served-By`):

```
X-Served-By: 172.19.0.3:8000   served_by: instance-7bcb37
X-Served-By: 172.19.0.4:8000   served_by: instance-f948e0
X-Served-By: 172.19.0.5:8000   served_by: instance-1015d3
X-Served-By: 172.19.0.3:8000   served_by: instance-7bcb37
X-Served-By: 172.19.0.4:8000   served_by: instance-f948e0
X-Served-By: 172.19.0.5:8000   served_by: instance-1015d3
```

Nginx chia round-robin đều cho 3 instance. Script không tự tắt instance nào; khả năng chịu lỗi khi một instance chết đến từ `proxy_next_upstream error timeout http_503`. Ở Part 7, thí nghiệm `docker pause` 1 instance cho thấy alert `AgentInstanceDown` firing sau 45 s.

---

## Part 6: Final Project — `check_production_ready.py`

Chạy bản đầy đủ (có Docker) trong WSL2 (`os.name == "posix"`), tại `06-lab-complete/`:

```
✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 20s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Docker: container chạy được, GET /health → 200
...
✅ 7. Rate limiting
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ 8. Cost guard
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1
✅ 10. Structured logging
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON
✅ 11. Graceful shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 2.8s

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Điểm chính của bài làm:

- `app/main.py`: `/health`, `/ready`, `/ask` (`Depends(verify_api_key)` → `check_rate_limit` → `check_budget` → LLM → `record_cost`); `JsonFormatter` ghi mỗi dòng log là một JSON; middleware log mỗi request kèm `request_id`; exception handler trả JSON gọn (422 khi input sai, 503 khi mất Redis, 500 chung), không lộ stack trace; `lifespan` cho startup và shutdown.
- `app/config.py`: mọi cấu hình đọc từ env (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`, `LOG_LEVEL`). `AGENT_API_KEY` mặc định rỗng, nên nếu quên cấu hình thì mọi request đều bị 401 (fail closed).
- `app/auth.py`: `APIKeyHeader(auto_error=False)` + `hmac.compare_digest`; thiếu hoặc sai key đều trả 401.
- `app/rate_limiter.py`: sliding window bằng Redis sorted set (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` + `EXPIRE`); trả 429 kèm `Retry-After`.
- `Dockerfile`: builder tạo venv `/opt/venv`, runtime `python:3.11-slim`, user `app`, `HEALTHCHECK` bằng `urllib`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000} --workers 2"`.
- `docker-compose.yml`: agent (`env_file .env required: false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: service_healthy`) + `redis:7-alpine` có healthcheck và volume.

---

## AI log

Bài làm có dùng trợ lý AI (Claude Code, mô hình Claude Opus) trong VS Code:

| Hỏi / yêu cầu | Nhận được | Mình kiểm tra thế nào |
|---|---|---|
| Đọc README, RUBRIC, CHECKPOINTS và hoàn thiện Part 6 | Code cho `app/*.py`, `Dockerfile`, `.dockerignore`, `.env.example`, `docker-compose.yml`, `railway.toml`, `render.yaml` | Chạy `python check_production_ready.py` bản đầy đủ trong WSL2 có Docker: **PASS 12/12, 43/43 checks**. Không sửa script chấm. |
| Chạy Part 7 Bước 1 (load test, eval) | Lệnh chạy và file `reports/*.json` | Số trong `BENCHMARK_REPORT.md` chép từ đúng các file JSON đó. AI cũng chỉ ra kết quả `MOCK_SLOW_RATE` bị nhiễu do CPU máy bận, và báo cáo ghi rõ điều này thay vì "làm đẹp" số. |
| Exercise 7.3: sửa `KNOWLEDGE_BASE` | Hai entry mới (JWT/API key, Kubernetes HPA) | Eval cuối với `--min-accuracy 1.0 --baseline reports/eval_v2.json`: 23/23, 0 regression, `✅ PASS`. Không sửa `golden_dataset.jsonl`. |
| Part 7 Bước 2: stack lỗi | Chẩn đoán: Docker Hub 429 (pull qua `mirror.gcr.io`), agent crash loop `No module named 'uvicorn'` (thêm `PYTHONUSERBASE` vào `production/Dockerfile`) | Đọc log container `docker logs`; kết quả Locust của lần chạy hỏng (100% lỗi 502/504) đã bị loại bỏ, không đưa vào báo cáo. |
| Part 7 Bước 2: chạy benchmark, chaos, chụp ảnh | Script tự động: Locust headless scale 1/3, đổi env cho thí nghiệm A–E, hỏi `/api/v1/alerts` mỗi 2 s để đo thời gian tới lúc firing, chụp ảnh bằng headless Chrome, lấy trace qua Jaeger API v3 | Mở và xem lại từng ảnh trước khi nộp; số trong báo cáo lấy từ CSV, JSON và log thật. Khi thấy log của trace cũ đã mất (container bị tạo lại trong chaos), chạy lại một lượt tải ngắn để lấy trace và log khớp `trace_id`. |
| Part 1, 2, 4, 5: chạy lệnh thật | Script chạy curl, build image, compose, `test_stateless.py` | Output dán trong file này là output thật, token đã che. |
| Soạn câu trả lời Part 1–5 | Bản nháp câu trả lời | Đối chiếu từng ý với code trong `01-…` tới `05-…`. |
