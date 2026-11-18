#!/usr/bin/env bash
set -euo pipefail
cleanup(){ sudo systemctl stop netscope.service >/dev/null 2>&1 || true; }
trap cleanup EXIT
sudo env NETSCOPE_ROLE=single NETSCOPE_PORT=10101 bash install.sh --yes
sudo systemd-analyze verify /etc/systemd/system/netscope.service
curl --fail --silent http://127.0.0.1:10101/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
sudo sed -i 's/^NETSCOPE_PORT=.*/NETSCOPE_PORT=10103/' /etc/netscope.env
sudo systemctl restart netscope
for attempt in $(seq 1 20); do
  if curl --fail --silent http://127.0.0.1:10103/health >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:10103/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
sudo env NETSCOPE_ROLE=single bash install.sh --yes
sudo grep -q '^NETSCOPE_PORT=10103$' /etc/netscope.env
curl --fail --silent http://127.0.0.1:10103/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
echo "PASS native installer, systemd environment port, config-only port change and port preservation on reinstall"
