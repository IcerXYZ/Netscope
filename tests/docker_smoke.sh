#!/usr/bin/env bash
set -Eeuo pipefail
docker build -t netscope:smoke .
tmp="$(mktemp -d)"
trap 'docker rm -f netscope-smoke >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
mkdir "$tmp/runtime"
chmod 0755 "$tmp" "$tmp/runtime"
python - "$tmp" <<'PY'
import secrets,sys
from pathlib import Path
from werkzeug.security import generate_password_hash
root=Path(sys.argv[1])
data={'NETSCOPE_ROLE':'server','NETSCOPE_BIND':'127.0.0.1','NETSCOPE_PORT':'18081','NETSCOPE_AUTH_ENABLED':'true',
      'NETSCOPE_SECRET_KEY':secrets.token_hex(32),'NETSCOPE_AUTH_USERNAME':'admin',
      'NETSCOPE_AUTH_PASSWORD_HASH':generate_password_hash('docker-test-password',method='scrypt')}
# docker run --env-file treats values literally, unlike Compose's single-quoted env files.
(root/'env').write_text(''.join(f'{k}={v}\n' for k,v in data.items()))
(root/'runtime'/'agents.json').write_text('{}')
PY
docker run -d --name netscope-smoke --network host --user 10001:10001 --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=32m --mount "type=bind,source=$tmp/runtime,target=/etc/netscope,readonly" --env-file "$tmp/env" netscope:smoke
for i in {1..20}; do
  if curl --fail --silent http://127.0.0.1:18081/health >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:18081/health >/dev/null
[[ "$(curl --silent -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/api/status)" == 401 ]]
[[ "$(docker exec netscope-smoke id -u)" == 10001 ]]
docker exec netscope-smoke python -c "from pathlib import Path; assert not Path('/host').exists(); assert Path('/etc/netscope/agents.json').read_text()=='{}'"
echo 'Docker unprivileged/read-only startup and auth checks passed.'
