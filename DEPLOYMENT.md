# Deployment Information — Day 14 Final Project

## Public URL
https://k5-l3-day14-deployment-agent-benchmark-obser-productio-07461da7.up.railway.app

## Platform
**Railway** (Project `triumphant-purpose`, Environment `production`, Root Directory `06-lab-complete`, built from [06-lab-complete/Dockerfile](06-lab-complete/Dockerfile) & [06-lab-complete/railway.toml](06-lab-complete/railway.toml), connected to managed **Railway Redis**).

## Test Commands & Observed Results (CP6 Self-Test)

Đặt biến `BASE` và `AGENT_API_KEY` trong terminal rồi chạy 4 lệnh kiểm tra chuẩn CP6:

```bash
export BASE="https://k5-l3-day14-deployment-agent-benchmark-obser-productio-07461da7.up.railway.app"
export AGENT_API_KEY="<YOUR_AGENT_API_KEY>"

# 1. Liveness health check -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Output: 200

# 2. Readiness check (Redis connected) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Output: 200

# 3. Ask without API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Output: 401

# 4. Ask with valid API key -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Output: 200
```

Kết quả JSON response thực tế:

```json
// GET /health -> HTTP 200
{"status":"ok","environment":"production"}

// GET /ready -> HTTP 200
{"status":"ready","redis":"connected"}

// POST /ask (không có X-API-Key) -> HTTP 401
{"detail":"Invalid or missing API key"}

// POST /ask (có X-API-Key hợp lệ) -> HTTP 200
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","user_id":"anonymous","usage":{"input_tokens":2,"output_tokens":25,"cost_usd":1.53e-05}}
```

Kiểm tra tự động bằng script chấm bài:
```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
# ✅ Public URL: GET https://k5-l3-day14-deployment-agent-benchmark-obser-productio-07461da7.up.railway.app/health → 200
```

## Environment Variables Set on Platform
- `PORT` *(tự động inject bởi Railway — `8080`)*
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` (`${{Redis.REDIS_URL}}` — kết nối trực tiếp tới managed Redis cùng project)
- `AGENT_API_KEY` *(secret cấu hình trực tiếp trên Railway Variables, không commit vào Git)*
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
