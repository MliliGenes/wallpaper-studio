#!/usr/bin/env bash
# Remove Wallpaper Studio and put your desktop back the way it was.
set -uo pipefail
APP=io.github.WallpaperStudio
DEST="$HOME/.local/share/wallpaper-studio"
cd "$(dirname "$(readlink -f "$0")")"
PYTHON=/usr/bin/python3
HELPER=$("$PYTHON" -m wallpaper_studio.install_storage helper-pattern)

if [ "$(readlink "$HOME/.local/bin/ws" 2>/dev/null || true)" = "$DEST/wallpaper-studio" ]; then
	rm -f "$HOME/.local/bin/ws"
fi

if [ -x "$DEST/wallpaper-studio" ]; then
	"$DEST/wallpaper-studio" restore || exit 1
else
	"$PYTHON" -m wallpaper_studio restore || exit 1
fi
pkill -f "$HELPER" 2>/dev/null
"$PYTHON" -m wallpaper_studio.install_storage uninstall || exit 1
CONFIG_DIR=$("$PYTHON" -c 'from wallpaper_studio.storage import CONFIG_DIR; print(CONFIG_DIR)')
rm -rf "$CONFIG_DIR"
rm -f "$HOME/.local/bin/wallpaper-studio" "$HOME/.local/share/applications/$APP.desktop" \
	"$HOME/.local/share/icons/hicolor/scalable/apps/$APP.svg" "$HOME/.config/autostart/wallpaper-studio-desktop.desktop"
echo "Wallpaper Studio removed. (The adw-gtk3 theme in ~/.local/share/themes was left in place.)"
