#!/usr/bin/env bash
# One-time hardening + Docker setup for a fresh Ubuntu 22.04/24.04 VPS. Run as root:  sudo ./provision.sh
# NOTE: written from the runbook and reviewed, but not executed against a real VM in this repository's CI.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
DEPLOY_USER=${DEPLOY_USER:-deploy}

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl ufw fail2ban unattended-upgrades age logrotate git

# Docker Engine + compose plugin (official convenience script)
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

# Non-root deploy user (docker group) with the SSH key that GitHub Actions uses
id "$DEPLOY_USER" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
touch "/home/$DEPLOY_USER/.ssh/authorized_keys" && chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/hospital /var/backups/hospital

# GitHub deploy key for cloning and fetching private repository
DEPLOY_KEY="/home/$DEPLOY_USER/.ssh/id_ed25519"
if [ ! -f "$DEPLOY_KEY" ]; then
    su - "$DEPLOY_USER" -c "ssh-keygen -t ed25519 -N '' -C 'deploy-key@hospital' -f '$DEPLOY_KEY'"
fi
# Add github.com to known_hosts so git fetch in CI will not prompt interactively
su - "$DEPLOY_USER" -c "ssh-keyscan -t ed25519,rsa github.com >> /home/$DEPLOY_USER/.ssh/known_hosts 2>/dev/null || true"
chmod 600 "/home/$DEPLOY_USER/.ssh/known_hosts" 2>/dev/null || true
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/known_hosts" 2>/dev/null || true

# Firewall: only SSH, HTTP (ACME + redirect) and HTTPS
ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable

# SSH hardening: keys only, no root login (support modern drop-in configs and legacy sshd_config)
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-hospital-hardening.conf <<'CONF'
PasswordAuthentication no
PermitRootLogin no
CONF
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd

systemctl enable --now fail2ban unattended-upgrades

# Docker log rotation defaults (compose also sets per-service limits)
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
JSON
systemctl restart docker

# Daily encrypted backup at 02:17 UTC + rotation of its log
cat > /etc/cron.d/hospital-backup <<CRON
17 2 * * * $DEPLOY_USER /opt/hospital/infra/scripts/backup.sh >> /var/log/hospital-backup.log 2>&1
CRON
cat > /etc/logrotate.d/hospital-backup <<'LR'
/var/log/hospital-backup.log { weekly rotate 8 compress missingok notifempty }
LR
touch /var/log/hospital-backup.log && chown "$DEPLOY_USER" /var/log/hospital-backup.log

echo ""
echo "=== Provisioning Complete ==="
echo "1. Dedicated GitHub Deploy Key for private repository:"
echo "--------------------------------------------------------"
cat "${DEPLOY_KEY}.pub"
echo "--------------------------------------------------------"
echo "Add the key above in: GitHub -> Repository -> Settings -> Deploy Keys (Read-only)."
echo ""
echo "2. CI deployment authorization:"
echo "Add your CI deployment public key to: /home/$DEPLOY_USER/.ssh/authorized_keys"
echo ""
echo "3. Clone repository:"
echo "sudo -u $DEPLOY_USER git clone git@github.com:<owner>/<repo>.git /opt/hospital"
echo ""
echo "4. Environment configuration:"
echo "Create /opt/hospital/.env.prod (chmod 600) from .env.prod.example, point DNS A/AAAA records at this host, then deploy."
