#!/usr/bin/env bash
# =============================================================================
# Helm — one-time host preparation (Ubuntu 22.04/24.04, e.g. a single EC2 instance)
#
#   sudo bash deploy/setup.sh [--app-dir /opt/helm-marine] [--deploy-user ubuntu]
#
# Idempotent: safe to run again. Installs Docker Engine + compose plugin, curl, git,
# python3, certbot, fail2ban and ufw; opens only 22/80/443; adds swap on small hosts;
# creates the application, backup and certificate directories. It does NOT clone the
# repository, create .env.prod, obtain certificates or deploy — see the runbook.
# =============================================================================
set -euo pipefail

APP_DIR=/opt/helm-marine
DEPLOY_USER="${SUDO_USER:-ubuntu}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir) APP_DIR="${2:?}"; shift 2 ;;
    --deploy-user) DEPLOY_USER="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "deploy user '$DEPLOY_USER' does not exist" >&2; exit 1; }

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl gnupg git python3 \
  fail2ban ufw certbot

echo "== docker"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
fi
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker "$DEPLOY_USER"
# Bounded container logs host-wide (compose files also set per-service limits).
if [ ! -f /etc/docker/daemon.json ]; then
  printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "20m", "max-file": "5"},\n  "live-restore": true\n}\n' \
    > /etc/docker/daemon.json
  systemctl restart docker
fi

echo "== firewall (22, 80, 443 only)"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

echo "== swap (only when the host has < 4 GiB RAM and no swap)"
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "$mem_kb" -lt 4194304 ] && ! swapon --show | grep -q .; then
  [ -f /swapfile ] || { fallocate -l 2G /swapfile; chmod 600 /swapfile; mkswap /swapfile; }
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== directories"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0750 "$APP_DIR"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 /var/backups/helm

cat <<EOF

Host prepared. Next (as $DEPLOY_USER, after logging in again for the docker group):
  1. git clone <repository> $APP_DIR && cd $APP_DIR && git checkout <release ref>
  2. cp .env.prod.example .env.prod && chmod 600 .env.prod   # fill in real values
  3. obtain TLS certificates (docs/08_delivery/Operations_Runbook.md, "HTTPS")
  4. deploy/deploy.sh
EOF
