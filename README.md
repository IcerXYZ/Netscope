# NetScope Pro

NetScope Pro is a lightweight Debian/Ubuntu VM dashboard for basic system and network-interface telemetry.

## Quick install (Debian 12/13 or Ubuntu)

Clone the private repository on your VM (Git must be installed):

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/IcerXYZ/Netscope.git
cd Netscope
sudo bash install.sh
```

Open the URL printed by the installer, normally:

```
http://VM-IP:8080
```

The installer installs Python dependencies in an isolated virtual environment, creates a dedicated `netscope` service account, installs a systemd service, enables it at boot, and starts it. It does not change the VM's IP address, routes, firewall, Proxmox bridges, or network interfaces.

## Manage the service

```bash
sudo systemctl status netscope-pro
sudo journalctl -u netscope-pro -f
sudo systemctl restart netscope-pro
```

Uninstall:

```bash
sudo bash uninstall.sh
```

## Current features

- CPU and memory utilization
- VM uptime and hostname
- Per-interface receive/transmit throughput
- Auto-refreshing web dashboard
- systemd startup and restart on failure
- Read-only network counters; no packet capture

## Important limitations

This is the first installable baseline, not the complete planned NetScope Pro feature set. SSH login event monitoring, Fail2ban integration, multi-node management, packet inspection, and Proxmox traffic mirroring are not included yet.

The dashboard currently has no built-in authentication and listens on all VM interfaces at port 8080 by default. Keep it on a trusted LAN or access it through a VPN/authenticated reverse proxy. Do not expose port 8080 directly to the public internet.

## Debian package / APT repository

The `packaging/` directory and GitHub Actions workflows retain the Debian package and signed APT repository scaffold. The quick VM installer above is the recommended way to try this initial dashboard while APT publishing is being configured.
