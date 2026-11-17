#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run update.sh as your normal Linux user, not with sudo."
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Git is required. Install it with: sudo apt install git"
  exit 1
fi

remote_url="$(git -C "$SOURCE_DIR" remote get-url origin 2>/dev/null || true)"
case "$remote_url" in
  https://github.com/IcerXYZ/Netscope|https://github.com/IcerXYZ/Netscope.git|git@github.com:IcerXYZ/Netscope.git|ssh://git@github.com/IcerXYZ/Netscope.git) ;;
  *) echo "This updater only accepts the official IcerXYZ/Netscope origin."; exit 1 ;;
esac

branch="$(git -C "$SOURCE_DIR" branch --show-current)"
if [[ "$branch" != "main" ]]; then
  echo "Switch this checkout to the main branch before updating (current: $branch)."
  exit 1
fi

echo "Fetching the latest NetScope scripts from GitHub..."
git -C "$SOURCE_DIR" pull --ff-only origin main

echo "Applying the downloaded scripts and restarting NetScope..."
sudo bash "$SOURCE_DIR/install.sh"
