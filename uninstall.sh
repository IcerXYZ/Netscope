#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash uninstall.sh" >&2; exit 1; fi
systemctl disable --now netscope-pro.service 2>/dev/null || true
rm -f /etc/systemd/system/netscope-pro.service
systemctl daemon-reload
rm -rf /opt/netscope-pro
if id netscope >/dev/null 2>&1; then userdel netscope 2>/dev/null || true; fi
echo "NetScope Pro service and application files removed."
echo "The installer does not remove Python system packages or alter network settings."
