# Deployment Information

> ⏳ Điền URL thật sau khi deploy. Agent được deploy là agent Part 6 trong `06-lab-complete/`.

## Public URL

⏳ `https://<your-app>.up.railway.app`

## Platform

Railway (Dockerfile build, cấu hình trong `06-lab-complete/railway.toml`) + Railway Redis.
Phương án dự phòng: Render Blueprint (`06-lab-complete/render.yaml`: web service Docker + Key Value Redis, `AGENT_API_KEY` dùng `generateValue: true`).

## Các bước deploy (Railway)

```bash
npm i -g @railway/cli
cd 06-lab-complete
railway login
railway init                       # tạo project
railway add --database redis       # thêm Redis
railway variables --set "AGENT_API_KEY=$(openssl rand -hex 24)" \
                  --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
                  --set ENVIRONMENT=production \
                  --set RATE_LIMIT_PER_MINUTE=10 \
                  --set DAILY_BUDGET_USD=1.0 --set MONTHLY_BUDGET_USD=10.0
railway up                         # build bằng Dockerfile
railway domain                     # lấy public URL
python check_production_ready.py --public-url https://<your-app>.up.railway.app
```

## Test Commands (4 lệnh tự kiểm ở CP6)

```bash
BASE=https://<your-app>.up.railway.app
AGENT_API_KEY=<key đã đặt trên Railway — không commit>

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả: ⏳ (dán 4 mã HTTP)

## Environment Variables Set (trên nền tảng, không có trong code)

- `AGENT_API_KEY`: secret, sinh ngẫu nhiên
- `REDIS_URL`: tham chiếu tới Redis của Railway (`${{Redis.REDIS_URL}}`)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`
- `PORT`: Railway tự cấp; `CMD` trong Dockerfile đọc `${PORT:-8000}`
- `LOG_LEVEL` (tuỳ chọn, mặc định `INFO`)

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png) ⏳
- [Service running](screenshots/running.png) ⏳
- [Test results](screenshots/test.png) ⏳
