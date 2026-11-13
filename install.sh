#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/netscope-pro"
SERVICE_USER="netscope"
SERVICE_FILE="/etc/systemd/system/netscope-pro.service"
BANNER_FILE="/etc/profile.d/netscope-banner.sh"
ENV_FILE="/etc/netscope-pro.env"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${NETSCOPE_PORT:-8080}"
HOST="${NETSCOPE_HOST:-0.0.0.0}"
ASSUME_YES=0
logo() {
  clear 2>/dev/null || true
  printf '\033[38;5;208m'
  cat <<'LOGO'
 _   _ _____ _____ ____   ____ ___  ____  _____
| \ | | ____|_   _/ ___| / ___/ _ \|  _ \| ____|
|  \| |  _|   | | \___ \| |  | | | | |_) |  _|
| |\  | |___  | |  ___) | |__| |_| |  __/| |___
|_| \_|_____| |_| |____/ \____\___/|_|   |_____|
                         P R O
LOGO
  printf '\033[0m'
  echo "                 VM INSTALLATION WIZARD"
  echo "  --------------------------------------------------"
}
ask() { local prompt="$1" default="$2" answer; read -r -p "$prompt [$default]: " answer || true; printf '%s' "${answer:-$default}"; }
for arg in "$@"; do case "$arg" in --yes|-y) ASSUME_YES=1;; --help|-h) echo "Usage: sudo bash install.sh [--yes]"; exit 0;; *) echo "Unknown option: $arg"; exit 2;; esac; done
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash install.sh"; exit 1; fi
if [[ ! -f "$SOURCE_DIR/app.py" || ! -f "$SOURCE_DIR/requirements.txt" || ! -d "$SOURCE_DIR/templates" || ! -d "$SOURCE_DIR/static" ]]; then echo "Installer files are incomplete. Pull the latest NetScope repository and retry."; exit 1; fi
. /etc/os-release
case "${ID:-}" in debian|ubuntu) ;; *) echo "Supported: Debian/Ubuntu. Detected: ${PRETTY_NAME:-unknown}"; exit 1;; esac
logo
echo "This wizard installs NetScope Pro as a background service."
echo "It will not change IP addresses, routes, firewall rules or Proxmox bridges."
if [[ ! -f "$ENV_FILE" ]]; then install -m 0600 /dev/null "$ENV_FILE"; fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
  echo "Optional Discord webhook. Leave blank to keep the current setting."
  read -r -s -p "Discord webhook URL: " DISCORD_HOOK || true; echo
  if [[ -n "${DISCORD_HOOK:-}" ]]; then
    grep -v "^NETSCOPE_DISCORD_WEBHOOK=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
    printf "NETSCOPE_DISCORD_WEBHOOK=%s\n" "$DISCORD_HOOK" >> "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"; chmod 0600 "$ENV_FILE"; unset DISCORD_HOOK
  fi
fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
  PORT="$(ask 'Dashboard TCP port' "$PORT")"
  [[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>=1 && PORT<=65535)) || { echo "Invalid TCP port."; exit 1; }
  HOST="$(ask 'Listen address (0.0.0.0 = all VM interfaces)' "$HOST")"
  echo
  echo "INSTALLATION SUMMARY"
  echo " OS       : ${PRETTY_NAME:-$ID}"
  echo " URL      : http://<VM-IP>:$PORT"
  echo " Listen   : $HOST"
  echo " Path     : $APP_DIR"
  echo " Service  : netscope-pro"
  read -r -p "Continue with installation? [Y/n]: " confirm || true
  case "${confirm:-Y}" in [Yy]|[Yy][Ee][Ss]) ;; *) echo "Cancelled."; exit 0;; esac
fi
step(){ printf '\n\033[38;5;208m[%s/6]\033[0m %s\n' "$1" "$2"; }
step 1 "Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip ca-certificates
step 2 "Creating restricted service account"
id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
step 3 "Installing dashboard and Python dependencies"
install -d -o root -g "$SERVICE_USER" -m 0750 "$APP_DIR" "$APP_DIR/templates" "$APP_DIR/static"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/app.py" "$SOURCE_DIR/requirements.txt" "$APP_DIR/"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/templates/index.html" "$APP_DIR/templates/index.html"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.css" "$APP_DIR/static/app.css"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.js" "$APP_DIR/static/app.js"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
step 4 "Creating systemd service"
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
EnvironmentFile=-$ENV_FILE
ExecStart=$APP_DIR/venv/bin/gunicorn --workers 2 --bind $HOST:$PORT app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
[Install]
WantedBy=multi-user.target
EOF
step 5 "Installing standard NetScope shell login logo"
cat > "$BANNER_FILE" <<'BANNER'
#!/bin/sh
[ -t 1 ] || return 0 2>/dev/null || exit 0
printf '\033[38;5;208m'
cat <<'NETSCOPE'
 _   _ _____ _____ ____   ____ ___  ____  _____
| \ | | ____|_   _/ ___| / ___/ _ \|  _ \| ____|
|  \| |  _|   | | \___ \| |  | | | | |_) |  _|
| |\  | |___  | |  ___) | |__| |_| |  __/| |___
|_| \_|_____| |_| |____/ \____\___/|_|   |_____|
                         P R O
NETSCOPE
printf '\033[0m'
printf ' NetScope Pro monitoring node · %s\n\n' "$(hostname)"
BANNER
chmod 0644 "$BANNER_FILE"
step 6 "Starting service and checking health"
systemctl daemon-reload
systemctl enable --now netscope-pro.service
sleep 2
if ! systemctl is-active --quiet netscope-pro.service; then systemctl --no-pager --full status netscope-pro.service || true; echo "Install failed. Logs: journalctl -u netscope-pro -n 80"; exit 1; fi
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
printf '\033[38;5;82m INSTALLATION COMPLETE\033[0m\n'
echo "Dashboard : http://${IP:-VM-IP}:$PORT"
echo "Service   : systemctl status netscope-pro"
echo "Logs      : journalctl -u netscope-pro -f"
echo "Config    : $ENV_FILE (Discord webhook + cluster nodes)"
echo "Login logo: shown on new interactive shell logins"
echo
echo "Security: no built-in login is configured. Restrict port $PORT to trusted LAN/VPN."
