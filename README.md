# NetScope Pro

A read-only host and network monitoring dashboard for Debian/Ubuntu VMs.

## Interactive VM installer

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
sudo bash install.sh
```

The wizard displays the NetScope logo, asks for a TCP port and listen address, shows a summary and asks for confirmation. For unattended setup use `sudo bash install.sh --yes` (port 8080, listen on 0.0.0.0).

When complete, open `http://VM-IP:8080` (or the configured port). The installer creates a restricted service account, Python virtual environment, systemd service and standard NetScope shell login banner. It does not change network configuration, routes, firewall rules or Proxmox bridges.

## Dashboard data

- CPU utilization, logical/physical core counts, frequency and load averages
- RAM, swap, root filesystem and uptime
- Rolling 60-sample live RX/TX bandwidth graph
- Per-interface IPv4, link state, speed, MTU, byte/packet counters, errors and drops
- Aggregate network totals and top processes by memory
- Hostname, OS and kernel information
- JSON health endpoint at `/health`

## Service management

```bash
sudo systemctl status netscope-pro
sudo journalctl -u netscope-pro -f
sudo systemctl restart netscope-pro
```

Update an existing install: `git pull && sudo bash install.sh`.
Uninstall: `sudo bash uninstall.sh` from the cloned repository.

## Security and scope

There is no built-in authentication. Keep the dashboard on a trusted LAN/VPN or behind an authenticated reverse proxy; never expose its port directly to the public internet. The agent reads OS counters and process metadata. It does not implement packet capture/deep inspection, SSH login monitoring, Fail2ban integration, multi-node management or Proxmox traffic mirroring.

The `packaging/` directory and GitHub Actions retain the Debian package and signed APT repository scaffold; the VM wizard is the supported installation path for this version.
