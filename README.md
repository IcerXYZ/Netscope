# NetScope Pro

NetScope Pro Debian package and APT repository scaffold.

> **Current status:** this change adds the Debian packaging and signed APT publishing foundation only. It does not yet implement the monitoring agent, dashboard, SSH event collection, Fail2ban integration, or Proxmox traffic mirroring.

## Build locally

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y dpkg-dev
bash packaging/build-deb.sh
```

The package is written to `dist/netscope-pro_0.1.0_all.deb`.

## Publish the signed APT repository

1. Enable **GitHub Pages** for this repository, using **GitHub Actions** as the source.
2. Create a dedicated GPG signing key. Export its ASCII-armored private key and add it as the Actions secret `APT_SIGNING_KEY`. Add its passphrase as `APT_SIGNING_PASSPHRASE`.
3. Push a version tag, for example `v0.1.0`. The workflow builds the package, creates APT metadata, signs `InRelease` and `Release.gpg`, and deploys the repository.
4. Check the exact Pages URL in repository Settings → Pages.

## Install

Replace `OWNER.github.io/REPOSITORY` with the Pages URL shown in Settings → Pages:

```bash
curl -fsSL https://OWNER.github.io/REPOSITORY/apt/public.key | sudo gpg --dearmor -o /usr/share/keyrings/netscope-pro-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/netscope-pro-archive-keyring.gpg] https://OWNER.github.io/REPOSITORY/apt stable main" | sudo tee /etc/apt/sources.list.d/netscope-pro.list
sudo apt update
sudo apt install netscope-pro
```

## Security note

APT verifies package hashes through the signed repository metadata. Protect the signing key and rotate it if exposed.

**GitHub Pages is public hosting.** A private source repository does not make the published APT files private. If packages must only be available to authorized customers, use an authenticated package host instead.

## Package status

The current `netscope-pro` command is only a packaging placeholder. The monitoring services and UI must be implemented before this should be presented as a working NetScope Pro product.
