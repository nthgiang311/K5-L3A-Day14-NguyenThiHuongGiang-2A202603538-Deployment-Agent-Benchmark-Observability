# Deployment Information

Agent được deploy là agent Part 6 trong `06-lab-complete/` (FastAPI + Redis, image build từ `Dockerfile`).

## Public URL

**https://agent-production-1fb71cee.up.railway.app**

## Platform

Railway, project `day14-production-agent`, gồm 2 service:

| Service | Nguồn | Ghi chú |
|---|---|---|
| `agent` | `06-lab-complete/Dockerfile` (upload bằng `railway up`) | 2 worker uvicorn, `PORT=8000`, domain public |
| `redis` | image `redis:7-alpine` | chỉ mở trên private network `redis.railway.internal:6379` |

`06-lab-complete/railway.toml`: builder `DOCKERFILE`, `healthcheckPath = "/health"`, restart `ON_FAILURE`.
Phương án dự phòng: Render Blueprint (`06-lab-complete/render.yaml`: web service Docker + Key Value Redis, `AGENT_API_KEY` dùng `generateValue: true`).

## Các bước đã chạy

Tài khoản dùng **workspace token** (`rlwy_wksp_...`). Token này không gọi được `railway whoami` / `railway init`, nên hạ tầng được tạo qua Railway GraphQL API, còn code được upload bằng CLI với project token:

1. `projectCreate` → project `day14-production-agent`.
2. `serviceCreate` → `redis` (image `redis:7-alpine`) và `agent` (rỗng).
3. `variableCollectionUpsert` → đặt biến môi trường cho `agent` (danh sách bên dưới).
4. `serviceDomainCreate` (target port 8000) → domain public.
5. `projectTokenCreate` → token cho CLI, rồi:
   ```bash
   cd 06-lab-complete
   RAILWAY_TOKEN=<project token> railway up --service <agent-id> --environment <env-id> --ci
   ```

Cách làm thông thường (tài khoản đăng nhập được bằng `railway login`) tương đương:

```bash
cd 06-lab-complete
railway login && railway init && railway add --database redis
railway variables --set "AGENT_API_KEY=$(openssl rand -hex 24)" --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
                  --set ENVIRONMENT=production --set RATE_LIMIT_PER_MINUTE=10 \
                  --set DAILY_BUDGET_USD=1.0 --set MONTHLY_BUDGET_USD=10.0 --set PORT=8000
railway up && railway domain
```

### Hai lỗi gặp khi deploy

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| Build fail: `header key "exclude-patterns" contains value with non-printable ASCII characters` | `.dockerignore` (và đường dẫn thư mục có chữ "Nguyễn") chứa ký tự ngoài ASCII; builder của Railway gửi pattern qua HTTP header | Comment trong `.dockerignore` chỉ dùng ASCII; upload từ thư mục build có đường dẫn ASCII |
| Deploy xong nhưng URL trả `502 Application failed to respond` | Domain trỏ cổng 8000, còn Railway tự cấp `PORT` khác cho container | Đặt biến `PORT=8000` (Dockerfile đọc `${PORT:-8000}`) |

## Test Commands (4 lệnh tự kiểm ở CP6)

```bash
BASE=https://agent-production-1fb71cee.up.railway.app
AGENT_API_KEY=<key đặt trên Railway, không commit>

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy thật (2026-11-25T17:14:23Z):

| Lệnh | Mong đợi | Thực tế |
|---|---|---|
| `GET /health` | 200 | **200** `{"status":"ok","environment":"production"}` |
| `GET /ready` | 200 | **200** `{"status":"ready","redis":"ok"}` |
| `POST /ask` không key | 401 | **401** |
| `POST /ask` có key | 200 | **200** |

Câu trả lời mẫu (`POST /ask` có key, `"What is Docker?"`):

```json
{"question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"input_tokens":3,"output_tokens":19,"cost_usd":1.185e-05}}
```

Checker với URL public:

```text
$ python check_production_ready.py --static-only --public-url https://agent-production-1fb71cee.up.railway.app
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://agent-production-1fb71cee.up.railway.app/health → 200
```

Log khởi động trên Railway (2 worker, Redis kết nối được):

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
[INFO]  ts="2026-11-25T16:59:31.690+00:00" logger="agent" event="startup" pid=4 environment="production" port=8000 rate_limit_per_minute=10 redis_ok=true
[INFO]  ts="2026-11-25T16:59:31.690+00:00" logger="agent" event="startup" pid=3 environment="production" port=8000 rate_limit_per_minute=10 redis_ok=true
INFO:     Application startup complete.
```

## Environment Variables Set (trên nền tảng, không có trong code)

- `AGENT_API_KEY`: secret ngẫu nhiên 48 ký tự hex
- `REDIS_URL=redis://redis.railway.internal:6379/0` (private network)
- `ENVIRONMENT=production`
- `PORT=8000`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`
- `LOG_LEVEL=INFO`

## Screenshots

- [Test results](screenshots/test.png): output 4 lệnh tự kiểm + checker
- [Deployment dashboard](screenshots/dashboard.png) ⏳ (chụp từ Railway)
- [Service running](screenshots/running.png) ⏳ (chụp từ Railway)
