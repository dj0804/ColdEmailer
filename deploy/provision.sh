#!/usr/bin/env bash
# One-time provisioning for a fresh Ubuntu 22.04 Lightsail box (512MB).
# Run ON the server:  bash provision.sh
set -euo pipefail

APP_DIR=/home/ubuntu/applier

echo "==> System packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip rsync

# 512MB has no swap by default; pip installs and the Python heap will OOM
# without it. 1GB swapfile is the difference between this box working and not.
if [ ! -f /swapfile ]; then
  echo "==> Creating 1GB swapfile"
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Python venv"
mkdir -p "$APP_DIR"
cd "$APP_DIR/backend"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

echo "==> systemd service"
sudo cp "$APP_DIR/deploy/applier.service" /etc/systemd/system/applier.service
sudo systemctl daemon-reload
sudo systemctl enable applier
sudo systemctl restart applier

echo "==> cloudflared"
if ! command -v cloudflared >/dev/null; then
  ARCH=$(dpkg --print-architecture)
  curl -sSL -o /tmp/cloudflared.deb \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  sudo dpkg -i /tmp/cloudflared.deb
fi

echo
echo "Provisioning done. Service status:"
sudo systemctl --no-pager --lines=5 status applier || true
echo
echo "Next: authenticate the tunnel (see deploy/README.md)"
