# Day 14 Lab — Mission Answers

> **Họ tên:** Trần Hải Long · **MSSV:** `2A202603891` · **Lớp:** `K5-L3B`  
> **Ngày thực hiện:** 2026-11-26  
> **Môi trường:** macOS (Apple Silicon), Python 3.11.18, Docker 29.9.2, Docker Compose v5.6.1

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn (`develop/app.py` dòng 17–18):** Khai báo trực tiếp `OPENAI_API_KEY` (`sk-hardcoded-...`) và `DATABASE_URL` (`postgresql://admin:<hardcoded>@localhost:5432/mydb`) ngay trong code. Nếu push lên GitHub (đặc biệt repo public), secret lộ ngay lập tức và bị bot thu hoạch trong vài giây. Trong `production/config.py` (dòng 27, 32), các biến nhạy cảm được đọc từ `os.getenv(...)` và validate ở startup.
2. **Không có config management / hardcode `DEBUG = True` (`develop/app.py` dòng 21–22):** Các thông số `DEBUG`, `MAX_TOKENS` bị viết cứng, không thể đổi giữa dev / staging / production mà không sửa code. `production/config.py` (dòng 15–50) tập trung mọi cấu hình vào dataclass `Settings` đọc từ biến môi trường.
3. **Dùng `print()` thay cho structured logging và in thẳng secret ra log (`develop/app.py` dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa làm lộ API key vào log hệ thống, vừa không có timestamp/level/JSON format để log aggregator (Loki, Datadog, Cloud Logging) lọc và truy vấn. `production/app.py` (dòng 28–32, 111–122) dùng `logging` định dạng JSON và chỉ log metadata (`question_length`, `client_ip`).
4. **Không có Health Check và Readiness endpoint (`develop/app.py` dòng 42–43):** Thiếu `GET /health` và `GET /ready`, nên cloud platform/orchestrator không biết khi nào container bị treo để restart hay khi nào instance đã sẵn sàng nhận traffic. `production/app.py` (dòng 135–161) cung cấp đầy đủ `/health` và `/ready` (trả `503` khi `is_ready = False`).
5. **Bind cứng `host="localhost"`, `port=8000` và bật `reload=True` (`develop/app.py` dòng 49–54):**
   - `host="localhost"` chỉ nghe trên loopback `127.0.0.1`, không nhận được kết nối từ bên ngoài container.
   - `port=8000` cố định làm app fail trên Railway/Render/Cloud Run (nơi nền tảng cấp cổng động qua biến `PORT`).
   - `reload=True` theo dõi file liên tục, tốn tài nguyên và gây mất ổn định trong production.
   - `production/app.py` (dòng 194–199) bind `settings.host` (`0.0.0.0`), `settings.port` (từ `PORT`) và chỉ bật `reload` khi `DEBUG=true`.
6. **Không có Graceful Shutdown (`develop/app.py`):** Khi nhận `SIGTERM` lúc deploy mới hoặc scale down, process dừng đột ngột, cắt ngang request đang xử lý. `production/app.py` dùng `lifespan` (dòng 39–67) để đặt `is_ready = False`, hoàn thành request đang chạy rồi mới thoát.
7. **Không có validation input và CORS (`develop/app.py` dòng 30–31):** Nhận `question` trực tiếp qua query string không giới hạn độ dài, không cấu hình CORS. `production/app.py` (dòng 77–82, 102–108) thêm `CORSMiddleware` theo `ALLOWED_ORIGINS` và trả HTTP `422` khi thiếu `question`.

### Exercise 1.2: Kết quả chạy bản `develop`

```bash
curl -sS -i -X POST "http://localhost:8000/ask?question=Hello"
```

```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:00:52 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Kết quả chạy bản `production` để đối chiếu:

```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:00:55.413076+00:00"}

# GET /ready
HTTP/1.1 200 OK
{"ready":true}

# POST /ask (JSON body)
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode trong `app.py` (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`) | Đọc từ biến môi trường qua `Settings` (`config.py`), validate fail-fast lúc startup | Tránh lộ secret khi push Git; cùng một artifact/image chạy được trên dev, staging, production chỉ bằng đổi env vars (12-Factor). |
| **Network Binding & Port** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=PORT` từ env, `reload=settings.debug` | Container chỉ nhận traffic ngoài khi bind `0.0.0.0`; cloud PaaS inject `PORT` động; tắt `reload` để ổn định và tiết kiệm CPU. |
| **Health & Readiness** | Không có | Có `GET /health` (liveness) và `GET /ready` (readiness, trả 503 khi chưa sẵn sàng) | Platform tự động restart container chết (liveness) và chỉ route traffic tới instance sẵn sàng (readiness), giúp deploy không downtime. |
| **Logging** | `print()` plain text, còn in cả `OPENAI_API_KEY` | Structured JSON logging qua `logging`, không log secret | Log JSON dễ parse, index, lọc theo event/level trên Datadog/Loki/Cloud Logging và bảo đảm an toàn thông tin nhạy cảm. |
| **Shutdown** | Tắt đột ngột | `lifespan` hạ `is_ready = False`, xử lý nốt in-flight requests | Tránh trả lỗi 502/connection reset cho người dùng đang chờ phản hồi khi rolling deploy hoặc scale down. |
| **API & Security** | Query param, không CORS, không validate | JSON body, validate (422), `CORSMiddleware` giới hạn origin | Chuẩn REST API, hạn chế truy cập cross-origin trái phép và bảo vệ backend khỏi input rỗng/sai định dạng. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` — image Debian đầy đủ kèm toàn bộ Python 3.11, compiler và nhiều tiện ích hệ thống (~1 GB trước khi cài pip packages).
2. **Working directory là gì?** `/app` (`WORKDIR /app`) — thư mục làm việc mặc định trong container cho mọi lệnh `COPY`, `RUN`, `CMD` phía sau.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`?** Để tận dụng **Docker build layer cache**. Khi chỉ sửa code (`app.py`) mà không đổi `requirements.txt`, Docker tái sử dụng cache của layer `pip install`, giảm thời gian rebuild từ vài chục giây xuống dưới 1 giây.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` định nghĩa lệnh hoặc tham số mặc định, có thể bị ghi đè hoàn toàn khi truyền lệnh mới ở cuối `docker run <image> <command>`.
   - `ENTRYPOINT` cố định chương trình thực thi chính của container; các tham số truyền thêm trong `docker run` được nối vào sau `ENTRYPOINT` (chỉ đổi được khi dùng cờ `--entrypoint`).

### Exercise 2.2: Build và chạy container `my-agent:develop`

Lệnh build từ gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm -p 18021:8000 my-agent:develop
curl -sS -i -X POST "http://localhost:18021/ask?question=What%20is%20Docker%3F"
```

Kết quả trả về từ container:
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:05:28 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & So sánh kích thước image

**Phân tích `02-docker/production/Dockerfile`:**
- **Stage 1 (`builder`, từ `python:3.11-slim`):** Cài build tools (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`, từ `python:3.11-slim`):** Tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local`, copy `main.py` và `utils/mock_llm.py`, cấu hình `HEALTHCHECK` và chạy `uvicorn` với 2 workers.
- **Tại sao image nhỏ hơn?** Vì stage `runtime` dùng base `python:3.11-slim` và loại bỏ toàn bộ compiler (`gcc`, `libpq-dev`), apt headers và file tạm ở stage `builder`, chỉ giữ lại Python runtime + site-packages cần thiết để chạy app.

**Kích thước đo thực tế bằng `docker images` và `docker image inspect`:**

```text
REPOSITORY:TAG       SIZE
my-agent:develop     1.67GB   (1,672.2 MB / 1,594.7 MiB)
my-agent:advanced    266MB    (265.5 MB / 253.2 MiB)
```

- **Develop:** `1672.2 MB` (`1.67 GB`)
- **Production (multi-stage):** `265.5 MB` (`266 MB`)
- **Chênh lệch (giảm):** **`-84.1%`** (nhỏ hơn khoảng 6.3 lần, đạt chuẩn < 500 MB)

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc các service (cùng mạng `internal`):**

```text
┌──────────┐       HTTP :80        ┌──────────────────┐
│  Client  │ ────────────────────▶ │  nginx (alpine)  │
└──────────┘                       │  ports: 80, 443  │
                                   └────────┬─────────┘
                                            │ reverse proxy (:8000)
                                            ▼
                                   ┌──────────────────┐
                                   │  agent (FastAPI) │
                                   │  internal :8000  │
                                   └───┬──────────┬───┘
                  REDIS_URL :6379      │          │     QDRANT_URL :6333
                       ┌───────────────┘          └───────────────┐
                       ▼                                          ▼
            ┌────────────────────┐                     ┌────────────────────┐
            │ redis:7-alpine     │                     │ qdrant:v1.9.0      │
            │ vol: redis_data    │                     │ vol: qdrant_data   │
            └────────────────────┘                     └────────────────────┘
```

- Các service giao tiếp nội bộ qua Docker bridge network `internal` bằng tên service (DNS nội bộ: `agent`, `redis`, `qdrant`). Chỉ `nginx` mở cổng `80`/`443` ra host; `agent`, `redis`, `qdrant` không expose port ra ngoài để tăng bảo mật. `agent` dùng `depends_on` với `condition: service_healthy` cho `redis` và `qdrant`.

**Kết quả test thực tế qua Nginx (`http://localhost`):**

```http
# curl -sS -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 08:05:50 GMT
Content-Type: application/json
Content-Length: 95
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":7.5,"version":"2.0.0","timestamp":"2026-11-26T08:05:50.219369"}

# curl -sS -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Date: Thu, 26 Nov 2026 08:05:50 GMT
Content-Type: application/json
Content-Length: 103
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 (`06-lab-complete/`)

- **Nền tảng chính:** **Railway** (Root Directory `06-lab-complete`, sử dụng `06-lab-complete/Dockerfile` + `06-lab-complete/railway.toml`, kết nối managed **Redis** qua biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}`, đặt `AGENT_API_KEY` qua Railway Variables — không ghi vào code).
- **Public URL:** https://k5-l3-day14-deployment-agent-benchmark-obser-productio-07461da7.up.railway.app
- **Chi tiết & lệnh kiểm tra:** Xem [DEPLOYMENT.md](DEPLOYMENT.md).
- **Kết quả 4 lệnh tự kiểm CP6 trên URL public:**
  - `GET /health` → **`200`** (`{"status":"ok","environment":"production"}`)
  - `GET /ready` → **`200`** (`{"status":"ready","redis":"connected"}`)
  - `POST /ask` (không có key) → **`401`** (`{"detail":"Invalid or missing API key"}`)
  - `POST /ask` (có `X-API-Key: $AGENT_API_KEY`) → **`200`** (`{"question":"Hello","answer":"...","user_id":"anonymous","usage":{"input_tokens":2,"output_tokens":25,"cost_usd":1.53e-05}}`)
- **Screenshots:**
  - [Dashboard (Agent + Redis Online)](screenshots/dashboard.png)
  - [Service Running & JSON Logs](screenshots/running.png)
  - [CP6 Public URL Curl Test Results](screenshots/test.png)

### So sánh `railway.toml` vs `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` (Blueprint) | Giải thích sự khác biệt |
|---|---|---|---|
| **Định dạng & phạm vi** | TOML, cấu hình **một service đơn lẻ** (`[build]`, `[deploy]`). | YAML (Infrastructure as Code), khai báo được **nhiều service cùng lúc** (web service + managed Redis/Postgres) trong cùng một file. | Render Blueprint hướng tới đồng bộ toàn bộ stack từ Git; Railway quản lý từng service riêng và nối Redis qua UI/CLI variable reference. |
| **Cách build** | `builder = "DOCKERFILE"` (hoặc `NIXPACKS`/`RAILPACK`), `dockerfilePath = "Dockerfile"`. | `runtime: docker` + `dockerfilePath: ./Dockerfile` (hoặc `runtime: python` + `buildCommand` + `startCommand`). | Cả hai đều hỗ trợ Dockerfile, nhưng Render yêu cầu khai báo rõ `type: web`, `plan`, `region` trong YAML. |
| **Biến môi trường & Secrets** | Không khai báo env vars trong `railway.toml`; đặt qua Railway Dashboard hoặc `railway variables set`. | Khai báo trực tiếp danh sách `envVars` trong YAML; secret dùng `generateValue: true` (Render tự sinh) hoặc `sync: false` (nhập tay trên dashboard, không commit). | Render kiểm soát cấu hình biến môi trường dưới dạng code (IaC) mà vẫn không lộ secret; Railway tách hẳn config deploy và env vars. |
| **Healthcheck & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`. | `healthCheckPath: /health`, `autoDeploy: true` (chính sách restart do Render quản lý mặc định). | Railway cho tùy chỉnh chi tiết restart policy và timeout trong file config; Render tập trung vào zero-downtime deploy dựa trên `healthCheckPath`. |

### Exercise 3.3: Phân tích CI/CD Pipeline GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` chạy tự động qua **4 bước tuần tự** (`waitFor`) khi push lên nhánh `main`:
1. **`test` (`python:3.11-slim`):** Cài `requirements.txt` và `pytest`, chạy toàn bộ unit test (`pytest tests/ -v`); nếu test fail thì dừng pipeline ngay, không build image lỗi.
2. **`build` (`gcr.io/cloud-builders/docker`):** Build Docker image gắn cả tag `$COMMIT_SHA` (bất biến để rollback) và `latest`, tận dụng `--cache-from` để tăng tốc build.
3. **`push` (`gcr.io/cloud-builders/docker`):** Đẩy tất cả các tag image lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy` (`gcr.io/cloud-builders/gcloud`):** Deploy image theo `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình `min-instances=1` (tránh cold start), `max-instances=10`, `512Mi` RAM / `1` vCPU, `timeout=60s`, và nạp secret từ **Secret Manager** (`--set-secrets=OPENAI_API_KEY=openai-key:latest`). File `service.yaml` (Knative IaC) mô tả trạng thái chuẩn tương ứng kèm `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Trong dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)`, rồi gắn vào `/ask` bằng `Depends(verify_api_key)` (dòng 70). `/health` và `/` được để public.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Thiếu header trả `401 Unauthorized`; gửi sai key trả `403 Forbidden` (ở Part 6 production agent ta chuẩn hóa cả hai trường hợp về `401 Unauthorized` theo hợp đồng chấm bài).
- **Cách rotate key an toàn không downtime:** Hỗ trợ đồng thời 2 key (ví dụ `AGENT_API_KEY_PRIMARY` và `AGENT_API_KEY_SECONDARY` dạng tập hợp các key hợp lệ), phát hành key mới cho client chuyển sang, theo dõi log đảm bảo không còn traffic dùng key cũ, rồi xóa key cũ khỏi biến môi trường và reload/restart service.

**Output test thực tế (`AGENT_API_KEY=secret-key-123`):**

```http
# Không có key → 401
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 08:02:42 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Có key hợp lệ → 200
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:02:42 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **JWT Flow (`auth.py`):** Client gửi `POST /auth/token` với `{"username": "student", "password": "demo123"}` → server xác thực và ký JWT bằng `HS256` chứa claims `sub`, `role`, `iat`, `exp` (60 phút) → các request tới `/ask` đính kèm `Authorization: Bearer <TOKEN_MASKED>` → `verify_token` giải mã chữ ký stateless mà không cần tra database mỗi request.
- **Rate Limiter (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window Counter** (dùng `deque` lưu timestamp các request trong 60 giây gần nhất, xóa các timestamp cũ hơn `now - 60`).
  - **Giới hạn:** `10 requests/phút` cho role `user` (`student`) và `100 requests/phút` cho role `admin` (`teacher`).
  - **Admin xử lý khác thế nào?** Trong `app.py` (dòng 141), `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user` — dựa vào `role` trong JWT để gán hạn mức cao hơn (100 req/phút) hoặc có thể bỏ qua kiểm tra nếu cần bypass hoàn toàn cho admin.

**Output test thực tế (`curl -i`, đã che JWT token):**

```http
# Không có JWT token → 401
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 08:02:44 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Request 1 với Authorization: Bearer <REDACTED_JWT_TOKEN> → 200
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:02:44 GMT
server: uvicorn
content-length: 215
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Vòng lặp gửi liên tiếp (Calls 2..10 đều trả HTTP 200; từ Call 11 vượt giới hạn 10 req/phút → 429):
Call 2 -> HTTP 200
Call 3 -> HTTP 200
Call 4 -> HTTP 200
Call 5 -> HTTP 200
Call 6 -> HTTP 200
Call 7 -> HTTP 200
Call 8 -> HTTP 200
Call 9 -> HTTP 200
Call 10 -> HTTP 200

# Call 11 (full headers) → 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 08:02:45 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795680226
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Call 12 -> HTTP 429
```

### Exercise 4.4: Cost Guard Implementation

- **Tại sao cần cả Rate Limit và Cost Guard?** Rate limit chỉ giới hạn *tốc độ gọi* (số request/phút), nhưng một user gọi đều đặn dưới ngưỡng rate limit với prompt cực dài hoặc dùng model đắt tiền vẫn có thể làm hóa đơn LLM tăng vọt. Cost guard bảo vệ *ngân sách tiền thực tế* bằng cách cộng dồn chi phí token.
- **Cách triển khai trong production (Redis-backed, đã áp dụng ở Part 6 `06-lab-complete/app/cost_guard.py`):**
  1. Trước khi gọi LLM (`check_budget()`): đọc tổng chi phí tích lũy từ Redis theo key ngày (`cost:daily:YYYY-MM-DD`) và theo tháng (`cost:monthly:YYYY-MM`). Nếu `spent >= DAILY_BUDGET_USD` hoặc `spent >= MONTHLY_BUDGET_USD`, chặn ngay với `HTTP 402 Payment Required` trước khi tốn thêm token.
  2. Sau khi gọi LLM (`record_cost(input_tokens, output_tokens)`): tính `cost = (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006`, cộng atomic vào Redis bằng `INCRBYFLOAT` và đặt `EXPIRE` (2 ngày cho key ngày, 35 ngày cho key tháng) để tự reset chu kỳ mới và tránh rò rỉ bộ nhớ.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Checks & Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

- **Phân biệt `/health` (Liveness) vs `/ready` (Readiness):**
  - `GET /health` kiểm tra *process còn sống không*. Nếu fail, platform (Kubernetes/Railway/Render) sẽ **restart container**. Do đó `/health` không nên phụ thuộc Redis (nếu Redis chập chờn mà `/health` trả 500 thì mọi agent bị restart hàng loạt gây crash loop).
  - `GET /ready` kiểm tra *instance đã sẵn sàng nhận traffic chưa* (đã load xong model, Redis kết nối được, không trong trạng thái shutdown). Nếu trả `503`, load balancer chỉ **tạm ngừng route traffic** tới instance đó mà không restart.
- **Graceful Shutdown (SIGTERM):** Khi nhận `SIGTERM`, app chuyển `_is_ready = False`, ngừng nhận kết nối mới, chờ các request đang chạy (`in_flight_requests`) hoàn tất rồi đóng tài nguyên và thoát với exit code `0`.

**Kết quả test thực tế (`05-scaling-reliability/develop/app.py`):**

```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:02:49.218121+00:00","checks":{"memory":{"status":"ok","used_percent":83.2}}}

# GET /ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

# Request đang chạy (POST /ask?question=Long%20task) khi gửi kill -TERM vẫn hoàn thành 200 OK:
HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Log ghi nhận lúc nhận SIGTERM:
```text
2026-11-26 15:02:49,299 INFO Received signal 15 — uvicorn will handle graceful shutdown
INFO:     127.0.0.1:49899 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
```

### Exercise 5.3, 5.4 & 5.5: Stateless Design & Load Balancing với Nginx (`--scale agent=3`)

- **Tại sao state trong RAM bị hỏng khi scale nhiều instance?** Khi Nginx phân tải round-robin qua 3 container `agent`, request 1 của user vào `agent-1` (lưu lịch sử trong RAM của `agent-1`), request 2 sang `agent-2` thì RAM của `agent-2` không có dữ liệu → mất ngữ cảnh hội thoại. Chuyển toàn bộ session (`session:<id>`) sang **Redis** (có TTL) giúp mọi instance hoàn toàn stateless và có thể thêm/bớt/restart bất cứ lúc nào.

**Lệnh chạy thực tế:**
```bash
cd 05-scaling-reliability/production
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
docker compose -p k5-day14-scaling down -v
```

**Kết quả `test_stateless.py` (cổng `8080`, endpoint `POST /chat`):**
```text
Total requests: 5
Instances used: {'instance-76a5ff', 'instance-9f0af1', 'instance-744692'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 câu hỏi liên tiếp trong cùng một `session_id` được Nginx chia đều tới cả **3 instance khác nhau** (`instance-76a5ff`, `instance-9f0af1`, `instance-744692` — xác nhận trong `docker compose logs agent` mỗi instance đều ghi `Storage: Redis ✅` và xử lý 1–2 request), nhưng khi gọi `GET /chat/{session_id}/history` vẫn nhận đủ toàn bộ **10 messages** (5 user + 5 assistant) nhờ lưu tập trung trong Redis.

---

## Part 6: Final Project — Output `check_production_ready.py`

Chạy đầy đủ (bao gồm static checks, runtime checks với `uvicorn --workers 2` + Redis, và Docker build/run/stop) trong `06-lab-complete/`:

```text
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

Một số chỉ số đo được từ lần chạy chấm bài:
- Kích thước Docker image multi-stage (`python:3.11-slim`, non-root `appuser`): **262 MB** (< 500 MB)
- Thời gian `docker stop`: **0.6s**, **exit code 0** (< 10s, không bị SIGKILL 137)
- Rate limit: trả `429` sau đúng 5 request (`RATE_LIMIT_PER_MINUTE=5`) và vẫn trả `429` sau khi restart agent (state lưu trên Redis)
- Readiness: `/ready` trả `200` khi Redis kết nối, trả `503` khi Redis mất kết nối trong khi `/health` vẫn giữ `200`
- Cost guard: trả `402` ngay khi vượt budget
- Structured logging: toàn bộ log của app đều là JSON hợp lệ

---

## AI Usage Log

- **Công cụ sử dụng:** Antigravity (AI coding assistant).
- **Mục đích sử dụng:**
  - Hỗ trợ kiểm tra cấu trúc bài lab, thiết kế và hoàn thiện các module trong `06-lab-complete/` (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`).
  - Hỗ trợ chạy và tổng hợp số liệu thực tế từ các bài tập Part 1–5 và Part 7 (load test, eval quality gate, observability stack, chaos alerts).
  - Rà soát tiêu chí rubric, cấu trúc nộp bài và đảm bảo không lộ secret/credentials trong mã nguồn và lịch sử commit.
- **Xác minh thủ công:** Toàn bộ lệnh `check_production_ready.py`, Docker build/compose, `test_stateless.py`, `load_test.py`, `run_eval.py`, `promtool test rules`, và Locust đều được chạy trực tiếp trên máy và kiểm chứng kết quả đầu ra thực tế.
