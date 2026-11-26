# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích xuất trực tiếp từ các file report trong `reports/`, `benchmark-results/`, Prometheus API, Jaeger UI và các screenshot trong `screenshots/`.

**Ngày chạy:** 2026-11-26  
**Môi trường:** macOS (Apple Silicon), Python 3.11.18, Docker 29.9.2, Docker Compose v5.6.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với mock LLM base latency ~120–180 ms + retrieval ~20 ms, 95% request thông thường hoàn thành ~220–280 ms. Ngưỡng 500 ms tạo khoảng đệm hợp lý cho jitter/tải cao nhưng vẫn đảm bảo trải nghiệm hội thoại phản hồi nhanh và khớp ngưỡng mặc định của `load_test.py`. |
| Error rate `/ask` | `< 2.0 %` | Mock LLM có tỷ lệ lỗi upstream tự nhiên ~1% (`MOCK_ERROR_RATE=0.01`). Đặt SLO < 2.0% (error budget 2%) giúp không báo động giả với dao động ngẫu nhiên nhưng nhanh chóng phát hiện khi lỗi upstream tăng bất thường (alert đặt ở > 5% trong 1 phút). |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu `100%` sau khi sửa KB) | Đảm bảo agent trả lời chính xác kiến thức cốt lõi trước khi deploy; mọi PR có accuracy < 85% hoặc gây regression trên câu từng pass sẽ bị chặn bởi CI quality gate (`.github/workflows/eval.yml`). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Số liệu khớp 100% với `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json` (mỗi lần 300 requests, `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4.41 | 192.5 | 221.4 | 1719.9 | 0.67% (2/300) | PASS |
| 10 | 33.83 | 192.7 | 226.6 | 1712.0 | 0.33% (1/300) | PASS |
| 50 | 103.94 | 200.5 | 280.4 | 1709.1 | 0.67% (2/300) | PASS |
| 100 | 45.32 | 747.1 | 4553.3 | 5037.0 | 0.67% (2/300) | FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency.
- Từ `concurrency=1` → `10` → `50`, RPS tăng mạnh (`4.41` → `33.83` → `103.94 req/s`) nhờ FastAPI/asyncio xử lý I/O không đồng bộ song song hiệu quả trong khi p50 gần như ổn định (~192–200 ms) và p95 vẫn dưới 500 ms.
- Tuy nhiên ở `concurrency=100`, một tiến trình uvicorn đơn bị bão hòa (saturation) về event loop/socket accept queue: requests xếp hàng chờ lâu khiến p50 nhảy lên `747.1 ms`, p95 vọt lên `4553.3 ms` (vi phạm SLO 500 ms), p99 lên `5037.0 ms` và throughput thậm chí **giảm ngược** xuống còn `45.32 req/s`. Đây là minh họa điển hình của điểm uốn bão hòa trong định luật Little / Universal Scalability Law.

### 2.2 Tail latency

Số liệu khớp 100% với `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json` (mỗi lần `--requests 300 --concurrency 20`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| `0` | 189.5 | 220.4 | 237.8 |
| `0.03` (mặc định) | 241.9 | 227.4 | 1696.4 |
| `0.1` | 331.3 | 1689.7 | 1709.6 |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm là `p99` và `p95`.**
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request bị cộng thêm ~1500 ms), `avg` chỉ nhích thêm `+52.4 ms` (`189.5` → `241.9 ms`, trông vẫn rất "đẹp"), nhưng `p99` đã tăng vọt hơn **7 lần** (`237.8` → `1696.4 ms`).
  - Khi `MOCK_SLOW_RATE=0.1` (10% request chậm — vượt ngưỡng 5% đuôi trên), `avg` mới tăng lên `331.3 ms` (vẫn thấp hơn SLO 500 ms), nhưng cả `p95` (`1689.7 ms`) và `p99` (`1709.6 ms`) đều tăng vọt lên gần 1.7 giây.
- **Vì sao SLO không nên đặt theo average?** Average bị kéo về phía đa số request nhanh nên **che giấu nhóm người dùng đang phải chờ rất lâu** (tail latency). Nếu đặt SLO theo `avg < 500 ms`, hệ thống ở `MOCK_SLOW_RATE=0.1` vẫn báo PASS dù cứ 10 người dùng lại có 1 người chờ gần 2 giây. Đặt SLO theo `p95`/`p99` phản ánh trực tiếp trải nghiệm xấu nhất mà một tỷ lệ đáng kể người dùng gặp phải.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu khớp 100% với `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` (23 câu hỏi trong `golden_dataset.jsonl`, `MOCK_ERROR_RATE=0`):

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | **100.00% (23/23)** |
| Avg tokens / câu | 58.1 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000418 | $0.000757 | $0.000790 |
| Cost / câu đúng (USD) | $0.00041775 | $0.00003607 | **$0.00003436** |
| Latency p50 / p95 (ms) | 165.1 / 203.2 | 194.9 / 214.4 | 194.3 / 217.4 |
| Quality gate | **FAIL** | **PASS** (≥ 80%, 0 regression) | **PASS** (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu (`eval_v2.json`) | Đã sửa gì trong `utils/mock_llm.py` (`KNOWLEDGE_BASE`) |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry với từ khóa `["jwt"]` giải thích sự khác biệt giữa API key cố định và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry với từ khóa `["hpa", "kubernetes", "autoscal"]` mô tả Kubernetes HPA scale pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi). |

*(Đã đồng bộ phần sửa `KNOWLEDGE_BASE` sang cả `develop/utils/mock_llm.py` và `production/utils/mock_llm.py`.)*

**Quality gate & CI chặn merge (Exercise 7.3):**
- Khi chạy thử ngược `python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json`, script phát hiện **20 câu bị regression**, in `Quality gate: ❌ FAIL` và trả **exit code `1`**.
- Đã tạo workflow CI tại [`.github/workflows/eval.yml`](.github/workflows/eval.yml): trên mỗi Pull Request vào `main`, GitHub Actions tự khởi động agent v2 và chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. Nếu accuracy < 85% hoặc có regression so với baseline, lệnh trả exit code `1` khiến job CI fail và chặn merge PR.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 (có RAG retrieval) tăng accuracy vượt bậc từ `4.35%` (1/23) lên `91.30%` (21/23) và `100%` (23/23) sau khi bổ sung 2 tài liệu thiếu trong knowledge base.
- **Chi phí:** Mỗi câu hỏi của v2 tốn gần gấp đôi token (`113.7` vs `58.1` tokens/câu) và tổng chi phí gấp ~1.89 lần (`$0.000790` vs `$0.000418`) vì prompt có thêm ngữ cảnh từ bước retrieval. Tuy nhiên xét theo **cost / câu trả lời đúng**, v2 (`$0.00003436`) **rẻ hơn ~12.2 lần** so với v1 (`$0.00041775`) — cho thấy "cost / câu đúng" phản ánh giá trị thực tốt hơn nhiều so với "cost / câu".
- **Latency:** v2 chậm hơn nhẹ (~29 ms ở p50: `194.3 ms` vs `165.1 ms`) do bước tìm kiếm tài liệu (~20 ms). Đánh đổi ~30 ms latency để tăng độ chính xác thêm +95.6 điểm % là hoàn toàn xứng đáng.

**Bổ sung Exercise 7.1 (Metrics & Cardinality):**
- Ví dụ 3 loại metric trong `/metrics`:
  - **Counter:** `http_requests_total{method="POST",route="/ask",status="200"} 1.0`
  - **Gauge:** `agent_in_flight_requests 0.0`
  - **Histogram:** `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0` và metric mới tự thêm `agent_question_length_chars_bucket{le="50.0"} 1.0` (`_count 1.0`, `_sum 40.0`).
- **Vì sao không dùng URL thật (`request.url.path`) làm label?** Khi bot quét hàng nghìn đường dẫn lạ (`/wp-admin`, `/.env`, `/a1b2c3`...), mỗi URL tạo ra một time series mới trên Prometheus → **cardinality explosion**, làm cạn kiệt RAM của Prometheus và làm chậm mọi câu truy vấn PromQL. Gộp route không khớp thành `unmatched` giúp số series luôn nhỏ và bị chặn trên.

---

## 4. Observability stack (production)

### 4.1 Screenshot & trả lời Exercise 7.4

- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời 4 câu hỏi Exercise 7.4 (quan sát thực tế từ Prometheus/Grafana khi chạy 2 instance với Locust 30 users):**
1. **p95 và avg đang là bao nhiêu? Khoảng cách nói lên điều gì?**
   - Tại thời điểm snapshot Prometheus dưới tải 30 users: `avg = 227.8 ms`, `p50 = 182.9 ms`, `p95 = 293.0 ms` (và trên ảnh Grafana tại thời điểm chụp `p95 = 449.23 ms`), trong khi `p99 = 1790.8 ms`. Khoảng cách rõ rệt giữa `avg`/`p50` (~183–228 ms) với đuôi trên `p95`/`p99` (~293–1791 ms) cho thấy phân phối latency bị lệch phải (right-skewed) bởi tail latency ~3% request chậm từ LLM.
2. **Nginx có chia đều traffic cho 2 instance không?**
   - Có. Truy vấn `sum by (instance) (rate(http_requests_total{job="agent",route="/ask"}[1m]))` cho `172.18.0.4:8000 = 4.89 req/s` và `172.18.0.8:8000 = 5.00 req/s` (chênh lệch ~2%), và hai đường trên panel *"Requests/s theo instance"* của Grafana gần như trùng khít nhau nhờ thuật toán round-robin của Nginx.
3. **Vì sao input tokens/s lớn hơn output tokens/s?**
   - Đo thực tế: `input = 762.2 tokens/s` vs `output = 398.5 tokens/s` (gấp ~1.9 lần). Ở agent v2 (RAG), mỗi lần gọi LLM phải gửi kèm `SYSTEM_PROMPT` + tài liệu context lấy từ knowledge base + câu hỏi người dùng trong input, trong khi output chỉ là câu trả lời ngắn gọn.
4. **`curl -i http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`HTTP/1.1 404 Not Found`** từ Nginx (`nginx/1.28.3`). Trong `nginx/nginx.conf`, route `/metrics` bị chặn (`return 404;`) ở tầng reverse proxy bên ngoài để không làm lộ nội bộ hệ thống (tên model, chi phí, số lượng instance, lưu lượng) ra internet; chỉ Prometheus trong mạng nội bộ Docker (`obs_net`) mới scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" (Exercise 7.6)

Unit test alert rules trước thí nghiệm:
```bash
docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
# Processing test file: /p/alert_rules_test.yml -> SUCCESS
```

Kết quả đo thời gian từ lúc thay đổi cấu hình/bơm tải tới lúc alert chuyển sang **firing** (ghi nhận tự động từ `/api/v1/alerts`):

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, giá trị đo `20.29%` > 5%) | **~81s** (`80.9s`) | *Error rate* (Golden Signals đỏ) & *Requests/s theo status code* (`503` tăng mạnh) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, giá trị đo `1.95s` > 1s) | **~141s** (`141.0s`) | *Latency p95* (Golden Signals) & *Latency /ask — p50/p95/p99* |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, giá trị đo `$11.26/giờ` > `$2/giờ`) | **~171s** (`171.1s`) | *Cost burn rate (USD/giờ)* & *LLM cost (1h)* |
| D | `docker pause` 1 instance (`agent-2`) | `AgentInstanceDown` (`for: 30s`, `up == 0`) | **~41s** (`40.5s`) | *Instances up* (giảm từ 2 xuống 1) & *Requests/s theo instance* |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | *Phiên bản đang chạy* (đổi sang `v1`), *Retrieval hit ratio* biến mất & *Tokens/s* giảm |

*(Ảnh `screenshots/prometheus-alert-firing.png` chụp trang `/alerts` của Prometheus cho thấy đồng thời 2 alert đang **FIRING**: `LLMCostBurnRateHigh` `$9.28/giờ` và `AgentInstanceDown` `172.18.0.4:8000`.)*

**Giải thích thí nghiệm D và thí nghiệm E:**
- **Vì sao dùng `docker pause` thay vì `docker stop` ở thí nghiệm D, và vì sao lỗi 504 từ Nginx không hiện trên metric của agent?**
  - Prometheus phát hiện agent bằng DNS service discovery (`dns_sd_configs`). Khi `docker stop`, container biến mất khỏi DNS nên Prometheus không còn thấy target để báo `up == 0`. Khi `docker pause`, container vẫn còn IP trong DNS nhưng bị đóng băng không phản hồi scrape → `up == 0` sau 30s kích hoạt `AgentInstanceDown`.
  - Lỗi `504 Gateway Timeout` do Nginx tự sinh ra khi chờ quá `proxy_read_timeout` với container bị đóng băng; request không bao giờ đi tới vòng trả response của agent nên counter `http_requests_total` bên trong agent không đếm được lỗi này. Vì vậy production cần giám sát thêm metrics ở tầng Nginx/Load Balancer và synthetic probes từ bên ngoài.
- **Thí nghiệm E (`AGENT_VERSION=v1`) không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**
  - Observability hạ tầng (error rate, latency, CPU, instance up) hoàn toàn xanh vì v1 vẫn trả `HTTP 200` nhanh và rẻ hơn v2, nhưng chất lượng câu trả lời tụt từ `100%` xuống `4.3%`. Để phát hiện cần kết hợp:
    1. **Offline CI Eval Quality Gate:** chạy `eval/run_eval.py` trên golden dataset chặn ngay ở bước CI/CD trước khi deploy.
    2. **Online Quality Monitoring:** lấy mẫu (sampling) traffic thật chạy chấm điểm bằng LLM-as-a-judge, theo dõi **retrieval hit ratio** (`agent_retrieval_hits_total` giảm đột ngột về 0 khi đổi sang v1 là tín hiệu cảnh báo trực tiếp!), và theo dõi **user feedback** (thumbs up/down, retry rate).

### 4.3 Debug bằng trace (Exercise 7.5)

**Trace chậm đã phân tích** (`screenshots/jaeger-slow-trace.png`):

- **`trace_id`:** `f28d8d9ba3e5309d75e0e16117e23520`
- **Tổng thời gian (`POST /ask`):** **`1718.3 ms`** (`1.7s` trên Jaeger UI)
- **Phân rã các span:**
  - `POST /ask`: `1718.3 ms`
  - `agent.run`: `1715.7 ms`
  - `agent.retrieve_context`: `23.1 ms` (`1.3%`)
  - **`chat mock-llm-small`:** **`1692.3 ms` (`98.5%` tổng thời gian)** — đây là span chiếm gần như toàn bộ độ trễ, khẳng định nút thắt nằm ở lời gọi LLM upstream chứ không phải logic xử lý hay retrieval của agent.
- **Dòng log JSON tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):**

```json
{"ts": "2026-11-26T08:20:07.707647+00:00", "level": "INFO", "service": "observable-agent", "instance": "1ca13bcfc63e", "event": "llm_call", "trace_id": "f28d8d9ba3e5309d75e0e16117e23520", "span_id": "a59fcfde257207eb", "request_id": "1a6eff8de6a7", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1691.9}
```

**Trace lỗi đã phân tích** (`screenshots/jaeger-error-trace.png`):
- **`trace_id`:** `d38c5a107243547bf84db4fd9a707243`
- Span lỗi `chat mock-llm-small` (`858 ms`) ghi nhận event `exception` với `exception.type = utils.mock_llm.LLMError`, `exception.message = Upstream LLM error: 503 Service Unavailable (mock)` và stacktrace đầy đủ.
- **Dòng log JSON tương ứng:**

```json
{"ts": "2026-11-26T08:19:41.490189+00:00", "level": "INFO", "service": "observable-agent", "instance": "1ca13bcfc63e", "event": "llm_error", "trace_id": "d38c5a107243547bf84db4fd9a707243", "span_id": "cdfadf4bea3fd8b0", "request_id": "eb06ca6eb5f8", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu khớp 100% với `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` (dòng `POST /ask` và `Aggregated`):

| Số instance | Endpoint | Total reqs | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---|---:|---:|---:|---:|---:|---:|
| **1** | `POST /ask` | 7,136 | **59.79** | **200** | **260** | **1700** | **68** (0.95%) |
| **1** | `Aggregated` (`/ask` + `/health`) | 7,821 | 65.53 | 190 | 250 | 1700 | 68 (0.87%) |
| **3** | `POST /ask` | 6,995 | **58.86** | **200** | **500** | **1700** | **63** (0.90%) |
| **3** | `Aggregated` (`/ask` + `/health`) | 7,693 | 64.73 | 190 | 390 | 1700 | 63 (0.82%) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện RPS hay p95/p99** (`p50` giữ nguyên `200 ms`, `p99` giữ nguyên `1700 ms`, `RPS` gần như không đổi ~59 req/s cho `/ask`, thậm chí `p95` của 3 instance là `500 ms` vs `260 ms` do dao động mẫu tail latency và cạnh tranh CPU host giữa 3 container + Prometheus/Grafana/Jaeger/Locust trên cùng máy local).
- **Nút thắt nằm ở đâu?**
  1. **Upstream LLM latency (I/O-bound):** Theo Jaeger trace, ~98.5% thời gian mỗi request là chờ LLM (`~120–180 ms` bình thường và `+1500 ms` cho 3% slow requests). Thêm số lượng replica của agent không làm API LLM bên ngoài trả lời nhanh hơn được.
  2. **Giới hạn tải đầu vào từ Locust:** 100 user ảo với `wait_time` nghỉ giữa các request chỉ tạo ra lưu lượng tối đa ~60 req/s `/ask` — mức tải mà **1 instance async FastAPI đã dư sức phục vụ** mà chưa chạm ngưỡng CPU/event-loop saturation. Scale ngang lên 3 instance chỉ thực sự tăng thông lượng khi bản thân tầng agent bị nghẽn CPU/kết nối đồng thời, đồng thời mang lại **high availability (chịu lỗi khi 1 instance chết)**.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Percentile quan trọng hơn average:** Average dễ che giấu tail latency (`avg = 241.9 ms` nhưng `p99 = 1696.4 ms`), vì vậy SLO và cảnh báo phải dựa trên `p95`/`p99`.
  2. **Metrics, Traces và Logs bổ trợ lẫn nhau thành vòng tròn debug khép kín:** Metrics trên Grafana báo động *có vấn đề gì*, Jaeger trace chỉ chính xác *chậm/lỗi ở span nào* (`chat mock-llm-small` chiếm 98.5% thời gian), và `trace_id` liên kết thẳng tới dòng log JSON chi tiết.
  3. **Hạ tầng xanh không đồng nghĩa agent trả lời đúng:** Đổi sang `v1` không kích hoạt bất kỳ alert hạ tầng nào dù accuracy rơi từ `100%` xuống `4.35%`; bắt buộc phải kết hợp **eval quality gate** trong CI và giám sát chỉ số chất lượng ở production.
- **Nếu đưa agent lên production thật, sẽ thêm các metric / alert nào?**
  - **Nginx / Load Balancer metrics:** tỷ lệ lỗi `502`/`504` và kết nối upstream timeout (bù cho điểm mù đã thấy ở thí nghiệm D).
  - **RAG & Quality metrics:** alert khi `retrieval_hit_ratio < 0.7` trong 5 phút (bắt sớm sự cố mất RAG như thí nghiệm E), kèm điểm đánh giá chất lượng online (LLM-as-judge / tỷ lệ thumbs-down của người dùng).
  - **Rate-limit & Cost-guard metrics:** đếm số request bị chặn `429` và `402` theo từng nhóm key, cảnh báo sớm khi mức sử dụng ngân sách chạm 80% trước khi cắt dịch vụ ở 100%, cùng với Redis latency/connection pool saturation và **TTFT (Time To First Token)** nếu bật streaming.
