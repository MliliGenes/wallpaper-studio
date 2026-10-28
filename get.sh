#!/usr/bin/env bash
# Install Wallpaper Studio in one line (no git, no sudo), then open it:
#
#   curl -fsSL https://raw.githubusercontent.com/yuxev/wallpaper-studio/main/get.sh | bash
#
# Run the same line again to update.
set -euo pipefail

REPO=yuxev/wallpaper-studio
BRANCH=${WALLPAPER_STUDIO_BRANCH:-main}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading Wallpaper Studio…"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar -xz -C "$tmp"
bash "$tmp"/wallpaper-studio-*/install.sh

# open the window, detached from this terminal
(setsid "$HOME/.local/share/wallpaper-studio/wallpaper-studio" >/dev/null 2>&1 &)
echo "Opening Wallpaper Studio. Next time, find it in your apps or run: wallpaper-studio"
