#!/usr/bin/env bash
set -Eeuo pipefail

# NetScope full removal. Only paths owned by NetScope are removed.
if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash uninstall.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_CHECKOUT=""
if [[ -f "$SCRIPT_DIR/install.sh" && -f "$SCRIPT_DIR/app.py" ]]; then
  SOURCE_CHECKOUT="$SCRIPT_DIR"
fi

echo
echo "NETSCOPE FULL UNINSTALL"
echo "This permanently removes:"
echo "  - NetScope services, application files and virtual environment"
echo "  - Dashboard settings, passwords, Discord webhook and agent token registry"
echo "  - NetScope command-line tools, banner and installer logs"
echo "  - The dedicated netscope service account"
if [[ -n "$SOURCE_CHECKOUT" ]]; then
  echo "  - Source checkout: $SOURCE_CHECKOUT"
fi
echo
echo "Your UFW/firewall rules, Python packages, Docker itself and unrelated files will NOT be changed."
echo "Agent tokens will be permanently deleted. Connected agents will no longer authenticate."
echo

if [[ ! -t 0 ]]; then
  echo "Uninstall requires an interactive confirmation. Run it in a terminal." >&2
  exit 1
fi
read -r -p 'Type DELETE to permanently remove NetScope: ' confirmation
if [[ "$confirmation" != "DELETE" ]]; then
  echo "Cancelled. Nothing was removed."
  exit 0
fi

# Stop and disable native services first.
systemctl disable --now netscope.service >/dev/null 2>&1 || true
systemctl disable --now netscope-pro.service >/dev/null 2>&1 || true

# If this checkout contains a Compose project, remove only that project's
# containers, local image and project volumes before deleting its .env/source.
if [[ -n "$SOURCE_CHECKOUT" ]] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && [[ -f "$SOURCE_CHECKOUT/compose.yaml" ]]; then
  echo "Removing the NetScope Docker Compose project (if present)..."
  docker compose --project-directory "$SOURCE_CHECKOUT" -f "$SOURCE_CHECKOUT/compose.yaml" down --remove-orphans --rmi local --volumes || {
    echo "Warning: Docker cleanup did not complete. Check 'docker compose ps' in $SOURCE_CHECKOUT." >&2
  }
fi

rm -f /etc/systemd/system/netscope.service
rm -f /etc/systemd/system/netscope-pro.service
rm -f /etc/profile.d/netscope-banner.sh
rm -f /etc/profile.d/netscope-pro-banner.sh

# Remove only the marked NetScope block, preserving the rest of bash.bashrc.
if [[ -f /etc/bash.bashrc ]]; then
  sed -i '/^# NETSCOPE_BANNER_HOOK$/,/^# END_NETSCOPE_BANNER_HOOK$/d' /etc/bash.bashrc
fi

rm -rf /opt/netscope /opt/netscope-pro
rm -rf /usr/local/lib/netscope
rm -f /usr/local/bin/netscope-agent-token
rm -f /etc/netscope.env /etc/netscope-pro.env /etc/netscope-agent-tokens.json
rm -f /var/log/netscope-install.log
rm -rf /var/lib/netscope /var/cache/netscope /run/netscope
rm -f /etc/logrotate.d/netscope /etc/tmpfiles.d/netscope.conf

if id netscope >/dev/null 2>&1; then
  userdel netscope 2>/dev/null || true
fi
if getent group netscope >/dev/null 2>&1; then
  groupdel netscope 2>/dev/null || true
fi

systemctl daemon-reload
systemctl reset-failed netscope.service netscope-pro.service >/dev/null 2>&1 || true

# The repository clone may contain the installer's own running script. Delete it
# last, after all other cleanup operations have completed.
if [[ -n "$SOURCE_CHECKOUT" && -d "$SOURCE_CHECKOUT" && "$SOURCE_CHECKOUT" != "/" && "$SOURCE_CHECKOUT" != "/opt" ]]; then
  rm -rf -- "$SOURCE_CHECKOUT"
fi

echo
echo "NetScope has been completely removed."
echo "Firewall rules and system-wide Python packages were left unchanged."
