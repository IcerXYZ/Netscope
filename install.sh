#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --yes ) ]] || { echo "Usage: sudo bash install.sh [--yes]"; exit 2; }
. /etc/os-release
[[ "$ID" == debian || "$ID" == ubuntu ]] || { echo "Supported: Debian/Ubuntu"; exit 1; }
for f in app.py security.py telemetry_schema.py launch.py gunicorn.conf.py configure.py agent_tokens.py requirements.lock netscope.service; do
  [[ -f "$SOURCE_DIR/$f" ]] || { echo "Missing source file: $f"; exit 1; }
done
if [[ "${1:-}" == --yes ]]; then
  [[ -f /etc/netscope.env ]] || { echo "Unattended setup requires a preconfigured /etc/netscope.env."; exit 1; }
else
  echo "Install/update NetScope, its Python environment and a restricted service account."
  echo "Existing configuration is preserved unless changed during setup. Firewall rules are not changed."
  read -r -p "Continue? [y/N]: " answer
  [[ "$answer" == y || "$answer" == Y ]] || exit 0
fi
apt-get update -qq
apt-get install -y -qq python3 python3-venv ca-certificates util-linux
getent group netscope >/dev/null || groupadd --system netscope
id netscope >/dev/null 2>&1 || useradd --system --gid netscope --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin netscope
# Read-only journal permissions, rather than running the web service as root.
if getent group systemd-journal >/dev/null; then usermod -aG systemd-journal netscope; fi
if getent group adm >/dev/null; then usermod -aG adm netscope; fi
install -d -o root -g netscope -m 0750 /etc/netscope /opt/netscope-releases
if [[ ! -s /etc/netscope/agents.json ]]; then printf '{}\n' > /etc/netscope/agents.json; fi
chown root:netscope /etc/netscope/agents.json
chmod 0640 /etc/netscope/agents.json
release="$(mktemp -d /opt/netscope-releases/release-XXXXXXXX)"
chown root:netscope "$release"; chmod 0750 "$release"
for f in app.py security.py telemetry_schema.py launch.py gunicorn.conf.py configure.py agent_tokens.py requirements.lock; do
  install -o root -g netscope -m 0640 "$SOURCE_DIR/$f" "$release/$f"
done
cp -R "$SOURCE_DIR/static" "$SOURCE_DIR/templates" "$release/"
chown -R root:netscope "$release/static" "$release/templates"
find "$release/static" "$release/templates" -type d -exec chmod 0750 {} +
find "$release/static" "$release/templates" -type f -exec chmod 0640 {} +
python3 -m venv "$release/venv"
"$release/venv/bin/pip" install --disable-pip-version-check -q --require-hashes -r "$release/requirements.lock"
chown -R root:netscope "$release"
chmod -R u=rwX,g=rX,o= "$release"
pending="$(mktemp /etc/.netscope-env-XXXXXXXX)"
backup="$(mktemp -d /opt/netscope-releases/rollback-XXXXXXXX)"
had_env=0; had_unit=0; switched=0; old_target=""; legacy=""
if [[ -f /etc/netscope.env ]]; then cp -p /etc/netscope.env "$backup/env"; had_env=1; fi
if [[ -f /etc/systemd/system/netscope.service ]]; then cp -p /etc/systemd/system/netscope.service "$backup/unit"; had_unit=1; fi
was_active=0; systemctl is-active --quiet netscope.service && was_active=1
rollback() {
  rc=$?
  if [[ $rc -ne 0 && "$switched" -eq 1 ]]; then
    systemctl stop netscope.service || true
    if [[ -L /opt/netscope ]]; then unlink /opt/netscope; fi
    if [[ -n "$old_target" ]]; then ln -s "$old_target" /opt/netscope; fi
    if [[ -n "$legacy" ]]; then mv "$legacy" /opt/netscope; fi
    if [[ "$had_env" -eq 1 ]]; then cp -p "$backup/env" /etc/netscope.env; else rm -f /etc/netscope.env; fi
    if [[ "$had_unit" -eq 1 ]]; then cp -p "$backup/unit" /etc/systemd/system/netscope.service; else rm -f /etc/systemd/system/netscope.service; fi
    systemctl daemon-reload
    if [[ "$was_active" -eq 1 ]]; then systemctl start netscope.service || true; fi
    echo "Update failed; previous service/configuration restored. Prepared files retained in $release."
  fi
  rm -f "$pending"
  exit "$rc"
}
trap rollback EXIT
if [[ "${1:-}" == --yes ]]; then
  "$release/venv/bin/python" "$release/configure.py" --file /etc/netscope.env --check
  cp /etc/netscope.env "$pending"
else
  "$release/venv/bin/python" "$release/configure.py" --file "$pending" --from-file /etc/netscope.env
fi
# Only after preparation succeeds, switch code/config and explicitly restart.
if [[ -L /opt/netscope ]]; then old_target="$(readlink /opt/netscope)"
elif [[ -e /opt/netscope ]]; then legacy="$backup/legacy"; fi
systemctl stop netscope.service 2>/dev/null || true
switched=1
if [[ -L /opt/netscope ]]; then unlink /opt/netscope
elif [[ -n "$legacy" ]]; then mv /opt/netscope "$legacy"; fi
ln -s "$release" /opt/netscope
install -o root -g root -m 0600 "$pending" /etc/netscope.env
install -o root -g root -m 0644 "$SOURCE_DIR/netscope.service" /etc/systemd/system/netscope.service
cat > /usr/local/bin/netscope-agent-token <<'HELPER'
#!/bin/sh
exec /opt/netscope/venv/bin/python /opt/netscope/agent_tokens.py "$@"
HELPER
chmod 0755 /usr/local/bin/netscope-agent-token
systemctl daemon-reload
systemctl enable netscope.service
systemctl restart netscope.service
sleep 3
systemctl is-active --quiet netscope.service
systemctl disable --now netscope-pro.service 2>/dev/null || true
echo "NetScope restarted successfully. Previous release/configuration retained at $backup."
echo "LAN mode requires a trusted TLS certificate and an inbound firewall rule limited to your management clients."
echo "Old scrypt/shared agent tokens are not migrated. Enroll each agent: sudo netscope-agent-token add node-01"

