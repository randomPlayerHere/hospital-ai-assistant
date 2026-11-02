# Load test

Script: `loadtest/k6.js`. 

## 1. Primary Scenario (50 Concurrent Users)
**50 concurrent virtual users** doing realistic non-AI traffic (patient portal reads, reception search/calendar, doctor schedule) with 1-3 s think time, plus 2 logins per second. Targets: browse p95 < 300 ms, errors < 1 %.

```bash
make e2e-up                     # stack with 4 API workers, rate limiting off
k6 run -e BASE_URL=http://localhost:8000 loadtest/k6.js
k6 run -e VUS=50 -e LOGIN_RATE=0 -e DURATION=30s ...   # variations
```

### Result (4 uvicorn workers on developer machine)
| Metric | Value |
|---|---|
| Browse p50 / p90 / **p95** | 20 ms / 44 ms / **67 ms** |
| Slowest endpoint p95 (`slots`) | 87 ms |
| Login p95 (argon2id, 2 logins/s) | 259 ms |
| Error rate | 0 % |
| Throughput | ~70 req/s |

---

## 2. AI Endpoint Load Testing Scenario
AI endpoints are rate-limited in production (`30/minute` per user) and include external LLM API calls. To load test the AI subsystem under concurrent traffic:

```bash
# Run with 5 AI virtual users alongside background traffic:
k6 run -e BASE_URL=http://localhost:8000 -e AI_VUS=5 loadtest/k6.js
```

### Workflow Evaluated
1. **AI Availability Status (`GET /api/ai/status`):** Lightweight probe (p95 < 15 ms).
2. **Deterministic Emergency Red-Flag Pre-Check (`POST /api/ai/triage/message`):**
   - Critical safety evaluation: emergencies ("crushing chest pain", "slurred speech", "sepsis") short-circuit the LLM pipeline immediately.
   - Response time: **p95 < 25 ms**. Deterministic regexes run in-process with zero network overhead.
3. **FAQ Knowledge Retrieval (`POST /api/ai/faq`):**
   - Evaluates TF-IDF in-memory retrieval over `knowledge_base/*.md`.
   - In fallback / degraded mode: **p95 < 35 ms**.
   - With live Anthropic LLM: bounded by Anthropic API roundtrip (~800–1800 ms).
4. **Routine Symptom Triage (`POST /api/ai/triage/message`):**
   - Evaluates structured JSON extraction and conversation persistence.
   - In fallback mode: returns advisory response with clinical safety disclaimer in < 30 ms.
   - With live Anthropic LLM: p95 ~1200–2400 ms.

---

## What we learned (and fixed)
1. **Connection-pool deadlock**: the audit middleware opened a second DB connection while the request still held one; at 50 concurrent requests the shared pool of 20 was exhausted and requests timed out after 30 s. Audit writes now use a separate small pool and run after the response is sent.
2. **argon2 on the event loop** blocked all requests during logins: hashing now runs in a thread pool, with the OWASP-recommended profile (19 MiB, t=2, p=1) instead of the library default (64 MiB, p=4).
3. **Pure ASGI Middleware**: Middleware was converted from `BaseHTTPMiddleware` to pure ASGI and the doctor list N+1 was removed.
4. **Emergency Red-Flag Short-Circuit**: The rule engine bypasses the LLM completely, guaranteeing that acute patients receive immediate emergency diversion in under 25 ms even if the external LLM provider is degraded or experiencing high latency.

## Limits
Offered load beyond roughly 100 req/s (50 VUs with < 1 s think time) saturated the developer machine and pushed p95 to ~0.6-0.9 s. Scale by raising `WEB_CONCURRENCY` and adding DB CPU.
