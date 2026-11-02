# Architecture

## System diagram
```mermaid
flowchart LR
  U[Browser: patient / staff / doctor / admin] -->|HTTPS| C[Caddy<br/>TLS + routing]
  C -->|/api, /healthz, /readyz| API[FastAPI x4 workers]
  C -->|everything else| FE[Next.js standalone]
  FE -. same origin API calls from the browser .-> C
  API --> DB[(PostgreSQL 16)]
  API --> R[(Redis<br/>rate-limit counters)]
  API --> ST[(Storage: local volume / S3)]
  API -->|timeouts, retries, circuit breaker| LLM[Anthropic API]
  W[Worker: APScheduler<br/>reminders] --> DB
  API --> KB[[knowledge_base/*.md]]
  B[Backup cron: pg_dump | age] --> DB
```

## Backend layout (`backend/app`)
- `api/` routers: `auth` (login, register, MFA, password reset/change), `admin` (users, departments, patient export/erasure), `analytics`, `patients`, `visits` (visits, prescriptions, version history), `documents`, `scheduling` (doctors, availability, slot-config, appointments, waitlist), `search`, `ai` (triage, booking assistant, FAQ, briefings), `health`.
- `core/`: config, DB sessions (dedicated connection pool for audit writes), security (argon2id, JWT), RBAC dependencies, tamper-proof audit log cryptographic hash chaining (`prev_hash` -> `entry_hash`), external JSONL streaming, rate limiting, field encryption.
- `services/`: access control (`access.py` centralized object-level authorization), scheduling engine, auth flows (cookie-based refresh token rotation), Multi-Factor Authentication (`mfa.py` RFC 6238 TOTP), storage (local / S3 with ServerSideEncryption AES256), virus-scanner (`scan.py` with ClamAV clamd daemon streaming protocol), notifications, versioning.
- `ai/`: `client.py` (LLM wrapper: timeout, retry/backoff, circuit breaker, usage logging), `prompts/*.vN.md` (versioned prompts), `redflags.py` (deterministic rule-based emergency detection), `triage.py`, `booking.py` (read-only tools + confirmation gate), `summarize.py`, `faq.py` (in-memory TF-IDF retrieval), `guards.py` (no diagnosis/medication filter), `pii.py`, `structured.py` (JSON + Pydantic validation), `evals/` (60 clinical test cases, report generator).
- `scripts/`: operational CLIs: `verify_audit_chain.py` (cryptographic audit verification), `rotate_encryption_key.py` (transactional field encryption re-keying), `purge_data.py` (data retention policy & permanent purge).
- `jobs/`: reminder job (24 h / 2 h, idempotent) and the APScheduler worker.

## Key design points
- **No double booking**: booking takes a row lock on the doctor, re-checks the generated slot, and the database enforces it with a GiST exclusion constraint on `(doctor_id, tstzrange(starts_at, ends_at))` for active appointments. Verified with 50 parallel requests for one slot (exactly one 201, forty-nine 409).
- **Idempotency**: `Idempotency-Key` header on booking, unique per user.
- **Least privilege & Access Control**: clinical data is limited to the patient and doctors with an appointment relationship; reception sees demographics/documents; admin sees analytics/audit but not clinical notes. DB runtime role has DML only.
- **Auditability & Tamper-Proofing**: every `/api` request is recorded with user, role, action, resource, status, IP, request id. Audit logs form a cryptographic SHA-256 hash chain and can stream to append-only storage for SIEM integration.
- **Multi-Factor Authentication (MFA)**: RFC 6238 TOTP supported for all roles, with signed login challenge tickets and replay prevention.
- **Browser Hardening**: Per-request cryptographic nonces in Content Security Policy (`strict-dynamic`); rotating refresh tokens stored in secure, `httpOnly`, `SameSite=Lax` cookies.
- **AI safety**: deterministic red-flag rules run before and independently of the model (100% emergency recall); output guard filters diagnoses/medication; PII minimised; booking proposals require explicit patient confirmation; resilient fallback modes when AI is unavailable.

## ER diagram
```mermaid
erDiagram
  roles ||--o{ users : has
  users ||--o| patients : "portal account"
  users ||--o| doctors : "is"
  departments ||--o{ doctors : contains
  doctors ||--o{ doctor_availability : weekly
  doctors ||--o{ availability_exceptions : leave
  patients ||--o{ appointments : books
  doctors ||--o{ appointments : serves
  patients ||--o{ waitlist_entries : waits
  doctors ||--o{ waitlist_entries : for
  patients ||--o{ visits : has
  doctors ||--o{ visits : conducts
  appointments ||--o| visits : produces
  visits ||--o{ prescriptions : has
  patients ||--o{ documents : owns
  patients ||--o{ ai_summaries : has
  users ||--o{ ai_conversations : starts
  ai_conversations ||--o{ ai_messages : contains
  patients ||--o{ notifications : receives
  users ||--o{ audit_logs : generates
  users ||--o{ refresh_tokens : holds
  users ||--o{ password_reset_tokens : requests
  visits ||--o{ record_versions : "snapshots (entity_type/id)"
```
Key constraints: GiST exclusion `ex_appointments_no_overlap` (no overlapping booked/completed appointments per doctor);
`visits.search_vector` generated `tsvector` with GIN index; `deleted_at` on clinical tables; `record_versions` snapshots every edit;
unique partial index on `(created_by, idempotency_key)`. FHIR mapping later: `patients` -> Patient, `visits` -> Encounter, `prescriptions` -> MedicationRequest, `documents` -> DocumentReference, `appointments` -> Appointment; IDs are UUIDs to make that mapping stable.
