#!/usr/bin/env bash
set -Eeuo pipefail
root="$(pwd)"
python - <<'PY'
from pathlib import Path
from werkzeug.security import generate_password_hash
import secrets
data={'NETSCOPE_ROLE':'server','NETSCOPE_BIND':'127.0.0.1','NETSCOPE_PORT':'18080','NETSCOPE_AUTH_ENABLED':'true',
      'NETSCOPE_SECRET_KEY':secrets.token_hex(32),'NETSCOPE_AUTH_USERNAME':'admin',
      'NETSCOPE_AUTH_PASSWORD_HASH':generate_password_hash('integration-test-password',method='scrypt')}
Path('/tmp/netscope-smoke.env').write_text(''.join(f"{k}='{v}'\n" for k,v in data.items()))
PY
sudo install -m 0600 /tmp/netscope-smoke.env /etc/netscope.env
sudo bash install.sh --yes
pid_before="$(systemctl show netscope -p MainPID --value)"
curl --fail --silent http://127.0.0.1:18080/health >/dev/null
[[ "$(curl --silent -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/api/status)" == 401 ]]
sudo openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' -keyout /etc/netscope/tls.key -out /etc/netscope/tls.crt 2>/dev/null
sudo chown root:netscope /etc/netscope/tls.key /etc/netscope/tls.crt
sudo chmod 0640 /etc/netscope/tls.key
sudo install -m 0644 /etc/netscope/tls.crt /tmp/netscope-ca.crt
printf "NETSCOPE_TLS_CERT='/etc/netscope/tls.crt'\nNETSCOPE_TLS_KEY='/etc/netscope/tls.key'\n" | sudo tee -a /etc/netscope.env >/dev/null
sudo bash install.sh --yes
pid_after="$(systemctl show netscope -p MainPID --value)"
[[ "$pid_before" != "$pid_after" ]]
curl --fail --silent --cacert /tmp/netscope-ca.crt https://localhost:18080/health >/dev/null
PYTHONPATH="$root" python tests/live_http.py
[[ "$(curl --silent --cacert /tmp/netscope-ca.crt -o /dev/null -w '%{http_code}' -H 'Host: attacker.invalid' https://localhost:18080/health)" == 400 ]]
sudo netscope-agent-token add integration-node >/tmp/netscope-enrollment
python - <<'PY'
import json, ssl, urllib.request
from pathlib import Path
token=Path('/tmp/netscope-enrollment').read_text().split('Token (shown once): ')[1].strip()
body=json.dumps({'agent_id':'integration-node','data':{'hostname':'test-node','interfaces':[]}}).encode()
context=ssl.create_default_context(cafile='/tmp/netscope-ca.crt')
request=urllib.request.Request('https://localhost:18080/api/agent/report',data=body,headers={'Content-Type':'application/json','X-NetScope-Token':token})
with urllib.request.urlopen(request,context=context) as response: assert response.status==200
Path('/tmp/netscope-report.json').write_bytes(body)
PY
sudo netscope-agent-token revoke integration-node
sudo netscope-agent-token add concurrent-one >/tmp/netscope-token-one &
first=$!
sudo netscope-agent-token add concurrent-two >/tmp/netscope-token-two &
second=$!
wait "$first"; wait "$second"
sudo python3 -c "import json; d=json.load(open('/etc/netscope/agents.json')); assert 'concurrent-one' in d and 'concurrent-two' in d"
# Validate malformed configuration fails without switching a running installation.
sudo cp /etc/netscope.env /tmp/netscope-valid.env
printf "NETSCOPE_AUTH_ENABLED='false'\n" | sudo tee -a /etc/netscope.env >/dev/null
if sudo bash install.sh --yes; then echo 'Invalid auth configuration accepted'; exit 1; fi
sudo cp /tmp/netscope-valid.env /etc/netscope.env
[[ "$(systemctl show netscope -p MainPID --value)" == "$pid_after" ]]
sudo systemctl restart netscope
echo 'Linux clean install, TLS upgrade, restart, host validation, agent enrollment/revocation and invalid-upgrade checks passed.'
