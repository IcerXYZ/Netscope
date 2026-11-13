#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-0.2.0}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([~+.-][A-Za-z0-9.]+)?$ ]] || { echo "Invalid version"; exit 1; }
PKG="$(mktemp -d)"
trap 'rm -rf -- "$PKG"' EXIT
install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/netscope" "$PKG/usr/share/doc/netscope"
cat > "$PKG/DEBIAN/control" <<EOF
Package: netscope
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Maintainer: IcerXYZ
Depends: python3, python3-venv, ca-certificates, util-linux
Description: NetScope authenticated LAN monitoring
 Run sudo netscope setup to configure credentials, TLS and the service.
EOF
for file in app.py security.py telemetry_schema.py launch.py gunicorn.conf.py configure.py agent_tokens.py requirements.txt requirements.lock install.sh uninstall.sh netscope.service; do
  install -m 0644 "$ROOT/$file" "$PKG/usr/lib/netscope/$file"
done
cp -R "$ROOT/static" "$ROOT/templates" "$PKG/usr/lib/netscope/"
install -m 0755 "$ROOT/packaging/netscope" "$PKG/usr/bin/netscope"
install -m 0644 "$ROOT/README.md" "$PKG/usr/share/doc/netscope/README.md"
mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/netscope_${VERSION}_all.deb"

