#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-0.1.0}"
ARCH="all"
PKG="$ROOT/build/netscope-pro"
rm -rf "$PKG"
install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/doc/netscope-pro"
cat > "$PKG/DEBIAN/control" <<EOF
Package: netscope-pro
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: IcerXYZ
Description: NetScope Pro network monitoring package
 NetScope Pro packaging baseline. Monitoring services are not yet included.
EOF
install -m 0755 "$ROOT/packaging/netscope-pro" "$PKG/usr/bin/netscope-pro"
install -m 0644 "$ROOT/README.md" "$PKG/usr/share/doc/netscope-pro/README.md"
mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/netscope-pro_${VERSION}_${ARCH}.deb"
echo "Built $ROOT/dist/netscope-pro_${VERSION}_${ARCH}.deb"
