# Deployment Information — Day 14 Final Project

> **Lưu ý:** Cập nhật `Public URL` và chụp 3 ảnh (`screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`) ngay sau khi deploy `06-lab-complete/` lên Railway hoặc Render.

## Public URL
`https://<your-agent-domain>.up.railway.app` *(thay bằng URL public sau khi chạy `railway up && railway domain` hoặc deploy Render Blueprint)*

## Platform
Railway (dùng [06-lab-complete/railway.toml](06-lab-complete/railway.toml)) hoặc Render (dùng [06-lab-complete/render.yaml](06-lab-complete/render.yaml))

## Deploy Steps (Railway — khuyến nghị)

```bash
cd 06-lab-complete
npm i -g @railway/cli
railway login
railway init
# Tạo Redis plugin/service trên Railway Dashboard, sau đó gán biến môi trường:
railway variables set ENVIRONMENT=production LOG_LEVEL=INFO RATE_LIMIT_PER_MINUTE=10 DAILY_BUDGET_USD=10.0 MONTHLY_BUDGET_USD=10.0
railway variables set AGENT_API_KEY="<STRONG_RANDOM_SECRET>"
railway variables set REDIS_URL="<RAILWAY_REDIS_URL>"
railway up
railway domain
```

## Test Commands (4 lệnh tự kiểm CP6)

Đặt biến `BASE` và `AGENT_API_KEY` trong terminal rồi chạy:

```bash
export BASE="https://<your-agent-domain>.up.railway.app"
export AGENT_API_KEY="<YOUR_AGENT_API_KEY>"

# 1. Liveness health check -> Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (Redis connected) -> Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Ask without API key -> Expected: 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Ask with valid API key -> Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

Kiểm tra thêm bằng script chấm bài:
```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set on Platform
- `PORT` *(tự động inject bởi nền tảng, mặc định `8000`)*
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` *(trỏ tới managed Redis service trên nền tảng)*
- `AGENT_API_KEY` *(secret đặt trên dashboard/CLI, không lưu trong Git)*
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
