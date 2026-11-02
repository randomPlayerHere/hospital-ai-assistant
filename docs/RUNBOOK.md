# Runbook

Audience: the person operating the deployed system. Commands run on the server in `/opt/hospital/infra` unless stated.

## 0. Architecture in one paragraph
Caddy (80/443, automatic Let's Encrypt certificates) routes `/api/*`, `/healthz`, `/readyz` to the FastAPI backend and everything else to the Next.js frontend. The backend talks to Postgres 16 (and Redis for shared rate-limit counters). A separate `worker` container runs APScheduler (appointment reminders). Only Caddy publishes ports.

## 1. First-time setup (new server)
1. Create a VM (Ubuntu 22.04/24.04, 2 vCPU / 4 GB is enough for a small clinic) and point DNS `A`/`AAAA` for your domain at it.
2. Copy `infra/scripts/provision.sh` to the server and run as root:
   ```bash
   scp infra/scripts/provision.sh root@<server-ip>:/tmp/provision.sh
   ssh root@<server-ip> "bash /tmp/provision.sh && rm /tmp/provision.sh"
   ```
   *(Note: because the repository is private, raw `curl` commands cannot fetch it without auth).*
   The script installs Docker, sets up firewall rules (22/80/443), fail2ban, unattended upgrades, key-only SSH, log rotation, and the 02:17 UTC backup cron. **Keep a second SSH session open while it changes sshd.**
3. **Configure private repository access and CI keys:**
   - **GitHub Deploy Key (read-only):** The provision script automatically generates a dedicated ed25519 deploy key in `/home/deploy/.ssh/id_ed25519.pub` and pre-populates `github.com` in `known_hosts`. Copy this public key and paste it into **GitHub → Repo → Settings → Deploy Keys** (leave *Allow write access* unchecked).
   - **CI Deployment Access:** Generate an SSH keypair on your local machine for GitHub Actions (or use an existing deployment key). Append the public key to `/home/deploy/.ssh/authorized_keys` on the server.
   - **Initial clone:** As the `deploy` user, clone the repo into `/opt/hospital`:
     ```bash
     sudo -u deploy git clone git@github.com:<owner>/<repo>.git /opt/hospital
     ```
4. `cp .env.prod.example .env.prod && chmod 600 .env.prod` in `/opt/hospital` and fill it in: `DOMAIN`, `ACME_EMAIL`, `GHCR_OWNER`, strong random `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` (`python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`), DB passwords (and the two DB URLs), `ANTHROPIC_API_KEY`, SMTP settings (`EMAIL_BACKEND=smtp`), `ADMIN_EMAIL`/`ADMIN_PASSWORD`, `BACKUP_AGE_RECIPIENT`.
   - **Back up `FIELD_ENCRYPTION_KEY` and the age private key somewhere safe and separate from the server.** Losing either means unrecoverable data / backups.
5. GitHub repo settings → Secrets (environment `production` or Repository Secrets): `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (private key matching `authorized_keys`), `GHCR_READ_TOKEN` (PAT with `read:packages`).
6. Seed the first admin and reference data (no demo data in prod because `ENVIRONMENT=prod`):
   ```bash
   IMAGE_TAG=<tag> docker compose -f docker-compose.prod.yml --env-file ../.env.prod run --rm backend python -m app.seed
   ```
   then log in and **change the admin password immediately** (`/change-password`). Create doctors (Admin → Users, role Doctor) and have them set their weekly availability (Doctor → Availability & leave).
7. Deploy (section 2). The smoke test needs at least one doctor with availability.

## 2. Deploy
Automatic: pushing a `v*` tag (or running the *Deploy* workflow) builds and pushes images to GHCR, SSHes to the server and runs `scripts/deploy.sh <tag>`.

Manually: `./scripts/deploy.sh v1.2.3`. The script: pulls images → starts db/redis → **runs Alembic migrations** (`migrate` service, schema-owner DB role) → restarts backend/worker/frontend → waits for health → runs `scripts/smoke.sh` (register → login → book → cancel → AI triage → admin dashboard) → records the tag in `.deployed_tag`.
Caddy retries upstreams for up to 15 s, so a rolling restart is normally invisible to users (low downtime, not zero).

**Migration rule**: migrations must be backward compatible with the previous release (expand → deploy → contract in a later release), because rollback re-deploys the previous *images* and does not reverse the schema.

## 3. Rollback
- Automatic: if health or the smoke test fails, `deploy.sh` redeploys the previously recorded tag and exits non-zero (the workflow fails).
- Manual: `./scripts/deploy.sh <previous-tag>`.
- Schema rollback (rare): restore the pre-deploy backup (section 4) into a new database and repoint; do not downgrade Alembic on live data.
- Rehearsed locally (see section 8): a deliberately broken release failed the smoke test and the previous release was restored automatically.

## 4. Backups and restore
- Daily 02:17 UTC: `scripts/backup.sh` → `pg_dump -Fc | age -r $BACKUP_AGE_RECIPIENT` → `/var/backups/hospital/hospital-<UTC>.dump.age` (+ `.sha256`), keeps `BACKUP_KEEP_DAYS` (14). Plaintext never touches disk. Set `BACKUP_S3_URI` (needs `aws` CLI) to copy off-host. **Off-host copies are essential: a backup on the same disk is not a backup.**
- Uploaded documents live in the `uploads` Docker volume (or your S3 bucket if `STORAGE_BACKEND=s3`) and are **not** in the DB dump: back that volume up too (`docker run --rm -v hospital-ai_uploads:/d -v /var/backups/hospital:/b alpine tar czf /b/uploads-$(date +%F).tgz -C /d .`) or use bucket versioning.
- Test the restore at least monthly (it never touches the live DB):
  `AGE_IDENTITY=/secure/age-key.txt ./scripts/restore-test.sh /var/backups/hospital/hospital-XXXX.dump.age` → prints `restore ok: users=.. patients=.. alembic=..`.
- Real restore (disaster): provision a server, deploy, stop the app (`docker compose ... stop backend worker`), `age -d -i key.txt file.dump.age | docker compose ... exec -T db pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists --no-owner`, restore the uploads volume, start the app, run the smoke test.

## 5. Monitoring and logs
- Uptime: point an external monitor (UptimeRobot, Better Stack, Uptime Kuma) at `https://<domain>/readyz` (checks DB) with alerts to on-call.
- Errors: set `SENTRY_DSN` (backend). Never enable request-body capture: payloads contain PHI.
- Logs: `docker compose -f docker-compose.prod.yml logs -f backend` (JSON lines with `request_id`; rotated at 10 MB × 5). Caddy access log: `caddy` container `/data/access.log` (rolled).
- AI health: Admin → Dashboard shows AI usage, degraded (AI-down) responses and latency.
- Certificates renew automatically (Caddy). If issuance fails, check DNS and that ports 80/443 are reachable: `docker compose logs caddy`.

## 6. Incident checklists
**Site down / 502**: `docker compose ps` → look for unhealthy containers → `logs backend` → `readyz` says DB down? check `db` health and disk space (`df -h`). Roll back if the last deploy is the trigger.
**Database disk full**: prune old backups/logs, `docker system prune` (never `--volumes`), resize disk, then investigate the growth (`audit_logs` is the usual suspect: archive rows older than your retention period).
**AI provider outage**: no action required. Triage falls back to rule-based red flags plus a "book directly" message, FAQ returns document excerpts, briefings return a structured overview, the booking assistant returns 503 and points users to manual booking. The circuit breaker re-tests after 60 s.
**Suspected credential compromise**: rotate `SECRET_KEY` (logs everyone out), disable the user (Admin → Users), review `Audit logs` filtered by that user/IP, rotate DB passwords, and follow your breach-notification policy (HIPAA/GDPR timelines start at discovery).
**Suspected PHI exposure**: preserve logs, restrict access, export the relevant audit log range, involve your privacy officer.
**Locked-out admin**: `docker compose run --rm backend python -c "..."` to reset the hash, or run the seed with a new `ADMIN_PASSWORD` for a *new* admin email and disable the old one.
**Reminders not sending**: `docker compose logs worker`; the job is idempotent (dedupe keys in `notifications`), so restarting the worker never double-sends.

## 7. Routine maintenance
- **Weekly**: Check backups exist off-host (`BACKUP_S3_URI`) and disk has space (`df -h`). Run token purge:
  ```bash
  docker compose -f docker-compose.prod.yml --env-file ../.env.prod run --rm backend python -m app.scripts.purge_data --purge-expired-tokens
  ```
- **Monthly**: Run backup restore test (`restore-test.sh`). Check `pip-audit` and `npm audit`. Run cryptographic audit chain verification:
  ```bash
  docker compose -f docker-compose.prod.yml --env-file ../.env.prod run --rm backend python -m app.scripts.verify_audit_chain
  ```
- **Quarterly**: Review administrative accounts and MFA enrollments. Review audit logs for anomalous cross-patient queries.
- **Key Rotation**: When rotating `FIELD_ENCRYPTION_KEY`, run transactional re-encryption:
  ```bash
  docker compose -f docker-compose.prod.yml --env-file ../.env.prod run --rm backend python -m app.scripts.rotate_encryption_key --old-key <old> --new-key <new>
  ```
- **Permanent Purge**: Execute statutory clinical data retention purge on aged soft-deleted patient records (e.g. older than 30 days post-erasure):
  ```bash
  docker compose -f docker-compose.prod.yml --env-file ../.env.prod run --rm backend python -m app.scripts.purge_data --purge-soft-deleted-older-than-days 30
  ```

## 8. Rehearse locally (what was verified)
`infra/docker-compose.rehearsal.yml` runs the *production* compose file on unprivileged ports with Caddy's internal CA:
```bash
docker build -t ghcr.io/local/hospital-ai-backend:test backend
docker build --build-arg NEXT_PUBLIC_API_URL= -t ghcr.io/local/hospital-ai-frontend:test frontend
cp .env.prod.example .env.prod   # DOMAIN=localhost, GHCR_OWNER=local, EMAIL_BACKEND=console, generated secrets
export COMPOSE_PROJECT_NAME=hospital-prod GHCR_OWNER=local COMPOSE_EXTRA="-f docker-compose.rehearsal.yml" \
       SKIP_PULL=1 SMOKE_BASE_URL=https://localhost:8443 CURL_OPTS=-k
cd infra && ./scripts/deploy.sh test          # add a demo seed first: run backend `python -m app.seed` with ENVIRONMENT=dev
```
Results recorded when this was written: migrations applied, HTTPS via Caddy, same-origin routing, smoke test passed; a broken image tag was rolled back automatically; an age-encrypted backup restored into a scratch database (12 users, 4 patients, alembic `0001`) and a wrong key was rejected.
