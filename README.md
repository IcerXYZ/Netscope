# NetScope

**A friendly central dashboard for monitoring multiple Debian/Ubuntu machines on one network.**

NetScope has three setup modes:

- **Single host:** monitor just this machine.
- **Central server:** one dashboard collects reports from all your agents.
- **Agent:** a lightweight monitor sends this machine's statistics to your central server every five seconds.

The dashboard shows CPU, RAM, disk, uptime, IP address, system details, network interfaces, traffic rates and process metadata. It is read-only and does not capture packet payloads or save PCAP files.

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

The installer creates a secure random enrollment token and displays it. Copy this token; you will need it when installing each agent.

Open the dashboard at \`http://CENTRAL-SERVER-IP:8080\`.

### 2. Install agents on the other machines

On every Debian/Ubuntu machine you want to monitor:

1. Clone the same repository and run \`sudo bash install.sh\`.
2. Choose \`3) Agent\`.
3. Enter the central dashboard URL, for example \`http://192.168.6.20:8080\`.
4. Enter the enrollment token from the central server.

Agents send their telemetry to the central server every five seconds. They appear automatically in **Whole network**; no static IP list or manual node JSON is required. Give the central server a stable LAN IP or DHCP reservation so agents can always find it.

### 3. Network and firewall

- The central server must accept TCP connections on the dashboard port (default \`8080\`) from your trusted LAN.
- Agents make outbound connections to the central server; they do not need inbound firewall ports opened.
- Agent installations bind their local service to \`127.0.0.1\` by default. The central server listens on the configured address (default \`0.0.0.0\`).
- Use a trusted LAN or VPN. Do not expose the dashboard to the public internet. The dashboard does not have user accounts or built-in login.
- The enrollment token is a shared secret. Keep it private and use HTTPS or a trusted management network when crossing untrusted networks.

An agent is marked offline after 25 seconds without a heartbeat. Reports are held in the central server's memory; after a central-server restart, agents automatically reconnect and repopulate the list. This is a live monitoring view, not historical storage or high availability.

## Dashboard

Choose **This machine** to view the central server's own detailed telemetry. Choose **Whole network** to view all connected machines, online status, IP, CPU, RAM, disk, uptime and combined network throughput.

## Discord alerts

The installer keeps an existing Discord webhook in \`/etc/netscope-pro.env\`. To configure one manually:

\`\`\`ini
NETSCOPE_DISCORD_WEBHOOK=https://discord.com/api/webhooks/REPLACE_ME
\`\`\`

Restart the service after changing the file:

\`\`\`bash
sudo systemctl restart netscope-pro
\`\`\`

Alerts are rate-limited. CPU, RAM or disk at 90% triggers a resource alert. Central servers can also notify when an agent stops reporting.

**Never put a real webhook or enrollment token in GitHub, screenshots or chat messages.**

## Useful commands

\`\`\`bash
sudo systemctl status netscope-pro
sudo journalctl -u netscope-pro -f
sudo systemctl restart netscope-pro
\`\`\`

Update an existing installation:

\`\`\`bash
cd ~/Netscope
git pull origin main
sudo bash install.sh
\`\`\`

The installer preserves the existing Discord webhook and keeps the central server's enrollment token when updating it.

Remove NetScope:

\`\`\`bash
cd ~/Netscope
sudo bash uninstall.sh
\`\`\`

## Configuration

Private settings are stored in \`/etc/netscope-pro.env\` with root-only permissions.

- \`NETSCOPE_ROLE=single|server|agent\`
- \`NETSCOPE_AGENT_TOKEN\` shared by the central server and its agents
- \`NETSCOPE_SERVER_URL\` set on agents
- \`NETSCOPE_DISCORD_WEBHOOK\` optional private Discord webhook

## Troubleshooting

Installer details:

\`\`\`bash
sudo tail -n 80 /var/log/netscope-install.log
\`\`\`

Service logs:

\`\`\`bash
sudo journalctl -u netscope-pro -n 100 --no-pager
\`\`\`

If an agent does not appear, verify the central server URL and token, then from the agent check that the central dashboard responds:

\`\`\`bash
curl -I http://CENTRAL-SERVER-IP:8080/health
\`\`\`

**NetScope** · One dashboard. Your whole network.
