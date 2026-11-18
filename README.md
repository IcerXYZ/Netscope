# NetScope

**A friendly central dashboard for monitoring multiple Debian/Ubuntu machines on one network.**

NetScope has three setup modes:

- **Single host:** monitor just this machine.
- **Central server:** one dashboard collects reports from all your agents.
- **Agent:** a lightweight monitor sends this machine's statistics to your central server every five seconds.

The dashboard shows CPU, RAM, disk, uptime, IP address, system details, network interfaces, traffic rates and process metadata. NetScope can be installed directly on Debian/Ubuntu or run as a Docker Compose service. It is read-only and does not capture packet payloads or save PCAP files.

## Quick install

On each Debian/Ubuntu machine:

\`\`\`bash
sudo apt update
sudo apt install -y git
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
sudo bash install.sh
\`\`\`

The animated installer guides you through setup. It shows a compact rotating progress indicator while installing; detailed output is saved to \`/var/log/netscope-install.log\`.

## Set up one dashboard for your network

### 1. Install the central server

On the machine that will host the dashboard, run the installer and choose:

\`2) Central server\`

After installation, create a separate enrollment token for every machine with `sudo netscope-agent-token add proxmox-node-01`. The token is displayed once; copy it before closing the terminal.

Open the dashboard at \`http://CENTRAL-SERVER-IP:8080\`.

### 2. Install agents on the other machines

On every Debian/Ubuntu machine you want to monitor:

1. Clone the same repository and run \`sudo bash install.sh\`.
2. Choose \`3) Agent\`.
3. Enter the central dashboard URL, for example \`http://192.168.6.20:8080\`.
4. Enter the enrollment token from the central server.

Agents send their telemetry to the central server every five seconds. They appear automatically in **Whole network**; no static IP list or manual node JSON is required. Each agent also reports its own local socket, listening-port and SSH authentication metadata, which the central dashboard combines for fleet-wide tables. Give the central server a stable LAN IP or DHCP reservation so agents can always find it.

### 3. Network and firewall

During installation, NetScope asks whether you want it to configure UFW. If you answer **yes**, it installs UFW if needed, adds an SSH rule for TCP **22** and (for LAN mode) a dashboard rule for the selected TCP port, scoped to the detected private subnet, then enables the firewall. It does not add a TCP 80 rule. Check that SSH really uses port 22 before enabling UFW, especially on remote servers. If you answer **no**, it leaves your firewall unchanged. Check that SSH really uses port 22 before enabling UFW, especially on remote servers.

- The central server must accept TCP connections on the dashboard port (default \`8080\`) from your trusted LAN.
- Agents make outbound connections to the central server; they do not need inbound firewall ports opened.
- Agent installations bind their local service to \`127.0.0.1\` by default. The central server listens on the configured address (default \`0.0.0.0\`).
- Use a trusted LAN or VPN. Do not expose the dashboard to the public internet. Dashboard login is optional and can be enabled in the installer. When enabled, use the configured username/password. NetScope binds to a private LAN IPv4 address by default, not all interfaces; localhost-only mode is also available. Do not forward the dashboard port from your router.
- Each agent uses its own unique token. On the central server, create one with `netscope-agent-token add proxmox-node-01`, then enter that ID and token when installing the corresponding agent. Revoke it with `netscope-agent-token revoke proxmox-node-01`. Tokens are stored as password hashes on the central server and the raw token is shown only once. HTTP is currently used, so only use a trusted LAN or VPN; HTTPS support is planned.

After upgrading an existing central server, create a unique token for every agent and update each agent's `/etc/netscope.env` with its `NETSCOPE_AGENT_ID` and new `NETSCOPE_AGENT_TOKEN`, then restart that agent. The old shared token is no longer accepted. An agent is marked offline after 25 seconds without a heartbeat. Reports are held in the central server's memory; after a central-server restart, agents automatically reconnect and repopulate the list. This is a live monitoring view, not historical storage or high availability.

## Docker deployment

Docker is supported on **Linux hosts**. The Compose setup uses host networking and the host PID namespace so NetScope can read the real machine's network interfaces and process metadata. A read-only host-root mount is used for host disk capacity. The container filesystem itself stays read-only, all Linux capabilities are dropped, and privilege escalation is disabled.

### Central server or single host

Install Docker Engine and the Docker Compose plugin first. Then:

```bash
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
cp .env.example .env
nano .env
docker compose up -d --build
```

For a single host, keep `NETSCOPE_ROLE=single`. For the central dashboard, set `NETSCOPE_ROLE=server`, set NETSCOPE_BIND to the central machine's private LAN IPv4 address (not 0.0.0.0), enable dashboard authentication, set a long random NETSCOPE_SECRET_KEY, and configure NETSCOPE_AUTH_USERNAME plus NETSCOPE_AUTH_PASSWORD_HASH. Generate the hash after the image is built with `docker compose run --rm --no-deps netscope python -c 'from werkzeug.security import generate_password_hash; print(generate_password_hash(input(), method="scrypt"))'`, then paste it into `.env`. The Compose file keeps the agent-token registry in the persistent, project-local `./data` directory; you do not need to create the file manually. Open http://SERVER-LAN-IP:8080 (or your selected port). After startup, create an individual token with `docker compose exec netscope netscope-agent-token add proxmox-node-01`; copy the token shown once into that agent's `.env`. The registry contains password hashes, not raw agent tokens.

### Add a Docker agent on another Linux machine

On each monitored machine, clone the repository and create its own `.env`:

```ini
NETSCOPE_ROLE=agent
NETSCOPE_PORT=8080
NETSCOPE_BIND=127.0.0.1
NETSCOPE_SERVER_URL=http://SERVER-IP:8080
NETSCOPE_AGENT_ID=proxmox-node-01
NETSCOPE_AGENT_TOKEN=PASTE_THIS_AGENTS_UNIQUE_TOKEN
```

Then run:

```bash
docker compose up -d --build
```

The agent reports to the central server every five seconds. It does not need an inbound firewall port. Keep the token secret.

### Docker management

```bash
docker compose ps
docker compose logs -f
docker compose restart
docker compose pull
docker compose up -d --build
docker compose down
```

Edit `.env` and recreate the container after changing its settings.

**Docker notes:** This Compose file is intended for Linux Docker hosts. It uses `network_mode: host`, so Compose port mappings are not used; the dashboard listens directly on the host at the configured port. Permit that TCP port on your LAN firewall for a central server. Docker Desktop on Windows/macOS does not provide the same host network/PID visibility, so full host telemetry is not guaranteed there. The read-only `/:/host` mount exposes host files to the container for disk reporting; only run this trusted image and do not publish it to an untrusted registry. Dashboard login is optional; enable it in `.env` and configure a password hash before starting the container.

### Agent token commands

Run these on the central server. Each agent must have its own ID and token; the raw token is displayed once when created.

```bash
sudo netscope-agent-token add debian-node-01
sudo netscope-agent-token list
sudo netscope-agent-token revoke debian-node-01
```

Copy the one-time token into the agent configuration at `/etc/netscope.env`:

```ini
NETSCOPE_ROLE=agent
NETSCOPE_SERVER_URL=http://CENTRAL-SERVER-IP:8080
NETSCOPE_AGENT_ID=debian-node-01
NETSCOPE_AGENT_TOKEN=PASTE_THE_ONE_TIME_TOKEN_HERE
```

Then restart the agent with `sudo systemctl restart netscope`. For Docker, run the create/list/revoke command inside the central container, for example `docker compose exec netscope netscope-agent-token add debian-node-01`.

## Dashboard

On the **Traffic** page, use **Chart scope** to view a single server or combined network throughput. The server list shows each online server download and upload rate; selecting a server updates the chart and totals. The Network fleet page shows CPU, RAM, disk, uptime and connection status.

## Discord alerts

The installer keeps an existing Discord webhook in \`/etc/netscope.env\`. To configure one manually:

\`\`\`ini
NETSCOPE_DISCORD_WEBHOOK=https://discord.com/api/webhooks/REPLACE_ME
\`\`\`

Restart the service after changing the file:

\`\`\`bash
sudo systemctl restart netscope
\`\`\`

Alerts are rate-limited. CPU, RAM or disk at 90% triggers a resource alert. Central servers can also notify when an agent stops reporting.

**Never put a real webhook or enrollment token in GitHub, screenshots or chat messages.**

## Useful commands

\`\`\`bash
sudo systemctl status netscope
sudo journalctl -u netscope -f
sudo systemctl restart netscope
\`\`\`

Update an existing installation:

\`\`\`bash
cd ~/Netscope
bash update.sh --host
\`\`\`

The installer preserves existing settings (including the Discord webhook and agent token registry) when updating an existing installation.

To update a Docker deployment from the checked-out repository, run this instead:

```bash
cd ~/Netscope
bash update.sh --docker
```

This fast-forward pulls the official `main` branch and rebuilds using the repository `Dockerfile` and `compose.yaml`. The project `.env` file and `./data` volume remain in place.


Remove NetScope:

\`\`\`bash
cd ~/Netscope
sudo bash uninstall.sh
\`\`\`

## Configuration

Private settings are stored in \`/etc/netscope.env\` with root-only permissions.

- \`NETSCOPE_ROLE=single|server|agent\`
- \`NETSCOPE_AGENT_TOKEN\` is a unique token set only on its matching agent
- \`NETSCOPE_SERVER_URL\` set on agents
- \`NETSCOPE_DISCORD_WEBHOOK\` optional private Discord webhook

## Troubleshooting

Installer details:

\`\`\`bash
sudo tail -n 80 /var/log/netscope-install.log
\`\`\`

Service logs:

\`\`\`bash
sudo journalctl -u netscope -n 100 --no-pager
\`\`\`

If an agent does not appear, verify the central server URL and token, then from the agent check that the central dashboard responds:

\`\`\`bash
curl -I http://CENTRAL-SERVER-IP:8080/health
\`\`\`

**NetScope** · One dashboard. Your whole network.


## Dashboard preferences

Open **Settings** in the left navigation to choose a 3, 5, 10 or 15 second refresh interval, enable compact spacing, or reduce animations. These preferences are stored only in that browser and do not add background services or database load. NetScope uses lightweight vanilla JavaScript and system fonts; it does not load external font libraries or charting frameworks.


## Network intelligence pages

The dark-first dashboard now has dedicated pages for:

- **Overview:** host identity, CPU/RAM/disk, uptime and current traffic.
- **Traffic:** interface rates, packet counters, errors and drops.
- **Connections:** local TCP/UDP socket metadata with local source address/port, remote destination address/port, protocol, state and PID.
- **Ports & Services:** local listening sockets and frequently observed destination ports from the current socket sample.
- **Security events:** failed SSH authentication events parsed from the local system journal or `auth.log`, including source IP, source port, attempted username and SSH target port 22.
- **Network fleet:** connected central/agent machines.
- **Settings:** dark/light theme, refresh interval, compact layout and reduced motion.

The service account is added to the `adm` and (when present) `systemd-journal` groups so it can read authentication log entries without running the web server as root. Restart NetScope after upgrading so the new group membership takes effect.

### Important visibility limits

Connection and listening-port information is collected from the Linux host's local socket table; it is **not** a complete record of every device-to-device flow on the LAN. Failed SSH events come only from logs readable by the NetScope service account. The frequent-port list is a live sample, not a historical frequency database. Socket visibility may be incomplete for containers or other isolated network namespaces.

For network-wide source-to-destination visibility (including traffic between two other machines), connect a switch SPAN/mirror port or network TAP to a dedicated passive sensor. The current connection pages do not claim to provide that network-wide packet view, and no packet payloads are captured or stored.


## Security model

- The installer defaults to binding the dashboard to a detected private LAN IPv4 address, or offers localhost-only mode. It never defaults to `0.0.0.0`.
- Optional dashboard authentication uses a password hash, HTTP-only SameSite session cookies, an eight-hour session lifetime and login throttling. The installer recommends enabling it.
- Agent report credentials are unique per agent. The central server stores password hashes in `/etc/netscope-agent-tokens.json` (root-owned, readable only by the NetScope service group; mode 0640). Manage them with `netscope-agent-token add <id>`, `list`, and `revoke <id>`.
- API requests are size-limited; responses include restrictive browser security headers. Agent reports are validated and require a registered agent ID and matching token.
- No remote command execution endpoint exists. Monitoring remains read-only.
- LAN binding is not a substitute for firewalling. If you enable UFW, the installer scopes SSH and NetScope rules to the detected private subnet. Do not create router port forwards for NetScope.
- HTTPS is not included yet. Credentials and telemetry cross the LAN in plaintext; use a trusted switched network or VPN until TLS support is added.
- The dashboard reports local interface counters and socket metadata. It does not capture all packets on a switched LAN. Network-wide visibility between other machines still requires switch port mirroring or a TAP.


## Change the Linux service port

The native systemd service reads its bind address and port from `/etc/netscope.env` at every start. This applies to single hosts, central servers and agents.

```ini
NETSCOPE_BIND=127.0.0.1
NETSCOPE_PORT=10101
```

After editing, run `sudo systemctl restart netscope`. Use a private LAN bind address for a central dashboard that agents must reach. On each agent, `NETSCOPE_SERVER_URL=http://CENTRAL-IP:10101` selects the central destination; `NETSCOPE_PORT` selects only that agent local listening port. These ports can differ. Agents report outbound and need no inbound firewall rule.

Upgrade older installs with `git pull --ff-only origin main` and `bash update.sh --host` to replace their old fixed-port systemd unit first. Changing the environment alone cannot override an old fixed `ExecStart`.


## Automated checks

Pull requests run the Python regression suite, JavaScript and shell syntax checks, Debian package build, Chromium dashboard interactions, a Docker central-server/agent enrollment test with different custom ports, and a native Ubuntu/systemd installation test. The native test also changes the configured port and verifies that unattended reinstall preserves the role and login credentials. These run on disposable CI machines; they do not access your servers.

The Network fleet page includes first-agent setup instructions and an expandable checklist for agents that are offline or have not appeared. Native service settings are in `/etc/netscope.env`; Docker settings are in the project `.env`.
