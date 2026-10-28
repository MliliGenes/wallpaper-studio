# Wallpaper Studio

Pick a wallpaper and your whole desktop takes its colours.

![Clicking wallpapers in Wallpaper Studio: the desktop, the app and Calculator recolour to match each one](docs/demo.gif)

*Picking a wallpaper recolours the desktop and every open app on the spot. [Full-quality video](docs/demo.webm).*

- **Wallpapers:** pictures or looping videos, chosen from a folder of yours, with an optional new one every few hours.
- **Colours:** apps, GNOME Terminal and the lock screen are recoloured to match, in light, dark, or auto (light by day, dark at night).
- **One click back:** *Restore original look* puts every setting back the way it was.
- **Desktop clock:** a time-and-date widget at the top centre, styled with your own live CSS.
- **Terminal control:** inspect and change preferences with `wallpaper-studio config` or `ws config`.

Made for the 42 iMacs (Ubuntu 22.04, GNOME, X11), where the normal desktop picture setting is locked.
No sudo needed.

![The same wallpaper in light mode (left) and dark mode (right)](docs/light-dark.png)

*One wallpaper, two looks: light by day, dark at night (or pick one).*

## Install

Paste this in a terminal. It downloads, installs and opens the app (no sudo needed):

```sh
curl -fsSL https://raw.githubusercontent.com/yuxev/wallpaper-studio/main/get.sh | bash
```

Run the same line again to update. Later, open **Wallpaper Studio** from your apps (press Super and
type *wallpaper*) or run `wallpaper-studio`.

Or from a clone:

```sh
git clone https://github.com/yuxev/wallpaper-studio.git
cd wallpaper-studio
./install.sh
```

## How to use it

<img src="docs/window.png" alt="The Wallpaper Studio window" width="560">

1. **Pick a folder.** The app comes with 16 wallpapers to start with;
   *Change folder…* points it at your own pictures and videos instead.
2. **Click a wallpaper.** The desktop changes and every open app takes its colours within a second.
   You can also drop a picture onto the window, or use *Open a file…*.
3. **Choose light, dark or auto** under *Colours*. Auto is light from 07:00 and dark from 19:00.
4. **Optional:** a new random wallpaper every few hours, see-through windows, the wallpaper on your
   lock screen, and *Keep screen awake* while you read or watch something.

To undo everything, open the menu (⋮) and choose *Restore original look*.

## Your own style

Write your own style in `~/.config/gtk-3.0/gtk.css` and `gtk-4.0/gtk.css`. Wallpaper Studio only adds one
line at the top of the GTK 4 file and keeps everything else. Use these colours there and your style follows
every wallpaper:

| Name | What it is |
|---|---|
| `@ws_paper`, `@ws_paper2`, `@ws_sheet` | backgrounds: window, header bars, content |
| `@ws_ink`, `@ws_muted` | text, secondary text |
| `@ws_accent`, `@ws_accent_text`, `@ws_on_accent` | the accent, accent-coloured text, text on the accent |
| `@ws_shadow` | a hard shadow colour (ink by day, black at night) |

For example, sharp corners with an accent shadow under every window:

```css
* { border-radius: 0; }
window.csd { box-shadow: 0 0 0 2px @ws_ink, 5px 5px 0 1px @ws_accent; }
```

## Recolour other tools (hooks)

After every recolour, Wallpaper Studio runs each executable file in `~/.config/wallpaper-studio/hooks/`
(in the background, in name order). The colours for the current mode are in environment variables:

| Variable | Value |
|---|---|
| `WS_MODE` | `light` or `dark` |
| `WS_PAPER`, `WS_PAPER2`, `WS_SHEET`, `WS_INK`, `WS_MUTED` | backgrounds and text, as `#RRGGBB` |
| `WS_ACCENT`, `WS_ACCENT_TEXT`, `WS_ON_ACCENT` | the accent colours |
| `WS_ANSI_0` … `WS_ANSI_15` | a 16-colour terminal palette |
| `WS_STATE` | path to `state.json`, with both the light and dark palettes |

For example, `~/.config/wallpaper-studio/hooks/kitty` (made executable with `chmod +x`):

```sh
#!/bin/sh
printf 'background %s\nforeground %s\ncursor %s\n' "$WS_PAPER" "$WS_INK" "$WS_ACCENT" > ~/.config/kitty/wallpaper.conf
pkill -USR1 kitty
```

## Command line

```
wallpaper-studio                  open the window
wallpaper-studio set FILE         use a picture or video
wallpaper-studio next             a random different one from your folder
wallpaper-studio light|dark|auto  colour mode
wallpaper-studio restore          undo everything
wallpaper-studio clock on|off     show or hide the desktop clock
wallpaper-studio awake 60         keep awake for 60 minutes (on/off also supported)
wallpaper-studio config list      list preferences and descriptions
wallpaper-studio config get KEY   read a preference
wallpaper-studio config set KEY VALUE
                                 validate, save and apply a preference
wallpaper-studio config reset [KEY]
                                 reset one preference, or all preferences
wallpaper-studio status           configuration, wallpaper state and awake request as JSON
```

The installer also creates `~/.local/bin/ws` as a shortcut, unless you already have a
command there. Put `~/.local/bin` on your `PATH` if needed. Examples:

```sh
ws config set folder ~/Pictures/Wallpapers
ws config set rotate_hours 0.5
ws config set glass true
ws config set light_from 8
ws config set dark_from 20
ws config set clock_format '%H:%M:%S'
ws config set clock_top 48
```

Configuration commands work without a graphical session; changes apply at the next
helper startup. With a running desktop, commands apply immediately and the open
control panel follows the saved preferences. `config path` prints the configuration path.
Equal light/dark hours mean always dark; schedules can also cross midnight.

For optional Bash/Zsh aliases (`ws`, `wnext`, `wawake`, `wclock`), run:

```sh
eval "$(wallpaper-studio shell-init)"
```

Add that line to your shell startup file to keep them. The installer leaves startup
files alone. `./install.sh --no-start` installs without launching the helper immediately;
the login autostart entry is still installed.

## Desktop widgets and live CSS

Edit `~/.config/wallpaper-studio/widgets.css` to style the desktop clock, or `app.css`
in the same directory to style the control panel. Both reload automatically and your
edits survive updates. `XDG_CONFIG_HOME` is respected when set.

```css
#ws-desktop-widgets .clock-time {
  font-family: monospace;
  font-size: 72px;
  color: @ws_accent;
}
```

The clock uses GTK 3; the control panel uses GTK 4. Read the
[widget development guide](docs/widgets.md) for the architecture, CSS selectors,
GTK API reading path and a pattern for future logtime, cluster-position and ranking
widgets.

Keep-awake uses GNOME inhibition plus a periodic XTEST F15 tap by default while enabled.
It skips held keys and locked/inactive sessions. F15 can trigger apps or custom shortcuts;
use `ws config set awake_method inhibit` for GNOME inhibition alone. Key mode requires
`libXtst` and an F15 mapping; it falls back to inhibition if unavailable. Whether synthetic
input satisfies a school's idle monitor needs checking on that machine. See
`~/.cache/wallpaper-studio/helper.log` for helper diagnostics. Restore also hides the clock
and turns keep-awake off.

## Uninstall

```sh
./uninstall.sh
```

It restores your original look first, then removes the app.

## How it works

| Part | What it does |
|---|---|
| `wallpaper_studio/palette.py` | Reads the picture at a tiny size and picks an accent colour (the picture's most vivid colour that stands out) plus neutrals tinted with its overall colour, in a light and a dark set. |
| `wallpaper_studio/core.py` | Applies them: a small GTK theme ("Wallpaper Studio A"/"B" in `~/.local/share/themes`, adw-gtk3 underneath plus your colours), the light/dark setting, a GNOME Terminal profile, and the lock-screen picture. Saves your original settings first. GTK only re-reads a theme when its name changes, so each recolour flips between the two identical copies and open apps restyle live. |
| `wallpaper_studio/desktop.py` | A small helper started at login. GNOME's own wallpaper is locked at 42, so it draws the wallpaper in a desktop window behind everything. Pictures cost almost nothing once drawn. Videos play through VLC and pause when a window is maximised or the screen is locked. It also handles the rotation timer and the auto light/dark switch. |
| `wallpaper_studio/app.py` | The window (GTK 4 + libadwaita). |
| `wallpaper_studio/settings.py`, `storage.py`, `cli.py` | Validated preferences, atomic persistence, shared locking and terminal commands; configuration inspection needs no GTK. |
| `wallpaper_studio/widgets.py`, `styles/` | The GTK 3 desktop clock, default CSS and live user overrides. |
| `wallpaper_studio/awake.py` | Optional XTEST F15 pulses while keep-awake is active. |

Preferences and generated colours live in `~/.config/wallpaper-studio`; previews and logs
in `~/.cache/wallpaper-studio`; installed code in `~/.local/share/wallpaper-studio`.
It also writes generated themes in `~/.local/share/themes`, a GTK 4 CSS import,
launcher/autostart files, GNOME settings and session files in `XDG_RUNTIME_DIR`.

Older GTK 3 apps (Files, Terminal…) take the colours through the
[adw-gtk3](https://github.com/lassekongo83/adw-gtk3) theme, which `install.sh` downloads into
`~/.local/share/themes` if you don't have it.

## Limits

- Open GTK 3 apps (Files, Terminal, Calculator…) and the Wallpaper Studio window recolour instantly.
  Other libadwaita apps (Settings, Text Editor…) only read their colours when they start, so they change
  the next time you open them.

- X11 sessions only (the default at 42).
- Videos need VLC and use more memory than pictures (about 75–130 MB while playing).
