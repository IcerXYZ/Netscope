#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/netscope"; SERVICE_USER="netscope"; SERVICE_FILE="/etc/systemd/system/netscope.service"
BANNER_FILE="/etc/profile.d/netscope-banner.sh"; ENV_FILE="/etc/netscope.env"; LOG_FILE="/var/log/netscope-install.log"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"; PORT=8080; HOST=127.0.0.1; ROLE=single; ASSUME_YES=0; USE_UFW=0
ACCESS_MODE=localhost; LAN_CIDR=""; AUTH_ENABLED=false; AUTH_USERNAME=""; AUTH_PASSWORD=""
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
if [[ ! -f "$SOURCE_DIR/app.py" || ! -f "$SOURCE_DIR/agent_tokens.py" || ! -f "$SOURCE_DIR/requirements.txt" || ! -d "$SOURCE_DIR/templates" || ! -d "$SOURCE_DIR/static" ]]; then echo "Installer files are incomplete. Pull the latest repository and retry."; exit 1; fi
. /etc/os-release
case "$ID" in debian|ubuntu) ;; *) echo "Supported: Debian/Ubuntu. Detected: $PRETTY_NAME"; exit 1;; esac
if [[ ! -f "$ENV_FILE" && -f /etc/netscope-pro.env ]]; then install -m 0600 /etc/netscope-pro.env "$ENV_FILE"; fi
if [[ ! -f "$ENV_FILE" ]]; then install -m 0600 /dev/null "$ENV_FILE"; fi
# Retire the previous service name during upgrades.
systemctl disable --now netscope-pro.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/netscope-pro.service /etc/profile.d/netscope-pro-banner.sh
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
 ACCESS_MODE=localhost
 LAN_CIDR="$(python3 - <<'PY'
import ipaddress, subprocess
try:
 for line in subprocess.check_output(["ip","-o","-f","inet","addr","show","scope","global"],text=True).splitlines():
  candidate=line.split()[3]; iface=ipaddress.ip_interface(candidate)
  if iface.ip.is_private and not iface.ip.is_loopback: print(candidate); break
except Exception: pass
PY
)"
 if [[ "$ASSUME_YES" -eq 0 ]]; then
  SERVER_URL="$(ask 'Central dashboard URL' 'http://192.168.6.20:8080')"
  AGENT_ID="$(ask 'Unique agent ID (e.g. proxmox-node-01)' "$(hostname -s)")"
  read -r -s -p "Unique agent token created on the central server: " AGENT_TOKEN || true; echo
 else
  SERVER_URL="$(printenv NETSCOPE_SERVER_URL 2>/dev/null || true)"; AGENT_TOKEN="$(printenv NETSCOPE_AGENT_TOKEN 2>/dev/null || true)"; AGENT_ID="$(printenv NETSCOPE_AGENT_ID 2>/dev/null || hostname -s)"
 fi
 [[ "$SERVER_URL" =~ ^https?:// ]] || { echo "Enter a valid central server URL."; exit 1; }
 [[ -n "$AGENT_TOKEN" ]] || { echo "An enrollment token is required."; exit 1; }
 [[ "$AGENT_ID" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || { echo "Invalid agent ID."; exit 1; }
 set_env NETSCOPE_SERVER_URL "$SERVER_URL"; set_env NETSCOPE_AGENT_TOKEN "$AGENT_TOKEN"; set_env NETSCOPE_AGENT_ID "$AGENT_ID"; unset AGENT_TOKEN
else
 if [[ "$ASSUME_YES" -eq 0 ]]; then
  PORT="$(ask 'Dashboard TCP port' "$PORT")"; [[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>=1 && PORT<=65535)) || { echo "Invalid TCP port."; exit 1; }
  LAN_CIDR="$(python3 - <<'PY'
import ipaddress, subprocess
try:
 for line in subprocess.check_output(["ip","-o","-f","inet","addr","show","scope","global"],text=True).splitlines():
  candidate=line.split()[3]
  iface=ipaddress.ip_interface(candidate)
  if iface.ip.is_private and not iface.ip.is_loopback:
   print(candidate); break
except Exception: pass
PY
)"
  if [[ -n "$LAN_CIDR" ]]; then
   LAN_IP="${LAN_CIDR%/*}"
   echo "Detected private LAN address: $LAN_IP"
   echo "  1) LAN only (other devices on this private subnet)"
   echo "  2) Localhost only (this machine)"
   access_choice="$(ask 'Choose access mode' '1')"
   if [[ "$access_choice" == "1" ]]; then HOST="$LAN_IP"; ACCESS_MODE=lan; else HOST=127.0.0.1; ACCESS_MODE=localhost; fi
  else
   echo "No private LAN IPv4 address detected; using localhost only."
   HOST=127.0.0.1; ACCESS_MODE=localhost
  fi
  auth_choice="$(ask 'Enable dashboard username/password login? (recommended)' 'Y')"
  case "$auth_choice" in [Nn]|[Nn][Oo]) AUTH_ENABLED=false;; *) AUTH_ENABLED=true;; esac
  if [[ "$AUTH_ENABLED" == true ]]; then
   AUTH_USERNAME="$(ask 'Dashboard username' 'admin')"
   [[ "$AUTH_USERNAME" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || { echo "Invalid username."; exit 1; }
   read -r -s -p "Dashboard password (minimum 12 characters): " AUTH_PASSWORD || true; echo
   [[ ${#AUTH_PASSWORD} -ge 12 ]] || { echo "Password must be at least 12 characters."; exit 1; }
   read -r -s -p "Confirm dashboard password: " AUTH_CONFIRM || true; echo
   [[ "$AUTH_PASSWORD" == "$AUTH_CONFIRM" ]] || { echo "Passwords do not match."; exit 1; }
   unset AUTH_CONFIRM
  fi
 fi
 if [[ "$ROLE" == server ]]; then
  echo "Central server will use individual per-agent credentials."
  echo "After installation, create one with: netscope-agent-token add <agent-id>"
  set_env NETSCOPE_AGENT_TOKEN ""
  if [[ ! -f /etc/netscope-agent-tokens.json ]]; then install -o root -g "$SERVICE_USER" -m 0640 /dev/null /etc/netscope-agent-tokens.json; else chown root:"$SERVICE_USER" /etc/netscope-agent-tokens.json; chmod 0640 /etc/netscope-agent-tokens.json; fi
 fi
fi
set_env NETSCOPE_ROLE "$ROLE"; set_env NETSCOPE_PORT "$PORT"; set_env NETSCOPE_HOST "$HOST"; set_env NETSCOPE_BIND "$HOST"; set_env NETSCOPE_AUTH_ENABLED "$AUTH_ENABLED"
if [[ "$AUTH_ENABLED" == true ]]; then
 set_env NETSCOPE_AUTH_USERNAME "$AUTH_USERNAME"
fi
if [[ "$ROLE" == server ]]; then set_env NETSCOPE_AGENT_TOKENS_FILE "/etc/netscope-agent-tokens.json"; fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
 read -r -p "Would you like NetScope to configure UFW firewall rules? [y/N]: " ufw_answer || true
 case "$ufw_answer" in [Yy]|[Yy][Ee][Ss]) USE_UFW=1;; *) USE_UFW=0;; esac
fi
if [[ "$ASSUME_YES" -eq 0 ]]; then
 echo; echo "READY TO INSTALL"; echo "  Machine role : $ROLE"
 if [[ "$ROLE" == agent ]]; then echo "  Central URL  : $SERVER_URL"; else echo "  Dashboard    : http://$HOST:$PORT ($ACCESS_MODE)"; echo "  Login        : $AUTH_ENABLED"; fi
 echo "  Discord      : existing webhook will be preserved"
 read -r -p "Continue? [Y/n]: " confirm || true; if [[ -z "$confirm" ]]; then confirm=Y; fi
 case "$confirm" in [Yy]|[Yy][Ee][Ss]) ;; *) echo "Cancelled."; exit 0;; esac
fi
: > "$LOG_FILE"; export DEBIAN_FRONTEND=noninteractive; echo; echo "Installing NetScope"
run_step "Updating package lists" apt-get update -qq
run_step "Installing Python requirements" apt-get install -y -qq python3 python3-venv python3-pip ca-certificates
run_step "Creating service account" bash -c "id $SERVICE_USER >/dev/null 2>&1 || useradd --system --home-dir $APP_DIR --create-home --shell /usr/sbin/nologin $SERVICE_USER"
# Permit read-only access to system authentication logs where the distro exposes them via adm/journal.
if getent group systemd-journal >/dev/null 2>&1; then usermod -aG adm,systemd-journal "$SERVICE_USER"; else usermod -aG adm "$SERVICE_USER"; fi
install -d -o root -g "$SERVICE_USER" -m 0750 "$APP_DIR" "$APP_DIR/templates" "$APP_DIR/static"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/app.py" "$SOURCE_DIR/agent_tokens.py" "$SOURCE_DIR/requirements.txt" "$APP_DIR/"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/templates/index.html" "$APP_DIR/templates/index.html"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/templates/login.html" "$APP_DIR/templates/login.html"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.css" "$APP_DIR/static/app.css"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/login.css" "$APP_DIR/static/login.css"
install -o root -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/static/app.js" "$APP_DIR/static/app.js"
run_step "Preparing Python environment" python3 -m venv "$APP_DIR/venv"
run_step "Installing dashboard libraries" "$APP_DIR/venv/bin/pip" install --disable-pip-version-check -q -r "$APP_DIR/requirements.txt"
cat > /usr/local/bin/netscope-agent-token <<EOF
#!/bin/sh
exec "$APP_DIR/venv/bin/python" "$APP_DIR/agent_tokens.py" "$@"
EOF
chmod 0755 /usr/local/bin/netscope-agent-token
run_step "Checking NetScope Python files" "$APP_DIR/venv/bin/python" -m py_compile "$APP_DIR/app.py" "$APP_DIR/agent_tokens.py"
if [[ "$AUTH_ENABLED" == true ]]; then
 HASH="$(printf '%s' "$AUTH_PASSWORD" | "$APP_DIR/venv/bin/python" -c 'import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.stdin.read(), method="scrypt"))')"
 set_env NETSCOPE_AUTH_PASSWORD_HASH "$HASH"
 unset AUTH_PASSWORD HASH
fi
if ! grep -q '^NETSCOPE_SECRET_KEY=' "$ENV_FILE"; then set_env NETSCOPE_SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"; fi
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
role="$(sed -n 's/^NETSCOPE_ROLE=//p' /etc/netscope.env 2>/dev/null | head -n1)"
port="$(sed -n 's/^NETSCOPE_PORT=//p' /etc/netscope.env 2>/dev/null | head -n1)"
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '\n\033[38;5;30mSYSTEM\033[0m\n'
printf 'Host       : %s\nService    : %b\nAutostart  : %s\nUptime     : %s\n' "$host" "$service_state" "$auto_state" "${up:-Unknown}"
printf '\n\033[38;5;30mDASHBOARD\033[0m\n'
if [ "$role" = agent ]; then
  central="$(sed -n 's/^NETSCOPE_SERVER_URL=//p' /etc/netscope.env 2>/dev/null | head -n1)"
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
 # Remove a previous broad NetScope port rule before adding a subnet-scoped rule.
 ufw --force delete allow "$PORT/tcp" >/dev/null 2>&1 || true
 if [[ -z "$LAN_CIDR" ]]; then
  echo "UFW was not enabled: no private LAN subnet was detected. Configure firewall rules manually to avoid locking yourself out."
 else
  run_step "Allowing SSH from private LAN $LAN_CIDR" ufw allow from "$LAN_CIDR" to any port 22 proto tcp
  if [[ "$ACCESS_MODE" == lan ]]; then
   run_step "Allowing NetScope from private LAN $LAN_CIDR" ufw allow from "$LAN_CIDR" to any port "$PORT" proto tcp
  else
   echo "Localhost mode: no NetScope inbound firewall rule added."
  fi
  run_step "Enabling UFW firewall" ufw --force enable
  echo "UFW enabled with private-subnet-only access rules."
 fi
else
 echo "UFW setup skipped; existing firewall settings were left unchanged."
fi
run_step "Starting NetScope in the background" systemctl enable --now netscope.service
sleep 1
if ! systemctl is-active --quiet netscope.service; then systemctl --no-pager --full status netscope.service || true; echo "Service failed. Check: journalctl -u netscope -n 80"; exit 1; fi
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo; printf '\033[38;5;82m SETUP COMPLETE\033[0m\n'
if [[ "$ROLE" == agent ]]; then
 echo "Role      : Monitoring agent"; echo "Central   : $SERVER_URL"; echo "Status    : Sending reports every 5 seconds"; echo "Local bind: 127.0.0.1 (not exposed to LAN)"
else
 echo "Role      : $ROLE"; echo "Dashboard : http://$HOST:$PORT"
 echo "Access    : $ACCESS_MODE"
 if [[ "$ROLE" == server ]]; then echo "Agent tokens: netscope-agent-token add <agent-id>"; fi
fi
echo "Service   : systemctl status netscope"; echo "Logs      : journalctl -u netscope -f"
echo "Agent CLI : netscope-agent-token add <agent-id> (central server only)"; echo "Config    : $ENV_FILE (Discord webhook and agent settings)"; echo "Install log: $LOG_FILE"
echo "Security  : keep dashboard access on your trusted LAN/VPN."
