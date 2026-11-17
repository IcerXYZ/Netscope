#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:---host}"

if ! command -v git >/dev/null 2>&1; then
  echo "Git is required. Install it with: sudo apt install git"
  exit 1
fi

case "$MODE" in
  --host) ;;
  --docker)
    if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
      echo "Docker Engine and the Docker Compose plugin are required for --docker mode."
      exit 1
    fi
    ;;
  *) echo "Usage: bash update.sh [--host|--docker]"; exit 2 ;;
esac

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

echo "Fetching the latest NetScope code from GitHub..."
git -C "$SOURCE_DIR" pull --ff-only origin main

if [[ "$MODE" == "--docker" ]]; then
  echo "Rebuilding this Docker deployment from the repository Dockerfile and compose.yaml..."
  (cd "$SOURCE_DIR" && docker compose up -d --build)
else
  echo "Applying the downloaded scripts and restarting the Linux service..."
  if [[ "${EUID}" -eq 0 ]]; then
    bash "$SOURCE_DIR/install.sh"
  else
    sudo bash "$SOURCE_DIR/install.sh"
  fi
fi
