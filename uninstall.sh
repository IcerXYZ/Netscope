#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --purge ) ]] || { echo "Usage: sudo bash uninstall.sh [--purge]"; exit 2; }
systemctl disable --now netscope.service 2>/dev/null || true
systemctl disable --now netscope-pro.service 2>/dev/null || true
rm -f /etc/systemd/system/netscope.service /etc/systemd/system/netscope-pro.service /usr/local/bin/netscope-agent-token
systemctl daemon-reload
if [[ -L /opt/netscope ]]; then unlink /opt/netscope; fi
# Keep release backups unless explicit purge is requested.
if [[ "${1:-}" == --purge ]]; then
  rm -rf -- /opt/netscope-releases /opt/netscope /opt/netscope-pro /etc/netscope
  rm -f -- /etc/netscope.env /etc/netscope-agent-tokens.json /etc/netscope-pro.env
fi
rm -f /etc/profile.d/netscope-banner.sh /etc/profile.d/netscope-pro-banner.sh
if [[ -f /etc/bash.bashrc ]]; then sed -i '/^# NETSCOPE_BANNER_HOOK$/,/^# END_NETSCOPE_BANNER_HOOK$/d' /etc/bash.bashrc; fi
rm -rf -- /usr/local/lib/netscope
echo "Service removed. Configuration and release backups are retained unless --purge was supplied."
echo "Firewall rules are unchanged. Revoke this machine's token separately on its central server."

