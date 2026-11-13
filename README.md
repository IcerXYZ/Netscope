# NetScope
Read-only host and fleet monitoring for Debian/Ubuntu, with authenticated HTTPS access on a private network.

## Security and supported deployment
- All dashboards require login. Missing credentials or invalid security settings prevent startup.
- Default bind: 127.0.0.1. For LAN access, choose a specific private IP and supply a TLS certificate/key. All-interface and public-address binds are rejected.
- Use a certificate trusted by browsers and agents, with the actual hostname/IP in its Subject Alternative Name. Do not bypass certificate warnings or disable verification.
- Allow the chosen port only from intended management clients/subnets using your firewall. No router port forwarding.
- The web process runs as a restricted account. Sessions are server-side, expire absolutely after eight hours, and are revoked on logout/password change/restart.
- The supported server has **one worker**. Up to 256 enrolled agents, 600 report requests/minute globally, 30/minute per source address, 20/minute per agent. Shared NAT sources must fit those limits.
- HTTP is permitted only on loopback for local administration. For LAN use, HTTPS is mandatory.
- Exact allowed hostnames are configured with NETSCOPE_TRUSTED_HOSTS. Reverse-proxy forwarded headers are deliberately not trusted; the supported deployment terminates TLS directly in Gunicorn.
- Agent mode runs only the outbound collector, not a dashboard listener. Reports use HTTPS and never follow redirects.
- This is not a packet sniffer or a record of all switched-network traffic.

## Install on Debian/Ubuntu
Download/review this source, then run:

```bash
sudo bash install.sh
```

The installer asks for confirmation before changing the machine, prepares a versioned environment, validates settings, and explicitly restarts the service. A failed activation restores the previous code/configuration. Configuration is root-only at /etc/netscope.env; old releases/backups remain under /opt/netscope-releases for recovery. They contain sensitive configuration: keep root-only and remove obsolete backups deliberately.

For LAN mode, provision your trusted certificate before setup, using an existing private/internal CA or your organization's certificate service:

```bash
sudo groupadd --system --force netscope
sudo install -d -o root -g netscope -m 0750 /etc/netscope
sudo install -o root -g netscope -m 0644 /path/to/fullchain.crt /etc/netscope/tls.crt
sudo install -o root -g netscope -m 0640 /path/to/private.key /etc/netscope/tls.key
sudo bash install.sh
```

Choose server or single, enter the machine's private bind IP, the certificate paths, the exact DNS name clients use, and a password of at least 12 characters. Open https://YOUR-CONFIGURED-HOST:8080. A private CA must be trusted on each accessing device. Restart after certificate renewal.

The installer does not change firewall rules or assume your SSH port. Add a narrowly scoped inbound rule appropriate to your firewall and verify remote management remains available.

## Enroll agents
On the central server:

```bash
sudo netscope-agent-token add node-01
```

Copy the token shown once. On the monitored machine run the installer, select agent, and supply its unique ID, token, central HTTPS URL, and a CA certificate path if the server uses a private CA. Keep tokens private.

```bash
sudo netscope-agent-token list
sudo netscope-agent-token revoke node-01
```

The registry stores SHA-256 digests of randomly generated 288-bit tokens. Passwords use scrypt. Revoked records are removed from the fleet on its next request; offline reports expire after five minutes. Agent display identity comes from its registered ID.

## Upgrade and migration
Back up /etc/netscope.env and any existing registry securely. Run the new installer interactively the first time. Old shared/scrypt agent credentials are intentionally rejected: enroll fresh tokens for each agent and update its settings. Legacy NETSCOPE_NODES polling is removed.

A previous HTTP LAN configuration requires TLS before it can start. Replace example/weak session secrets using configure.py; interactive setup generates a fresh random secret. Existing passwords may be preserved if their hashes meet the supported format. Valid unattended upgrades preserve settings:

```bash
sudo bash install.sh --yes
```

This requires an already-valid /etc/netscope.env. It never silently turns authentication off. All clients must sign in again after restart.

## Docker on Linux
The container runs as UID/GID 10001 with no Linux capabilities and a read-only filesystem. It uses host networking for interface counters but **does not mount the host root or share its PID namespace**. Process, disk and SSH-log views therefore describe container-accessible resources and may be incomplete. Use the native service when full authorized host telemetry is needed.

Create a local Python virtual environment for configuration/token administration:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
sudo install -d -o root -g 10001 -m 0750 runtime
sudo install -o root -g 10001 -m 0644 /path/to/fullchain.crt runtime/tls.crt
sudo install -o root -g 10001 -m 0640 /path/to/private.key runtime/tls.key
sudo .venv/bin/python agent_tokens.py list --file runtime/agents.json --group-id 10001
sudo sh -c 'test -f runtime/agents.json || printf "{}\n" > runtime/agents.json'
sudo chown root:10001 runtime/agents.json
sudo chmod 0640 runtime/agents.json
sudo .venv/bin/python configure.py --file .env --docker
sudo docker compose up -d --build
```

Inside the container use certificate paths /etc/netscope/tls.crt and /etc/netscope/tls.key. For private-CA agents place ca.crt in runtime and select /etc/netscope/ca.crt. The configuration generator validates these against ./runtime before saving. Compose reads single-quoted values literally, preserving dollar signs in password hashes.

Manage Docker credentials **on the host**, not inside the read-only container:

```bash
sudo .venv/bin/python agent_tokens.py add node-01 --file runtime/agents.json --group-id 10001
sudo .venv/bin/python agent_tokens.py revoke node-01 --file runtime/agents.json --group-id 10001
```

A directory mount permits atomic registry replacement; the serving container has read-only access. Recreate containers after editing .env. Do not use plain docker run --env-file with the generated quoted file: Docker CLI and Compose parse it differently.

## Configuration and limits
Use configure.py for settings; do not source configuration into a shell. Optional NETSCOPE_DISCORD_WEBHOOK accepts only a discord.com HTTPS webhook. Webhook failures log a generic error. Outbound clients use normal certificate verification, optional NETSCOPE_CA_FILE, no proxies, and no redirects.

Network/log collection is bounded and cached. Frontend text is rendered as text, not HTML. Malformed agent telemetry is rejected and faulty nodes are isolated in rendering. A successful review is not a guarantee against every future vulnerability; apply dependency updates deliberately.

## Maintenance
```bash
sudo systemctl status netscope
sudo journalctl -u netscope -n 80
sudo systemctl restart netscope
sudo bash uninstall.sh
# Explicitly remove stored configuration and release backups:
sudo bash uninstall.sh --purge
```

Uninstall does not change firewall rules or revoke a machine's token on another central server. Remove obsolete rules/revoke that token separately.

The Debian package includes the application and setup files; it does not silently enroll/start a service during package installation. Run sudo netscope setup afterward.

## Development and validation
```bash
python -m pip install --require-hashes -r requirements.lock
python -m unittest discover -s tests -v
node tests/frontend.cjs .
bash -n install.sh uninstall.sh tests/*.sh packaging/build-deb.sh
```

GitHub checks Python 3.12/3.14, dependencies, Linux clean installation/TLS upgrades, and the restricted Docker deployment. The APT publishing workflow depends on those checks. Tests/linux_smoke.sh changes an ephemeral Linux runner; do not run it on a real NetScope machine.

requirements.lock pins application dependencies and distribution hashes. Update it deliberately together with requirements.txt, rerun pip-audit and tests, and rebuild. GitHub actions are pinned to commit IDs.

