# NetScope Pro

**A clean, lightweight dashboard for monitoring Linux hosts and small server clusters.**

NetScope Pro gives you a quick overview of CPU, memory, storage, uptime, IP addresses, network traffic, interfaces and running processes. It is designed for Debian and Ubuntu VMs and uses read-only system telemetry.

## Quick install

Run these commands on your Debian/Ubuntu VM:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
sudo bash install.sh
```

The guided installer:
- Shows the NetScope shell logo.
- Lets you choose the dashboard port and listen address.
- Optionally configures a Discord webhook without displaying the secret.
- Creates a dedicated service account and Python virtual environment.
- Installs and starts the systemd service.
- Adds the NetScope logo to interactive shell logins.

When installation finishes, open the URL printed by the installer. The default is `http://VM-IP:8080`.

## Dashboard guide

The dashboard refreshes automatically every three seconds.

| Section | What it shows |
| --- | --- |
| Resource usage | CPU, RAM, root disk and uptime |
| Host identity | Primary IPv4, hostname, boot time and OS |
| Traffic overview | Live download/upload rates and a short traffic history |
| System details | Kernel, CPU count/frequency, load average and swap |
| Network totals | Bytes, packets, errors and drops |
| Network interfaces | Per-interface IPv4, link state, speed and traffic; searchable |
| Top processes | The eight processes using the most memory |

Use the **Single host** button for the current server. Use **Cluster** to see the current server and any remote agents configured below. The IP and hostname copy buttons copy those values to your clipboard.

## Configure a cluster

Install NetScope Pro on each machine you want to monitor. On the central dashboard server, edit:

```bash
sudo nano /etc/netscope-pro.env
```

Add a JSON array of remote nodes. Replace the sample names and addresses with the real management IPs:

```ini
NETSCOPE_NODES=[{"name":"pve-node-2","url":"http://192.168.6.32:8080"},{"name":"pve-node-3","url":"http://192.168.6.33:8080"}]
```

You can start from [netscope-pro.env.example](netscope-pro.env.example). Then restart the central service:

```bash
sudo systemctl restart netscope-pro
```

The central server must be able to reach each remote node's `/api/status` endpoint. Cluster mode is a lightweight polling overview, not a distributed database, failover controller or full Proxmox manager.

## Discord notifications

The installer can ask for a Discord webhook. You can also configure it manually in `/etc/netscope-pro.env`:

```ini
NETSCOPE_DISCORD_WEBHOOK=https://discord.com/api/webhooks/REPLACE_ME
```

Restart NetScope after changing the file. Rate-limited notifications are sent when local CPU, RAM or disk reaches 90%, or when a configured cluster node cannot be reached.

**Keep your webhook private.** The real webhook belongs only in `/etc/netscope-pro.env`, never in GitHub, screenshots or chat messages. The example file contains no real secret.

## Service commands

```bash
# Check service status
sudo systemctl status netscope-pro

# Follow live logs
sudo journalctl -u netscope-pro -f

# Restart the service
sudo systemctl restart netscope-pro

# Update to the latest GitHub version
cd ~/Netscope
git pull origin main
sudo bash install.sh

# Remove NetScope Pro
cd ~/Netscope
sudo bash uninstall.sh
```

The installer keeps the existing private configuration file and shell login logo when updating.

## Security notes

- The dashboard does not include user accounts or built-in authentication.
- Do not expose the dashboard directly to the public internet. Restrict its port to a trusted LAN/VPN or put it behind an authenticated reverse proxy.
- Use HTTPS or a trusted management network when connecting remote cluster agents.
- The service runs as a dedicated unprivileged `netscope` user.
- NetScope reads operating-system counters and process metadata. It does not record packet payloads or save PCAP files.

## Troubleshooting

**Dashboard does not open**
```bash
sudo systemctl status netscope-pro
sudo journalctl -u netscope-pro -n 80 --no-pager
```

Check that the VM IP and configured port are correct and that your firewall allows access from your trusted management network.

**A cluster node appears offline**

From the central VM, check that the node's dashboard is reachable:

```bash
curl http://192.168.6.32:8080/api/status
```

Check the node IP, port, service status and firewall rules.

**No IP address is shown**

Check that the VM network interface is connected and has an IPv4 address:

```bash
ip -br address
```

---

**NetScope Pro** · Simple visibility for your infrastructure.
