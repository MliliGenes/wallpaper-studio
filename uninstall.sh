#!/usr/bin/env bash
# Remove Wallpaper Studio and put your desktop back the way it was.
set -uo pipefail
APP=io.github.WallpaperStudio
DEST="$HOME/.local/share/wallpaper-studio"

[ -x "$DEST/wallpaper-studio" ] && "$DEST/wallpaper-studio" restore
pkill -f "^[^ ]*python3[^ ]* .*wallpaper[-_]studio desktop$" 2>/dev/null
rm -rf "$DEST" "$HOME/.config/wallpaper-studio" "$HOME/.cache/wallpaper-studio"
rm -f "$HOME/.local/bin/wallpaper-studio" "$HOME/.local/share/applications/$APP.desktop" \
	"$HOME/.local/share/icons/hicolor/scalable/apps/$APP.svg" "$HOME/.config/autostart/wallpaper-studio-desktop.desktop"
echo "Wallpaper Studio removed. (The adw-gtk3 theme in ~/.local/share/themes was left in place.)"
