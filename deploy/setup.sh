#!/usr/bin/env bash
# ============================================================
# Helm Marine — EC2 single-server setup (Ubuntu 22.04 / 24.04)
# Run once on a fresh EC2 instance:
#   curl -sSL <raw-url> | sudo bash
#   — or —
#   sudo bash deploy/setup.sh
# ============================================================
set -euo pipefail

echo "=== Helm Marine — EC2 Setup ==="

# ---------- system packages ----------
apt-get update -y
apt-get install -y \
  apt-transport-https ca-certificates curl gnupg lsb-release \
  git unzip fail2ban ufw

# ---------- Docker ----------
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# ---------- Docker Compose (plugin) ----------
if ! docker compose version &>/dev/null; then
  echo "Installing Docker Compose plugin..."
  apt-get install -y docker-compose-plugin
fi

# ---------- Firewall (ufw) ----------
echo "Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable

# ---------- Swap (useful on small instances) ----------
if [ ! -f /swapfile ]; then
  echo "Creating 2GB swap..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------- App directory ----------
APP_DIR=/opt/helm-marine
mkdir -p "$APP_DIR"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. cd $APP_DIR"
echo "  2. git clone <your-repo-url> ."
echo "  3. cp .env.example .env.prod  (then fill in secrets)"
echo "  4. bash deploy/deploy.sh"
echo ""
