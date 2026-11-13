#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash uninstall.sh" >&2; exit 1; fi
systemctl disable --now netscope.service 2>/dev/null || true
systemctl disable --now netscope-pro.service 2>/dev/null || true
rm -f /etc/systemd/system/netscope.service /etc/profile.d/netscope-banner.sh
if [[ -f /etc/bash.bashrc ]]; then sed -i '/^# NETSCOPE_BANNER_HOOK$/,/^# END_NETSCOPE_BANNER_HOOK$/d' /etc/bash.bashrc; fi
rm -rf /usr/local/lib/netscope
systemctl daemon-reload
rm -rf /opt/netscope /opt/netscope-pro
if id netscope >/dev/null 2>&1; then userdel netscope 2>/dev/null || true; fi
rm -f /etc/netscope.env /etc/netscope-pro.env
 echo "NetScope service, files and terminal banner removed."
echo "System Python packages and network settings were not changed."
