#!/usr/bin/env bash
# Install Wallpaper Studio for the current user (no sudo needed). Run it again to update.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

APP=io.github.WallpaperStudio
DEST="$HOME/.local/share/wallpaper-studio"
ADW_GTK3=v6.5   # GTK 3 theme that lets older apps (Files, Terminal…) take the new colours

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# --- what the app needs -------------------------------------------------------------
python3 - <<'PY' || { echo "Wallpaper Studio needs GTK 4 and libadwaita for Python (gir1.2-adw-1)." >&2; exit 1; }
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
PY
if [ "${XDG_SESSION_TYPE:-x11}" != x11 ]; then
	echo "Note: you're on $XDG_SESSION_TYPE; the wallpaper is only drawn in X11 (Xorg) sessions." >&2
fi
command -v cvlc >/dev/null || echo "Note: VLC isn't installed, so video wallpapers won't play (pictures work)." >&2

# an older home-made setup also draws the desktop and writes gtk.css; two would fight
if [ -f "$HOME/.config/autostart/studio-wallpaper.desktop" ]; then
	echo "Found the older 'studio' setup. Run 'studio reset' first so the two don't fight over the desktop." >&2
	exit 1
fi

# --- the app ------------------------------------------------------------------------
say "Installing to $DEST"
HELPER='^[^ ]*python3[^ ]* .*wallpaper[-_]studio desktop$'
pkill -f "$HELPER" 2>/dev/null || true
for _ in $(seq 50); do pgrep -f "$HELPER" >/dev/null || break; sleep 0.1; done   # let it let go first
rm -rf "$DEST"
mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications" \
	"$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.config/autostart"
cp -r wallpaper_studio wallpaper-studio "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
ln -sf "$DEST/wallpaper-studio" "$HOME/.local/bin/wallpaper-studio"
cp data/$APP.svg "$HOME/.local/share/icons/hicolor/scalable/apps/$APP.svg"

cat >"$HOME/.local/share/applications/$APP.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Wallpaper Studio
Comment=Change your wallpaper and recolour your desktop to match
Exec=$DEST/wallpaper-studio
Icon=$APP
Categories=Settings;DesktopSettings;GTK;
Keywords=wallpaper;background;theme;colour;color;
StartupNotify=true
DESKTOP

# the helper that draws the wallpaper, every time you log in
cat >"$HOME/.config/autostart/wallpaper-studio-desktop.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Wallpaper Studio (desktop)
Comment=Draws your Wallpaper Studio wallpaper behind every window
Exec=$DEST/wallpaper-studio desktop
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESKTOP

# --- GTK 3 theme --------------------------------------------------------------------
if [ ! -d "$HOME/.local/share/themes/adw-gtk3" ] && [ ! -d /usr/share/themes/adw-gtk3 ]; then
	say "Downloading the adw-gtk3 theme ($ADW_GTK3)"
	mkdir -p "$HOME/.local/share/themes"
	if curl -fsSL "https://github.com/lassekongo83/adw-gtk3/releases/download/$ADW_GTK3/adw-gtk3${ADW_GTK3}.tar.xz" |
		tar -xJ -C "$HOME/.local/share/themes"; then
		:
	else
		echo "Couldn't download adw-gtk3; newer apps will still be recoloured, older ones won't." >&2
	fi
fi

update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# start the helper now, so you don't have to log out
(setsid "$DEST/wallpaper-studio" desktop >/dev/null 2>&1 &)

say "Done. Open “Wallpaper Studio” from your apps, or run: wallpaper-studio"
