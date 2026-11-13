#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/netscope-pro"
SERVICE_USER="netscope"
SERVICE_FILE="/etc/systemd/system/netscope-pro.service"
PORT="${NETSCOPE_PORT:-8080}"
HOST="${NETSCOPE_HOST:-0.0.0.0}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo: sudo bash install.sh" >&2
  exit 1
fi
if [[ ! -f "$SOURCE_DIR/app.py" || ! -f "$SOURCE_DIR/requirements.txt" ]]; then
  echo "Run install.sh from the NetScope repository directory." >&2
  exit 1
fi
if [[ -r /etc/os-release ]]; then . /etc/os-release; else echo "Cannot detect Linux distribution."; exit 1; fi
case "${ID:-}" in
  debian|ubuntu) ;;
  *) echo "This installer supports Debian and Ubuntu. Detected: ${PRETTY_NAME:-unknown}"; exit 1 ;;
esac

echo "[1/6] Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-venv python3-pip ca-certificates

echo "[2/6] Creating service account..."
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "[3/6] Installing NetScope files..."
install -d -o root -g "$SERVICE_USER" -m 0750 "$APP_DIR"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/app.py" "$APP_DIR/app.py"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/requirements.txt" "$APP_DIR/requirements.txt"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[4/6] Creating systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=NetScope Pro monitoring dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=NETSCOPE_HOST=$HOST
Environment=NETSCOPE_PORT=$PORT
ExecStart=$APP_DIR/venv/bin/gunicorn --workers 2 --bind $HOST:$PORT app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

echo "[5/6] Enabling and starting NetScope..."
systemctl daemon-reload
systemctl enable --now netscope-pro.service

echo "[6/6] Checking service..."
if ! systemctl is-active --quiet netscope-pro.service; then
  systemctl --no-pager --full status netscope-pro.service || true
  echo "NetScope did not start. Check: journalctl -u netscope-pro -n 80" >&2
  exit 1
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "NetScope Pro installed successfully."
echo "Dashboard: http://${IP:-VM-IP}:$PORT"
echo "Service:   systemctl status netscope-pro"
echo "Logs:      journalctl -u netscope-pro -f"
echo
echo "Note: the dashboard is bound to $HOST and has no built-in login yet."
echo "Only expose it on a trusted LAN or behind an authenticated reverse proxy/VPN."
