# NetScope Pro

Read-only host and network monitoring for Debian/Ubuntu VMs.

## Install
```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
sudo bash install.sh
```
The wizard asks for the dashboard port and listen address, prints the NetScope logo, creates the service account, venv, systemd service and shell login banner. Existing `/etc/netscope-pro.env` settings are preserved. During interactive installation you can optionally enter a Discord webhook; it is stored locally with root-only permissions and never committed to Git.

Open `http://VM-IP:8080`. The dashboard shows CPU, RAM, disk, uptime, boot time, primary IPv4, interface IP/link state/speed, live bandwidth, packet/error/drop counters, system details and top processes.

## Single / Cluster mode
Use **Single** for this VM or **Cluster** to view this VM plus configured remote NetScope agents. On the central node, edit:
```bash
sudo nano /etc/netscope-pro.env
```
Add remote agents as a JSON array:
```ini
NETSCOPE_NODES=[{"name":"pve-node-2","url":"http://192.168.6.32:8080"},{"name":"pve-node-3","url":"http://192.168.6.33:8080"}]
```
Each remote node must run NetScope Pro and allow the central node to reach `/api/status`. Restart with `sudo systemctl restart netscope-pro`. This is a lightweight polling dashboard, not a distributed database or HA controller.

## Discord alerts
Set `NETSCOPE_DISCORD_WEBHOOK` in `/etc/netscope-pro.env`. Rate-limited alerts are sent when local CPU, RAM or disk reaches 90%, or a configured cluster node is unreachable. Treat the webhook as a secret; never commit it or share it in screenshots.

## Management
```bash
sudo systemctl status netscope-pro
sudo journalctl -u netscope-pro -f
sudo systemctl restart netscope-pro
```
Update: `git pull origin main && sudo bash install.sh`
Uninstall: `sudo bash uninstall.sh`

## Security
There is no built-in authentication. Restrict the dashboard to a trusted LAN/VPN or use an authenticated reverse proxy; never expose it directly to the public internet. Use HTTPS or a trusted management network for remote cluster nodes. NetScope reads OS counters and process metadata; it does not capture packet payloads.
