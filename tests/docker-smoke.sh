#!/usr/bin/env bash
set -euo pipefail
cleanup() {
  docker rm -f netscope-ci-agent >/dev/null 2>&1 || true
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
export NETSCOPE_AUTH_ENABLED=false NETSCOPE_BIND=127.0.0.1 NETSCOPE_PORT=10101 NETSCOPE_ROLE=server
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
curl --fail --silent http://127.0.0.1:10101/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
token_output="$(docker compose exec -T netscope netscope-agent-token add ci-agent)"
agent_token="$(printf '%s\n' "$token_output" | sed -n '3p')"
test -n "$agent_token"
docker run -d --name netscope-ci-agent --network host \
  -e NETSCOPE_ROLE=agent -e NETSCOPE_BIND=127.0.0.1 -e NETSCOPE_PORT=10102 \
  -e NETSCOPE_HOST_ROOT=/ -e NETSCOPE_AGENT_ID=ci-agent \
  -e NETSCOPE_SERVER_URL=http://127.0.0.1:10101 \
  -e NETSCOPE_AGENT_TOKEN="$agent_token" netscope:latest >/dev/null
unset agent_token token_output
connected=0
for attempt in $(seq 1 20); do
  if curl --fail --silent http://127.0.0.1:10101/api/cluster |
    python3 -c 'import json,sys; assert any(n.get("agent_id")=="ci-agent" and n["online"] for n in json.load(sys.stdin)["nodes"])'; then
    connected=1
    break
  fi
  sleep 2
done
test "$connected" = 1
curl --fail --silent http://127.0.0.1:10102/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
docker rm -f netscope-ci-agent >/dev/null
export NETSCOPE_PORT=10103
docker compose up -d --wait --wait-timeout 120
curl --fail --silent http://127.0.0.1:10103/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
docker compose exec -T netscope netscope-agent-token list | grep -q ci-agent
echo "PASS custom server port, independent agent port, enrollment, port change and persistent token registry"
