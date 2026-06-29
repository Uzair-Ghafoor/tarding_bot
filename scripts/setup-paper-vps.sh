#!/usr/bin/env bash
# One-shot setup on Ubuntu 22.04 (Oracle Cloud Always Free ARM)
# Run ON THE VPS after: git clone YOUR_REPO ~/scalpbot
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== ScalpBot paper VPS setup ==="

if ! command -v python3 >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y python3 python3-venv python3-pip rsync git
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-paper.txt

mkdir -p logs data
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — edit if needed: nano .env"
fi

# systemd units
USER_NAME="$(whoami)"
sed "s|User=ubuntu|User=$USER_NAME|g; s|/home/ubuntu/scalpbot|$ROOT|g" \
  scripts/scalpbot-paper.service | sudo tee /etc/systemd/system/scalpbot-paper.service >/dev/null
sed "s|User=ubuntu|User=$USER_NAME|g; s|/home/ubuntu/scalpbot|$ROOT|g" \
  scripts/scalpbot-dashboard.service | sudo tee /etc/systemd/system/scalpbot-dashboard.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable scalpbot-paper scalpbot-dashboard
sudo systemctl restart scalpbot-paper scalpbot-dashboard

# Log bundle every 6 hours
(crontab -l 2>/dev/null | grep -v bundle-logs.sh; echo "0 */6 * * * $ROOT/scripts/bundle-logs.sh") | crontab -

chmod +x scripts/*.sh scripts/paper-status.py

PUBLIC_IP="$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo ""
echo "=== Done ==="
echo "  Bot:       sudo systemctl status scalpbot-paper"
echo "  Dashboard: http://$PUBLIC_IP:8501  (open port 8501 in cloud firewall)"
echo "  Logs:      tail -f $ROOT/logs/autopilot.log"
echo ""
echo "On your Mac, add to .env:"
echo "  PAPER_HOST=$USER_NAME@$PUBLIC_IP"
echo "Then: npm run pull-logs"
