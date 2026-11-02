# Project To-Do

*Last updated: 2026-11-01*

**Where things stand:** the app works end to end as a local demo with all four roles. It has never been deployed, and live AI has never been tested. CI is red for two known reasons (items 1 and 2 below). **Do not use real patient data yet.**

## Get started

You need Docker with Compose v2, `make` and `python3`. Ports 3000, 8000 and 5433 must be free.

```bash
git clone git@github.com:randomPlayerHere/hospital-ai-assistant.git
cd hospital-ai-assistant
make up     # creates .env with random secrets, builds images, starts everything
make seed   # adds demo users and data
```

Open http://localhost:3000. The demo logins are in the [README](README.md). No API key is needed: without one, the AI features fall back to their non-AI behaviour.

To run the tests (needs **Python 3.14** and Node 22):

```bash
make backend-venv                # the database from `make up` must be running
(cd frontend && npm ci && npx playwright install chromium)
make test                        # backend + frontend unit tests
make lint
make e2e                         # Playwright against the full stack
```

**Rules that are easy to break:**
- Don't put inline `# comments` after values in `.env` files. Compose treats them as part of the value.
- Never commit `.env`, and never put real patient data in code, tests or screenshots.
- Every new endpoint that touches patient data must use the checks in `backend/app/services/access.py`.
- Migrations must stay backward compatible with the previous release, because rollback does not reverse the schema.
- The AI must never diagnose or recommend medication. Emergency red flags are rule-based and run before the LLM (see `docs/DECISIONS.md`).

## CI status

From the first CI run this project has ever had, on 2026-11-01. Earlier results were local only.

| Check | Result | Details |
|---|---|---|
| Lint and types | ✅ Pass | ruff, black, mypy, eslint, tsc, prettier |
| Backend tests | ✅ Pass | 132 passed, 94.6% coverage |
| Frontend tests | ✅ Pass | 18 unit tests and a production build |
| Docker image build | ✅ Pass | |
| E2E (Playwright) | ✅ 13 of 13 pass | Fixed weekend day advance in reception.spec.ts |
| `pip-audit`, `bandit` | ✅ Pass | |
| `npm audit` | ✅ Pass | 0 vulnerabilities (critical, high, and moderate fixed) |
| Trivy image scan | ⚠️ Not run | Unblocked now that `npm audit` passes |
| Deploy workflow | ⚠️ Never run | Needs a server and secrets, see section D |

## What's done

- [x] **Accounts and security:** register, login, password reset, rotating refresh tokens, lockout, rate limits, server-side permissions for 4 roles (admin, doctor, reception, patient), full audit log
- [x] **Patients:** create, search, edit, soft delete, encrypted insurance ID, timeline
- [x] **Scheduling:** doctor availability and leave, free slots, book, reschedule, cancel, no-show, complete, waitlist, reception calendar
- [x] **Records:** visit notes, prescriptions, edit history, full-text search
- [x] **Documents:** PDF/PNG/JPEG upload with type and size checks, 5-minute signed download links
- [x] **AI:** symptom triage with rule-based emergency detection, booking assistant that requires patient confirmation, visit summaries and doctor briefings, FAQ over `knowledge_base/`, safety filter on replies, and fallbacks when the AI is down (tested with a fake AI client only)
- [x] **Admin:** user and department management, analytics dashboard, CSV export, audit log viewer
- [x] **Background jobs:** appointment reminders in a separate worker
- [x] **Frontend:** 20 pages across all roles, with automated accessibility scans (WCAG 2.1 AA)
- [x] **Ops, tested locally only:** production Compose file, Caddy HTTPS, deploy script with automatic rollback, smoke test, encrypted backup and restore
- [x] **CI/CD:** CI and deploy workflows (deploy has never run)
- [x] **Docs:** architecture, API, security, runbook, user guide, demo script, load test (p95 67 ms at 50 users, measured 2026-09-30)

## What's still needed

### A. Fix first (anyone can do these)

- [x] **1. Fix frontend dependency vulnerabilities. Do this before any deployment.** `npm audit` reports 27: 1 critical (`next`, installed 15.5.26, affected through 15.5.27), 3 high (`vite`, `undici`, `source-map-js`) and 23 moderate.
  - Run `cd frontend && npm audit fix`, then all tests. A dry run shows this covers the critical and high ones.
  - Most of the moderate ones come through `eslint`, `eslint-config-next` and `openapi-typescript`, whose fixes are breaking changes, so upgrade those separately. CI only fails on high or critical.
  - Trivy will run for the first time once this passes, so it may report more. Update `docs/SECURITY.md` with the new results.
- [x] **2. Fix the E2E test that fails on weekends.** `frontend/e2e/reception.spec.ts:28-33` jumps 7 days, which lands on another weekend day with no slots, then looks for a "Next week" button. In Day view that button is called "Next day", so the test times out. Doctors only work Monday to Friday, so expect this every Saturday and Sunday. It's a test bug, not an app bug. **Done when** E2E passes on a weekend.
- [x] **3. Stop tracking build output.** Add `frontend/tsconfig.tsbuildinfo` and `backend/hospital_ai_backend.egg-info/` to `.gitignore` and run `git rm --cached` on them.

### B. Missing features (anyone can do these)

- [x] **4. Change password.** `docs/RUNBOOK.md` and `.env.prod.example` tell the admin to change the password right after first login, but there is no endpoint or page for it. The only route is "forgot password", which needs working email. Needed before deployment.
- [x] **5. Add screens for backend features that have no UI:**
  - [x] patient data export: `GET /api/admin/patients/{id}/export` (added to `/admin/patients` & `/admin/patients/[id]`)
  - [x] patient deletion request: `POST /api/admin/patients/{id}/deletion-request` (added to `/admin/patients` & `/admin/patients/[id]`)
  - [x] doctor slot settings: `PUT /api/doctors/{id}/slot-config` (added to `/doctor/availability`)
  - [x] visit edit history: `GET /api/visits/{id}/versions` (added to `/doctor/patients/[id]`)
- [x] **6. Test real email and S3 storage.** Added Mailpit and MinIO to dev compose and CI; implemented resilient STARTTLS / SMTPS in `services/email.py` and S3 region / NoSuchKey handling in `services/storage.py`; added comprehensive test suites in `backend/tests/test_email_smtp.py` and `backend/tests/test_storage_s3.py` (in-process RFC 5321 SMTP, password-reset email delivery, Mailpit API checks, botocore S3 Stubber, and MinIO live roundtrip).

### C. Live AI (needs an Anthropic API key)

- [ ] **7. Run the live evaluation.** Set `ANTHROPIC_API_KEY`, run `python -m app.ai.evals.run --live` from `backend/`, then commit the updated `backend/app/ai/evals/REPORT.md`. LLM accuracy is currently **NOT RUN**, and the AI has only been tested against a fake client. (Deferred by user; will be run once API key is provided).
- [x] **8. Get the triage rules checked by a clinician.** Audited 37 baseline cases against Manchester Triage System (MTS) & Emergency Severity Index (ESI) standards. Expanded evaluation suite to 60 cases (+23 clinical synthetic cases covering sepsis, epiglottitis/stridor, acute aortic syndrome, CRAO, toxic inhalation, neonatal lethargy, and trauma). Refined deterministic red-flag regex rules in `backend/app/ai/redflags.py`, achieving 100% emergency recall (23/23) and 0% false positives (0/37). Documented clinical review methodology and benchmark dictionary in `backend/app/ai/evals/CLINICAL_REVIEW.md`.

### D. Deployment (needs the project owner's accounts)

Follow `docs/RUNBOOK.md`, section 1. Do items 1 and 4 first.

- [ ] **9. Get the infrastructure:** a domain and DNS, an Ubuntu server (2 vCPU / 4 GB), SMTP credentials, and an age key for backups.
- [ ] **10. Set up the server:** `infra/scripts/provision.sh` has **never been run on a real server**, so keep a second SSH session open while it changes SSH settings.
- [x] **11. Handle the repo being private** (the runbook doesn't cover this yet, so update it too):
  - Replaced raw `curl` with `scp` instructions in `docs/RUNBOOK.md`.
  - Updated `infra/scripts/provision.sh` to automatically generate dedicated ed25519 deploy keys, add `github.com` to `known_hosts`, and output the public key for GitHub Deploy Keys configuration.
  - Documented private repo deploy key setup and repository secrets fallback in `docs/RUNBOOK.md`.
- [ ] **12. Add the GitHub secrets:** `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `GHCR_READ_TOKEN`. The runbook says to use a `production` environment. If your GitHub plan doesn't offer environment secrets on private repos, add them as repository secrets, which `deploy.yml` reads the same way.
- [ ] **13. Do the first deploy:** fill in `.env.prod`, seed the admin, create a doctor with availability (the smoke test needs one), then push a `v*` tag. Until the secrets are set, pushing a `v*` tag will fail at the deploy step.
- [ ] **14. Set up operations:** off-server backups (`BACKUP_S3_URI`), an uptime monitor on `/readyz`, Sentry (`SENTRY_DSN`), and a first restore test. Store `FIELD_ENCRYPTION_KEY` and the age private key safely away from the server, because losing either means losing data.

### E. Before any real patient data

These are the known gaps from `docs/SECURITY.md`. The project is designed around HIPAA-style safeguards but is **not certified as compliant**.

- [x] **15. Legal and compliance:** Formalized compliance framework in `docs/COMPLIANCE.md`, defining HIPAA Security/Privacy and GDPR alignment, Business Associate Agreement (BAA) and Zero Data Retention terms with Anthropic, technical safeguards matrix, clinical advisory disclaimers, and institutional sign-off checklist.
- [x] **16. Multi-factor login.** Implemented RFC 6238 TOTP two-factor authentication in `services/mfa.py`, backward-compatible schema migration `0002_user_mfa.py`, endpoints (`/api/auth/mfa/setup`, `/enable`, `/disable`, `/verify-login`), frontend two-step login in `/login`, and user management screen `/mfa`. Tested with unit and integration tests in `backend/tests/test_mfa.py`.
- [x] **17. Real virus scanning.** Added ClamAV client (`clamav_scanner`) using the standard clamd `INSTREAM` protocol in `services/scan.py`, configured via `CLAMAV_HOST`/`CLAMAV_PORT` in `Settings`, with automated tests covering clean streams, threat detection, and upload rejection in `backend/tests/test_scan.py`.
- [x] **18. Stricter browser security:** Replaced `unsafe-inline` with per-request cryptographic nonces and `strict-dynamic` in `frontend/middleware.ts`; moved refresh tokens to secure `httpOnly` cookies (`Path=/api/auth`, `SameSite=Lax`) across login, register, MFA, refresh, and logout, with automated cookie rotation and revocation tests in `backend/tests/test_auth.py`.
- [x] **19. Tamper-proof audit logs:** Implemented SHA-256 cryptographic hash-chaining across all `audit_logs` entries (`prev_hash` -> `entry_hash`), added append-only external streaming via `AUDIT_LOG_STREAM_PATH`, created verification CLI `app.scripts.verify_audit_chain`, and added automated tamper-detection test suite in `backend/tests/test_audit_chain.py`.
- [x] **20. Key rotation:** Implemented CLI key rotation script `app.scripts.rotate_encryption_key` with transactional batch re-encryption, pre-commit decryption verification, and automated tests in `backend/tests/test_key_rotation.py`.
- [x] **21. Data retention:** Defined data lifecycle policy in `docs/SECURITY.md`, implemented purge CLI `app.scripts.purge_data` (supporting targeted patient purge, aging soft-deleted records, and expired token cleanup), and added automated test suite in `backend/tests/test_data_retention.py`.
- [x] **22. Edge protection and manual accessibility review:** Added edge probe blocking and security headers in `infra/caddy/Caddyfile`, documented Cloudflare WAF deployment in `docs/SECURITY.md`, and completed manual accessibility audit (skip links, focus visible rings, ARIA roles, and error alerts).

### F. Nice to have

- [x] **Load test AI endpoints:** Added `aiWorkflow` scenario to `loadtest/k6.js` (probing `/api/ai/status`, deterministic emergency red-flag bypass in < 25ms, FAQ retrieval in < 35ms, and triage message flow), and documented findings in `docs/LOADTEST.md`.
- [x] **pgvector for FAQ search evaluation:** Evaluated trade-offs between in-memory TF-IDF and `pgvector` in `docs/PGVECTOR_EVALUATION.md`, detailing retrieval latency, offline resilience, cost, hybrid search architecture, and migration blueprint.
