#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-0.1.0}"
ARCH="all"
PKG="$ROOT/build/netscope"
rm -rf "$PKG"
install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/doc/netscope"
cat > "$PKG/DEBIAN/control" <<EOF
Package: netscope
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: IcerXYZ
Description: NetScope network monitoring package
 NetScope packaging baseline. Monitoring services are not yet included.
EOF
install -m 0755 "$ROOT/packaging/netscope" "$PKG/usr/bin/netscope"
install -m 0644 "$ROOT/README.md" "$PKG/usr/share/doc/netscope/README.md"
mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$PKG" "$ROOT/dist/netscope_${VERSION}_${ARCH}.deb"
echo "Built $ROOT/dist/netscope_${VERSION}_${ARCH}.deb"
