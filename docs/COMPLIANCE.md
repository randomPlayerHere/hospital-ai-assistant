# Legal, Regulatory & Compliance Framework (HIPAA / GDPR)

*Document Version: 1.0*  
*Last Updated: 2026-11-02*

---

## 1. Compliance Scope & Status

The Hospital AI Assistant is engineered with technical, physical, and administrative safeguards aligned with the **Health Insurance Portability and Accountability Act (HIPAA) Security and Privacy Rules** (45 CFR Part 160 and Part 164, Subparts A, C, and E) and the **General Data Protection Regulation (GDPR)**.

> [!IMPORTANT]
> Software architecture alone cannot grant legal compliance certification. Full regulatory compliance requires that the covered entity (the hospital, clinic, or healthcare provider organisation):
> 1. Formally executes a **Business Associate Agreement (BAA)** or **Data Processing Agreement (DPA)** with all third-party vendors processing Protected Health Information (PHI) — specifically Anthropic, cloud hosting providers, and email relays.
> 2. Adopts written operational policies covering employee access, training, and workstation security.
> 3. Periodically conducts and signs off on an institutional Risk Assessment.

---

## 2. Third-Party LLM Processing (Anthropic BAA & Zero-Retention)

### 2.1 The PHI Challenge in AI Triage
The AI triage and summarisation workflows receive unstructured symptom text, patient age, and clinical notes. Although `backend/app/ai/pii.py` performs deterministic de-identification (scrubbing emails, phone numbers, postal codes, and specific identifiers before LLM prompts), clinical descriptions may still inherently constitute PHI under HIPAA 45 CFR § 160.103.

### 2.2 Anthropic BAA Requirements
1. **Commercial Tier Requirement:** Anthropic enters into Business Associate Agreements (BAAs) with eligible commercial enterprise customers. The project owner MUST execute Anthropic's standard BAA prior to routing live patient interactions through the API.
2. **Zero Data Retention (ZDR):** Under the BAA, Anthropic acts as a HIPAA Business Associate. Ensure the organisation account is enrolled in Anthropic's Commercial Terms where:
   - Prompts and completions are **never used to train** future foundational models.
   - Prompts are processed ephemerally in volatile memory and are not persisted in server logs beyond transient routing requirements.
3. **Regional Hosting / Data Sovereignty:** Verify that API traffic terminates within required legal jurisdictions (e.g., US-based data centers for US HIPAA entities, EU data regions for GDPR).

---

## 3. HIPAA Safeguards Matrix

| HIPAA Security Rule Citation | Safeguard Specification | Implementation in Hospital AI Assistant |
|---|---|---|
| **§ 164.312(a)(1)** | **Access Control:** Unique user identification, emergency access, automatic logoff. | Role-Based Access Control (RBAC) enforced on every route (`access.py`). 15-minute access token lifespan, automatic token revocation on logout/deactivation. |
| **§ 164.312(a)(2)(iv)** | **Multi-Factor Authentication (MFA):** Identity verification for remote/portal access. | RFC 6238 TOTP two-factor authentication for user and staff logins (`app/services/mfa.py`, `/api/auth/mfa/*`). |
| **§ 164.312(a)(2)(iv)** | **Encryption at Rest:** Standard cryptography for stored PHI. | AES-256 Fernet field encryption for patient insurance IDs (`FIELD_ENCRYPTION_KEY`). Transactional rotation CLI (`rotate_encryption_key.py`). S3 Server-Side Encryption (`AES256`). Database disk encryption. |
| **§ 164.312(e)(1)** | **Transmission Security:** End-to-end encryption in transit. | Strict TLS 1.3 termination via Caddy reverse proxy. Strict-Transport-Security (HSTS), Content Security Policy with per-request nonces (`strict-dynamic`), and httpOnly/SameSite cookies. |
| **§ 164.312(b)** | **Audit Controls:** Mechanism to record and examine system activity in PHI-containing components. | Tamper-proof cryptographic SHA-256 hash chaining on all `audit_logs` entries (`prev_hash` → `entry_hash`). Independent verification utility (`verify_audit_chain.py`). Optional external append-only JSONL streaming for SIEM ingestion (`AUDIT_LOG_STREAM_PATH`). |
| **§ 164.312(c)(1)** | **Data Integrity:** Protection against improper alteration or destruction of PHI. | Soft-deletion architecture (`deleted_at`), versioned visit note editing (`visit_versions`), automated data retention purge utility (`purge_data.py`). |
| **§ 164.308(a)(7)** | **Contingency Plan:** Data backup and disaster recovery. | Daily automated encrypted backups (`infra/scripts/backup.sh`) using `age` public-key encryption; automated restore verification suite (`infra/scripts/restore-test.sh`). |
| **§ 164.308(a)(1)(ii)(A)** | **Risk Analysis & Malicious Software Protection:** | Anti-malware scanning pipeline via ClamAV clamd daemon streaming protocol (`INSTREAM`) on all uploaded documents (`services/scan.py`). |

---

## 4. Patient Consent & Clinical Disclaimer Architecture

To satisfy regulatory transparency guidelines (FDA guidance on Clinical Decision Support software and FTC AI guidelines):

1. **Explicit Advisory Nature:**
   - Every AI-generated output is programmatically flagged as advisory and contains the mandatory clinical disclaimer:
     > *"This summary and triage classification is generated by an artificial intelligence assistant for administrative and triaging assistance only. It does not constitute a medical diagnosis, clinical evaluation, or prescription."*
2. **Rule-Based Emergency Pre-empt:**
   - Emergent red flags (cardiac arrest, stroke, severe hemorrhage, respiratory compromise, anaphylaxis, sepsis) run on deterministic regex rules before the LLM. In an emergency, the AI conversational workflow is halted immediately, and the emergency banner directing the user to 911 / emergency services is displayed.
3. **No Autonomous Prescribing or Alteration:**
   - The AI client has **zero write permissions** to prescription or diagnosis tables. All prescription entries and clinical notes require explicit, authenticated physician authorship.
4. **Patient Booking Confirmation Gate:**
   - The booking assistant cannot autonomously book, reschedule, or cancel appointments. It generates proposals which require an explicit, user-initiated `POST /api/appointments` confirmation.

---

## 5. Organizational Action Items Prior to Live Patient Data

Before toggling production traffic with real patient records:
- [ ] Sign formal BAA with Anthropic (via Anthropic Sales / Console).
- [ ] Sign formal BAA / DPA with transactional email provider (SendGrid / AWS SES / Mailgun).
- [ ] Sign BAA with cloud infrastructure provider (AWS / Google Cloud / Azure / Ubuntu host).
- [ ] Verify `FIELD_ENCRYPTION_KEY` and the `age` backup private key are securely vaulted in an institutional key management system (e.g. AWS KMS, HashiCorp Vault), strictly isolated from the application server.
- [ ] Schedule quarterly audit log verification using `python -m app.scripts.verify_audit_chain`.
- [ ] Complete workforce training on role-based access and workstation security.
