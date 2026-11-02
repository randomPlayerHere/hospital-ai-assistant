# API reference

Generated from the OpenAPI schema (`make api-docs`). Interactive docs: `/docs` (Swagger UI) on the API host.

## Conventions
- Auth: `Authorization: Bearer <access token>` from `POST /api/auth/login` (15 min); renew with `POST /api/auth/refresh` (rotating refresh tokens).
- Roles: `admin`, `doctor`, `staff` (reception), `patient`. Every endpoint enforces its roles server-side; unauthorised object access returns `404`.
- Errors: `{"detail": "..."}` (validation errors: list of `{loc, msg, type}`); every response carries `X-Request-ID`.
- Booking: send an `Idempotency-Key` header on `POST /api/appointments`; a repeated key returns the original booking (`200` instead of `201`).
- Timestamps are UTC ISO 8601; appointment slots are generated in the hospital timezone.
- AI endpoints return `disclaimer`, `ai_generated` and `requires_clinician_review`; when the AI service is down triage/FAQ/briefings degrade gracefully and the booking assistant returns `503`.

## admin

| Method | Path | Summary | Auth |
|---|---|---|---|
| GET | `/api/admin/analytics/export.csv` | Analytics Export | bearer |
| GET | `/api/admin/analytics/summary` | Analytics Summary | bearer |
| GET | `/api/admin/audit-logs` | Audit Logs | bearer |
| POST | `/api/admin/departments` | Create Department | bearer |
| PUT | `/api/admin/departments/{department_id}` | Update Department | bearer |
| POST | `/api/admin/patients/{patient_id}/deletion-request` | Deletion Request | bearer |
| GET | `/api/admin/patients/{patient_id}/export` | Export Patient | bearer |
| GET | `/api/admin/users` | List Users | bearer |
| POST | `/api/admin/users` | Create User | bearer |
| PATCH | `/api/admin/users/{user_id}/active` | Set Active | bearer |

## ai

| Method | Path | Summary | Auth |
|---|---|---|---|
| POST | `/api/ai/booking/confirm` | Booking Confirm | bearer |
| POST | `/api/ai/booking/message` | Booking Message | bearer |
| POST | `/api/ai/faq` | Faq Ask | bearer |
| POST | `/api/ai/patients/{patient_id}/briefing` | Patient Briefing | bearer |
| GET | `/api/ai/patients/{patient_id}/summaries` | List Summaries | bearer |
| GET | `/api/ai/status` | Ai Status | bearer |
| POST | `/api/ai/triage/message` | Triage Message | bearer |
| POST | `/api/ai/visits/{visit_id}/summary` | Visit Summary | bearer |

## auth

| Method | Path | Summary | Auth |
|---|---|---|---|
| POST | `/api/auth/forgot-password` | Forgot Password | public |
| POST | `/api/auth/login` | Login | public |
| POST | `/api/auth/logout` | Logout | public |
| GET | `/api/auth/me` | Me | bearer |
| POST | `/api/auth/refresh` | Refresh | public |
| POST | `/api/auth/register` | Register | public |
| POST | `/api/auth/change-password` | Change Password | bearer |
| POST | `/api/auth/reset-password` | Reset Password | public |

## documents

| Method | Path | Summary | Auth |
|---|---|---|---|
| GET | `/api/documents/download` | Download | public |
| DELETE | `/api/documents/{doc_id}` | Delete Document | bearer |
| GET | `/api/documents/{doc_id}/link` | Signed Link | bearer |
| POST | `/api/patients/{patient_id}/documents` | Upload Document | bearer |
| GET | `/api/patients/{patient_id}/documents` | List Documents | bearer |

## ops

| Method | Path | Summary | Auth |
|---|---|---|---|
| GET | `/healthz` | Healthz | public |
| GET | `/readyz` | Readyz | public |

## patients

| Method | Path | Summary | Auth |
|---|---|---|---|
| POST | `/api/patients` | Create Patient | bearer |
| GET | `/api/patients` | List Patients | bearer |
| GET | `/api/patients/me` | My Profile | bearer |
| GET | `/api/patients/{patient_id}` | Get Patient | bearer |
| PATCH | `/api/patients/{patient_id}` | Update Patient | bearer |
| DELETE | `/api/patients/{patient_id}` | Delete Patient | bearer |
| GET | `/api/patients/{patient_id}/timeline` | Timeline | bearer |

## records

| Method | Path | Summary | Auth |
|---|---|---|---|
| POST | `/api/patients/{patient_id}/visits` | Create Visit | bearer |
| GET | `/api/patients/{patient_id}/visits` | List Visits | bearer |
| PATCH | `/api/prescriptions/{rx_id}` | Update Prescription | bearer |
| DELETE | `/api/prescriptions/{rx_id}` | Delete Prescription | bearer |
| GET | `/api/visits/{visit_id}` | Get Visit | bearer |
| PATCH | `/api/visits/{visit_id}` | Update Visit | bearer |
| DELETE | `/api/visits/{visit_id}` | Delete Visit | bearer |
| POST | `/api/visits/{visit_id}/prescriptions` | Add Prescription | bearer |
| GET | `/api/visits/{visit_id}/versions` | Visit Versions | bearer |

## scheduling

| Method | Path | Summary | Auth |
|---|---|---|---|
| POST | `/api/appointments` | Book Appointment | bearer |
| GET | `/api/appointments` | List Appointments | bearer |
| POST | `/api/appointments/{appt_id}/cancel` | Cancel Appointment | bearer |
| POST | `/api/appointments/{appt_id}/complete` | Complete Appointment | bearer |
| POST | `/api/appointments/{appt_id}/no-show` | No Show Appointment | bearer |
| POST | `/api/appointments/{appt_id}/reschedule` | Reschedule Appointment | bearer |
| GET | `/api/departments` | Departments | bearer |
| GET | `/api/doctors` | Doctors | bearer |
| GET | `/api/doctors/me` | My Doctor Profile | bearer |
| GET | `/api/doctors/{doctor_id}/availability` | Get Availability | bearer |
| PUT | `/api/doctors/{doctor_id}/availability` | Set Availability | bearer |
| GET | `/api/doctors/{doctor_id}/exceptions` | List Exceptions | bearer |
| POST | `/api/doctors/{doctor_id}/exceptions` | Add Exception | bearer |
| DELETE | `/api/doctors/{doctor_id}/exceptions/{exc_id}` | Delete Exception | bearer |
| PUT | `/api/doctors/{doctor_id}/slot-config` | Set Slot Config | bearer |
| GET | `/api/doctors/{doctor_id}/slots` | Slots | bearer |
| GET | `/api/waitlist` | List Waitlist | bearer |
| POST | `/api/waitlist` | Join Waitlist | bearer |
| DELETE | `/api/waitlist/{entry_id}` | Leave Waitlist | bearer |

## search

| Method | Path | Summary | Auth |
|---|---|---|---|
| GET | `/api/search/records` | Search Records | bearer |
