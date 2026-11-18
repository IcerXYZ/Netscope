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

# A later unattended update must preserve the selected central role and login.
sudo sed -i 's/^NETSCOPE_ROLE=.*/NETSCOPE_ROLE=server/;s/^NETSCOPE_AUTH_ENABLED=.*/NETSCOPE_AUTH_ENABLED=true/' /etc/netscope.env
sudo python3 - <<'PY'
import subprocess
password_hash=subprocess.check_output(
    ["/opt/netscope/venv/bin/python","-c",
     "from werkzeug.security import generate_password_hash; print(generate_password_hash('ci-test-password'))"],
    text=True).strip()
with open("/etc/netscope.env","a",encoding="utf-8") as handle:
    handle.write("NETSCOPE_AUTH_USERNAME=ci-admin\nNETSCOPE_AUTH_PASSWORD_HASH="+password_hash+"\n")
PY
sudo bash install.sh --yes
sudo grep -q '^NETSCOPE_ROLE=server$' /etc/netscope.env
sudo grep -q '^NETSCOPE_AUTH_ENABLED=true$' /etc/netscope.env
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:10103/api/status)" = 401
test "$(curl --silent --output /dev/null --write-out '%{http_code}' --data 'username=ci-admin&password=ci-test-password' http://127.0.0.1:10103/login)" = 302
echo "PASS unattended upgrade preserves central role and dashboard authentication"
