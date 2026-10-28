# Building your desktop layer

Wallpaper Studio is the wallpaper, colour and widget layer of a GNOME/X11 setup. Keep
installation of terminals, LazyVim, Git and Docker in separate, opt-in setup modules;
those tools have their own dependencies and configuration lifecycles. They can consume
Wallpaper Studio's palette through hooks without becoming dependencies of the wallpaper.

## The pieces

```text
CLI / GTK 4 control panel
        |
        v
settings.py + storage.py       validated preferences + atomic files + process locks
        |
        +--> core.py           palette, theme integrations, restoration
        |
        +--> desktop.py        persistent X11 wallpaper / video / scheduling
                 |
                 +--> widgets.py   GTK 3 desktop window and clock
                 +--> awake.py     optional XTEST key tap
```

The desktop helper uses GTK 3 because it already renders through GDK 3 and controls X11
windows. The control panel uses GTK 4/libadwaita. **Never import both GTK versions into
one process.** They share files and the semantic colour palette, not widget instances.

`config.json` stores preferences, `state.json` stores the selected wallpaper and both
palettes, and `originals.json` stores settings to restore. Preferences are validated on
write; invalid values in hand-edited files fall back to defaults. Read/modify/write
operations use a file lock. Don't call a locking save function while already holding
`storage.locked()`; the lock is not reentrant.

## Style your desktop

The installer and app seed two files without overwriting your edits:

- `~/.config/wallpaper-studio/widgets.css`: GTK 3 desktop widgets.
- `~/.config/wallpaper-studio/app.css`: GTK 4 control-panel overrides.

Both reload automatically, including when an editor saves by replacing the file. With
`XDG_CONFIG_HOME` set, use that directory instead of `~/.config`.

For a large, unboxed clock, put this in `widgets.css`:

```css
#ws-desktop-widgets .desktop-clock {
  background: transparent;
  border: none;
  border-radius: 0;
}
#ws-desktop-widgets .clock-time {
  font-family: monospace;
  font-size: 84px;
  color: @ws_ink;
  text-shadow: 0 2px 8px alpha(@ws_paper, 0.9);
}
#ws-desktop-widgets .clock-date {
  color: @ws_accent;
  letter-spacing: 2px;
}
```

The desktop clock sits at the top centre of the **primary monitor's work area**, below
GNOME's panel. It stays below normal app windows, appears on all workspaces, does not
take keyboard focus and passes pointer input through to the desktop. CSS controls
appearance; `clock_top` controls placement. A window manager can interpret desktop
window hints differently, so verify stacking on the target iMac.

For the control panel, try this in `app.css`:

```css
.hero, .thumb, .thumb picture { border-radius: 0; }
.thumb.current { outline-color: @ws_accent; }
```

GTK supports a subset of CSS. Widget trees (`Gtk.Box`, `Gtk.Grid`, etc.) control layout;
web properties such as `display: flex` and JavaScript DOM APIs do not apply.
Don't edit `theme.css`: it is regenerated from the wallpaper.

## Configure the clock and keep-awake behavior

```sh
ws clock on
ws config set clock_format '%H:%M:%S'
ws config set clock_date_format '%a, %d %b'
ws config set clock_date_format ''       # hide the date
ws config set clock_top 48

ws config set awake_method key          # GNOME inhibitor + periodic F15 press/release
ws config set awake_interval 60         # seconds, allowed range 10–300
ws awake 60                             # on for one hour
ws awake off
ws config set awake_method inhibit      # GNOME only, no synthetic keys
```

Key mode requires X11's XTEST extension and `libXtst`. It never types text or moves the
pointer, but F15 is still a real synthetic key event: apps or custom F15 shortcuts can
react to it. It skips taps while any key is held and requires logind to report an active,
unlocked session. Without the extension, key mapping or session information, only
GNOME inhibition remains. An administrator's idle monitor may treat synthetic input
differently from hardware input; test on the actual school machine.

The request expires when its duration ends, when you turn it off, or at logout when
the session runtime directory is cleared. `restore` also disables keep-awake and hides
the clock. Diagnostics go to `~/.cache/wallpaper-studio/helper.log` (or `XDG_CACHE_HOME`).

## Add another widget

Start with `Clock` in `wallpaper_studio/widgets.py`:

1. Build a `Gtk.Box` subclass with labels, a progress bar or a grid.
2. Give it stable CSS classes with `get_style_context().add_class(...)`.
3. Add it to a container in `DesktopWidgets`, alongside the clock. Currently the window
   contains the clock directly; replace that child with a `Gtk.Box` for multiple widgets.
4. Update it from a GLib timer or a file monitor. GTK updates belong on the main thread.
5. Add validated settings in `settings.py` and descriptions in `DESCRIPTIONS`.

For a first custom widget without networking, a producer can write:

```json
{"login":"your-login","logtime_hours":42.5,"cluster_position":"c2r4p8","rank":12}
```

to `~/.cache/wallpaper-studio/student.json`. Your widget reads that file and updates
labels. Publish updates with atomic replacement, just like `storage.write()`.
The current app does not read this file yet; this is an extension pattern.

Keep API access in a separate data-provider module/process. Fetch off the GTK main
thread, cache results, show the last successful refresh time, and handle offline or
expired credentials. Return data to GTK using `GLib.idle_add(callback, result)`.

For logtime rankings, first define the period (today/week/month), population (cluster,
campus, friends), and data source. Credentials belong outside repository files and CSS.
The presentation widget should render provider data without containing authentication
or ranking rules. The desktop window is currently click-through; an interactive
leaderboard would need its own input-enabled window or control-panel view.

## GTK reading path

1. [PyGObject getting started](https://pygobject.gnome.org/getting_started.html): Python
   bindings, application lifecycle, signals.
2. [GTK 3 API](https://docs.gtk.org/gtk3/): desktop widgets in this project. Start with
   `Gtk.Box`, `Gtk.Label`, `Gtk.Grid`, `Gtk.ProgressBar` and `Gtk.Window`.
3. [GTK 3 CSS overview](https://docs.gtk.org/gtk3/css-overview.html) and
   [supported properties](https://docs.gtk.org/gtk3/css-properties.html): selectors,
   style classes, named colours and supported declarations.
4. [GTK 4 API](https://docs.gtk.org/gtk4/) and
   [libadwaita API](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/): control
   panel and future standalone apps. Check the `since` version against Ubuntu 22.04.
5. [GLib main loop](https://docs.gtk.org/glib/main-loop.html): timers and asynchronous
   updates. Avoid blocking work inside timer callbacks.
6. [Gdk.Window.set_pass_through](https://docs.gtk.org/gdk3/method.Window.set_pass_through.html)
   and [Gtk.Window.set_type_hint](https://docs.gtk.org/gtk3/method.Window.set_type_hint.html):
   how the desktop widget window behaves.
7. [XTEST library](https://www.x.org/releases/current/doc/libXtst/xtestlib.html): the
   optional key-event mechanism.

## Verify changes

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q wallpaper_studio
bash -n install.sh uninstall.sh get.sh
```

Use Ubuntu's `/usr/bin/python3` for GTK tests; a pyenv/virtualenv Python may lack `gi`.

On the target GNOME/X11 desktop, also verify:

- Clock appears below the panel, behind normal apps, above the wallpaper and video;
  desktop icons still accept clicks and workspaces behave normally.
- Editing CSS and changing clock settings from the CLI updates without a restart.
- Light/dark changes recolour the clock; monitor changes keep it centred.
- Keep-awake works over the machine's idle timeout and stops on expiry, `awake off`
  and manual lock. Check the helper log if XTEST or logind is unavailable.
- `restore` removes the wallpaper, hides widgets and stops keep-awake.
