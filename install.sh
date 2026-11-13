#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/netscope"; SERVICE_USER="netscope"; SERVICE_FILE="/etc/systemd/system/netscope.service"
BANNER_FILE="/etc/profile.d/netscope-banner.sh"; ENV_FILE="/etc/netscope.env"; LEGACY_ENV_FILE="/etc/netscope.env"; LOG_FILE="/var/log/netscope-install.log"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"; PORT=8080; HOST=0.0.0.0; ROLE=single; ASSUME_YES=0; USE_UFW=0
logo() {
 clear 2>/dev/null || true; printf '\033[38;5;208m'
 cat <<'LOGO'
 _   _ _____ _____ ____   ____ ___  ____  _____
| \ | | ____|_   _/ ___| / ___/ _ \|  _ \| ____|
|  \| |  _|   | | \___ \| |  | | | | |_) |  _|
| |\  | |___  | |  ___) | |__| |_| |  __/| |___
|_| \_|_____| |_| |____/ \____\___/|_|   |_____|
LOGO
 printf '\033[0m'; echo "             NETWORK INTELLIGENCE"; echo "  ------------------------------------------------"
}
ask() { local p="$1" d="$2" a; read -r -p "$p [$d]: " a || true; if [[ -n "$a" ]]; then printf '%s' "$a"; else printf '%s' "$d"; fi; }
set_env() {
 local key="$1" value="$2" tmp; tmp="$(mktemp)"
 if [[ -f "$ENV_FILE" ]]; then grep -v "^$key=" "$ENV_FILE" > "$tmp" || true; fi
 printf '%s=%s\n' "$key" "$value" >> "$tmp"; install -m 0600 "$tmp" "$ENV_FILE"; rm -f "$tmp"
}
run_step() {
 local label="$1"; shift; local i=0 pid rc frame
 "$@" >>"$LOG_FILE" 2>&1 & pid=$!
 while kill -0 "$pid" 2>/dev/null; do
  case "$i" in 0) frame='▖';; 1) frame='▘';; 2) frame='▝';; *) frame='▗';; esac
  printf '\r  \033[38;5;208m%s\033[0m %s' "$label" "$frame"; i=$(((i+1)%4)); sleep 0.12
 done
 if wait "$pid"; then printf '\r  \033[38;5;82m✓\033[0m %s\n' "$label"
 else rc=$?; printf '\r  \033[38;5;196m✗\033[0m %s\n' "$label"; echo "Details: $LOG_FILE"; tail -n 18 "$LOG_FILE" || true; return "$rc"; fi
}
for arg in "$@"; do case "$arg" in --yes|-y) ASSUME_YES=1;; --help|-h) echo "Usage: sudo bash install.sh [--yes]"; exit 0;; *) echo "Unknown option: $arg"; exit 2;; esac; done
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash install.sh"; exit 1; fi
if [[ ! -f "$SOURCE_DIR/app.py" || ! -f "$SOURCE_DIR/requirements.txt" || ! -d "$SOURCE_DIR/templates" || ! -d "$SOURCE_DIR/static" ]]; then echo "Installer files are incomplete. Pull the latest repository and retry."; exit 1; fi
. /etc/os-release
case "$ID" in debian|ubuntu) ;; *) echo "Supported: Debian/Ubuntu. Detected: $PRETTY_NAME"; exit 1;; esac
if [[ ! -f "$ENV_FILE" ]]; then
 if [[ -f "$LEGACY_ENV_FILE" ]]; then install -m 0600 "$LEGACY_ENV_FILE" "$ENV_FILE"; else install -m 0600 /dev/null "$ENV_FILE"; fi
fi
# Stop the previous service name during an upgrade; keep its data/config.
systemctl disable --now netscope.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/netscope-pro.service
logo
echo "How should this machine be used?"
echo "  1) Single host      Monitor only this machine"
echo "  2) Central server   Collect data from all agents"
echo "  3) Monitoring agent Send this machine's data to the central server"
if [[ "$ASSUME_YES" -eq 0 ]]; then
 read -r -p "Choose 1, 2 or 3 [1]: " choice || true; if [[ -z "$choice" ]]; then choice=1; fi
 case "$choice" in 1) ROLE=single;; 2) ROLE=server;; 3) ROLE=agent;; *) echo "Invalid choice."; exit 1;; esac
else
 if [[ -n "$(printenv NETSCOPE_ROLE 2>/dev/null || true)" ]]; then ROLE="$(printenv NETSCOPE_ROLE)"; fi
fi
if [[ "$ROLE" == agent ]]; then
 HOST=127.0.0.1
 if [[ "$ASSUME_YES" -eq 0 ]]; then
  SERVER_URL="$(ask 'Central dashboard URL' 'http://192.168.6.20:8080')"
  read -r -s -p "Central server enrollment token: " AGENT_TOKEN || true; echo
 else
  SERVER_URL="$(printenv NETSCOPE_SERVER_URL 2>/dev/null || true)"; AGENT_TOKEN="$(printenv NETSCOPE_AGENT_TOKEN 2>/dev/null || true)"
 fi
 [[ "$SERVER_URL" =~ ^https?:// ]] || { echo "Enter a valid central server URL."; exit 1; }
 [[ -n "$AGENT_TOKEN" ]] || { echo "An enrollment token is required."; exit 1; }
 set_env NETSCOPE_SERVER_URL "$SERVER_URL"; set_env NETSCOPE_AGENT_TOKEN "$AGENT_TOKEN"; unset AGENT_TOKEN
else
 if [[ "$ASSUME_YES" -eq 0 ]]; then
  PORT="$(ask 'Dashboard TCP port' "$PORT")"; [[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>=1 && PORT<=65535)) || { echo "Invalid TCP port."; exit 1; }
  HOST="$(ask 'Listen address (0.0.0.0 = LAN access)' "$HOST")"
 fi
 if [[ "$ROLE" == server ]]; then
  TOKEN="$(grep -m1 '^NETSCOPE_AGENT_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)"
  if [[ -z "$TOKEN" ]]; then TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"; fi
  set_env NETSCOPE_AGENT_TOKEN "$TOKEN"; echo
  echo "CENTRAL SERVER TOKEN — copy this into each agent installation:"
  printf '\033[38;5;208m%s\033[0m\n' "$TOKEN"; echo "Keep it private. Existing tokens are kept on updates."
 fi
fi
set_env NETSCOPE_ROLE "$ROLE"; set_env NETSCOPE_PORT "$PORT"; set_env NETSCOPE_HOST "$HOST"
if [[ "$ASSUME_YES" -eq 0 ]]; then
 read -r -p "Would you like NetScope to configure UFW firewall rules? [y/N]: " ufw_answer || true
 case "$ufw_answer" in [Yy]|[Yy][Ee][Ss]) USE_UFW=1;; *) USE_UFW=0;; esac
fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
 echo; echo "READY TO INSTALL"; echo "  Machine role : $ROLE"
 if [[ "$ROLE" == agent ]]; then echo "  Central URL  : $SERVER_URL"; else echo "  Dashboard    : http://<machine-IP>:$PORT"; fi
 echo "  Discord      : existing webhook will be preserved"
 read -r -p "Continue? [Y/n]: " confirm || true; if [[ -z "$confirm" ]]; then confirm=Y; fi
 case "$confirm" in [Yy]|[Yy][Ee][Ss]) ;; *) echo "Cancelled."; exit 0;; esac
fi
: > "$LOG_FILE"; export DEBIAN_FRONTEND=noninteractive; echo; echo "Installing NetScope"
run_step "Updating package lists" apt-get update -qq
run_step "Installing Python requirements" apt-get install -y -qq python3 python3-venv python3-pip ca-certificates
run_step "Creating service account" bash -c "id $SERVICE_USER >/dev/null 2>&1 || useradd --system --home-dir $APP_DIR --create-home --shell /usr/sbin/nologin $SERVICE_USER"
install -d -o root -g "$SERVICE_USER" -m 0750 "$APP_DIR" "$APP_DIR/templates" "$APP_DIR/static"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/app.py" "$SOURCE_DIR/requirements.txt" "$APP_DIR/"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/templates/index.html" "$APP_DIR/templates/index.html"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.css" "$APP_DIR/static/app.css"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.js" "$APP_DIR/static/app.js"
run_step "Preparing Python environment" python3 -m venv "$APP_DIR/venv"
run_step "Installing dashboard libraries" "$APP_DIR/venv/bin/pip" install --disable-pip-version-check -q -r "$APP_DIR/requirements.txt"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=NetScope monitoring service
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=-$ENV_FILE
ExecStart=$APP_DIR/venv/bin/gunicorn --workers 1 --bind $HOST:$PORT app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
[Install]
WantedBy=multi-user.target
EOF
BANNER_SCRIPT="/usr/local/lib/netscope/banner.sh"
install -d -m 0755 /usr/local/lib/netscope
cat > "$BANNER_SCRIPT" <<'BANNER'
#!/bin/sh
if [ -n "${NETSCOPE_BANNER_SHOWN:-}" ]; then return 0; fi
if [ ! -t 1 ]; then return 0; fi
export NETSCOPE_BANNER_SHOWN=1
printf '\033[38;5;30m'
cat <<'NETSCOPE'
███╗   ██╗███████╗████████╗ ██████╗ ██████╗ ██████╗ ███████╗
████╗  ██║██╔════╝╚══██╔══╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
██╔██╗ ██║█████╗     ██║   ██║     ██║   ██║██████╔╝█████╗
██║╚██╗██║██╔══╝     ██║   ██║     ██║   ██║██╔═══╝ ██╔══╝
██║ ╚████║███████╗   ██║   ╚██████╗╚██████╔╝██║     ███████╗
╚═╝  ╚═══╝╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝     ╚══════╝
NETSCOPE
printf '\033[0m'
printf '\033[90m------------------------------------------------------------\033[0m\n'
printf ' NETSCOPE  /  NETWORK INTELLIGENCE\n'
printf '\033[90m------------------------------------------------------------\033[0m\n'
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet netscope.service; then service_state='\033[38;5;82mONLINE\033[0m'; else service_state='\033[38;5;196mOFFLINE\033[0m'; fi
  if systemctl is-enabled --quiet netscope.service 2>/dev/null; then auto_state='Enabled'; else auto_state='Disabled'; fi
else service_state='Unknown'; auto_state='Unknown'; fi
up="$(uptime -p 2>/dev/null | sed 's/^up //')"
host="$(hostname 2>/dev/null)"
role="$(sed -n 's/^NETSCOPE_ROLE=//p' /etc/netscope-pro.env 2>/dev/null | head -n1)"
port="$(sed -n 's/^NETSCOPE_PORT=//p' /etc/netscope-pro.env 2>/dev/null | head -n1)"
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '\n\033[38;5;30mSYSTEM\033[0m\n'
printf 'Host       : %s\nService    : %b\nAutostart  : %s\nUptime     : %s\n' "$host" "$service_state" "$auto_state" "${up:-Unknown}"
printf '\n\033[38;5;30mDASHBOARD\033[0m\n'
if [ "$role" = agent ]; then
  central="$(sed -n 's/^NETSCOPE_SERVER_URL=//p' /etc/netscope-pro.env 2>/dev/null | head -n1)"
  printf 'Central    : %s\n' "${central:-Not configured}"
else
  printf 'Web        : http://%s:%s\n' "${ip:-localhost}" "${port:-8080}"
fi
printf 'Logs       : journalctl -u netscope -f\n'
printf '\n\033[90mInfrastructure monitoring.\033[0m\n\n'
BANNER
chmod 0644 "$BANNER_SCRIPT"
cat > "$BANNER_FILE" <<'HOOK'
[ -r /usr/local/lib/netscope/banner.sh ] && . /usr/local/lib/netscope/banner.sh
HOOK
chmod 0644 "$BANNER_FILE"
BASHRC_FILE="/etc/bash.bashrc"
if [[ -f "$BASHRC_FILE" ]] && ! grep -q 'NETSCOPE_BANNER_HOOK' "$BASHRC_FILE"; then
 cat >> "$BASHRC_FILE" <<'HOOK'

# NETSCOPE_BANNER_HOOK
if [ -n "$PS1" ] && [ -r /usr/local/lib/netscope/banner.sh ]; then
    . /usr/local/lib/netscope/banner.sh
fi
# END_NETSCOPE_BANNER_HOOK
HOOK
fi
run_step "Reloading system service manager" systemctl daemon-reload
if [[ "$USE_UFW" -eq 1 ]]; then
 run_step "Installing UFW firewall" apt-get install -y -qq ufw
 run_step "Allowing SSH on TCP 22" ufw allow 22/tcp
 run_step "Allowing HTTP on TCP 80" ufw allow 80/tcp
 run_step "Allowing NetScope port TCP $PORT" ufw allow "$PORT/tcp"
 run_step "Enabling UFW firewall" ufw --force enable
 echo "UFW enabled: allowed TCP ports 22, 80 and $PORT."
else
 echo "UFW setup skipped; existing firewall settings were left unchanged."
fi
run_step "Starting NetScope in the background" systemctl enable --now netscope.service
sleep 1
if ! systemctl is-active --quiet netscope-pro.service; then systemctl --no-pager --full status netscope.service || true; echo "Service failed. Check: journalctl -u netscope -n 80"; exit 1; fi
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo; printf '\033[38;5;82m SETUP COMPLETE\033[0m\n'
if [[ "$ROLE" == agent ]]; then
 echo "Role      : Monitoring agent"; echo "Central   : $SERVER_URL"; echo "Status    : Sending reports every 5 seconds"; echo "Local bind: 127.0.0.1 (not exposed to LAN)"
else
 echo "Role      : $ROLE"; echo "Dashboard : http://$IP:$PORT"
fi
echo "Service   : systemctl status netscope"; echo "Logs      : journalctl -u netscope -f"
echo "Config    : $ENV_FILE (Discord webhook and agent settings)"; echo "Install log: $LOG_FILE"
echo "Security  : keep dashboard access on your trusted LAN/VPN."
