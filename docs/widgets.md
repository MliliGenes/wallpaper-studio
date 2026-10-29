# Desktop widgets and customization

The desktop is one transparent GTK layout. Its cards share a stylesheet, but each has
its own component, position, scale, props and on/off switch. The built-in cards are
**Clock**, **Calendar**, **System stats** (actual CPU, memory and disk usage), **Notes**, and **Logtime**.

## Arrange cards on the desktop

After installing this version with `./install.sh`, enable arrange mode:

```sh
ws layout edit
```

- Drag a card to move it; it follows the pointer while you drag.
- Drag its lower-right corner to resize it, or scroll over it to change its scale.
- Positions and sizes are saved when you release the card. Scale ranges from 0.5 to 2.5.

Finish with:

```sh
ws layout done
```

Arrange mode raises the cards and accepts input only over the cards. Normal mode stays
below app windows and passes mouse input through to the desktop, except over widget buttons. Manual locking hides
the layout. The primary monitor's work area excludes GNOME's panel.

In normal mode the canvas uses a normal window with the window manager's **below** state.
This places interactive widgets above GNOME's transparent desktop-icons window and below
ordinary apps. Only the button rectangles accept pointer input; drag controllers are
enabled only in arrange mode.

## Independent switches

The graphical control panel lists each layout entry under **Desktop widgets**, including
user-defined cards. Each switch changes only that entry. **Show desktop widgets** is a
master switch; it preserves individual choices. The TUI's **Widgets** panel has the same
individual controls, and the CLI supports:

```sh
ws layout list
ws layout disable calendar
ws layout enable calendar
ws layout toggle notes
```

## Files you customize

```text
~/.config/wallpaper-studio/
├── layout.json       which widgets load, their positions, scales and props
├── widgets.css       shared desktop-card styling
├── app.css           graphical control-panel styling
└── widgets/
    └── greeting.py   your own component; no app/core edits required
```

`XDG_CONFIG_HOME` is respected. These files survive updates. Layout, CSS and custom Python
component edits reload live. Invalid layout/CSS edits keep the previous working version;
a broken edit to an already-loaded custom component keeps its previous function and
writes the error to `~/.cache/wallpaper-studio/helper.log`.

On school machines with `~/goinfre`, app files and caches are stored in
`~/goinfre/wallpaper-studio`. The cache path above remains a compatibility link; your
customizations stay in the small home config folder. Use `ws paths` to inspect locations.

## Layout format

For example, this layout contains two independently controlled cards:

```json
{
  "version": 1,
  "widgets": [
    {
      "id": "clock",
      "component": "Clock",
      "anchor": "top-center",
      "x": 0,
      "y": 32,
      "scale": 1.2,
      "enabled": true
    },
    {
      "id": "notes",
      "component": "Notes",
      "anchor": "bottom-right",
      "x": 32,
      "y": 32,
      "scale": 1,
      "class_name": "personal-note",
      "props": {"title": "Today", "text": "Build something useful."}
    }
  ]
}
```

Each `id` must be unique. The available built-in component names are `Clock`, `Calendar`,
`System`, `Notes` and `Logtime`. Custom component names refer to Python filenames in your `widgets/`
folder, without `.py`.

Anchors combine `top`, `center` or `bottom` with `left`, `center` or `right`, for example
`top-left`, `center-center`, or `bottom-right`. Offsets point inward from an edge; centred
offsets move right/down. Cards are kept within the work area. Dragging saves a `top-left`
anchor with pixel offsets. If a Clock entry omits `y`, it uses the existing `clock_top`
preference. An explicit `y` overrides that preference.

`enabled` defaults to true, `scale` to 1, offsets to zero, and props to an empty object.
The global `config` prop is supplied automatically. Multiple instances can use the same
component with different IDs and props.

```sh
ws layout path      # print the layout file path
ws layout reset     # replace placements with the default five-card layout
```

Reset deliberately replaces `layout.json`; copy your custom layout first if you want to
keep it. The installer upgrades the exact former clock-only starter layout, and preserves
layouts that have been customized.

## Logtime

Set your login in the GUI's **Desktop widgets** settings, the TUI's **Widgets** panel,
or the CLI:

```sh
ws config set logtime_username sel-mlil
ws config set logtime_goal 180
ws layout enable logtime
```

The hours goal is your own target, with an initial default of 180. The ring caps at 100%;
the actual hours always remain visible, including hours beyond the goal. An empty login
pauses requests. Each Logtime entry has its own switch and navigation state.

Each month starts on the **28th**: **October 2026** means **October 28–November 27**.
On October 27 the active period is September 28–October 27; on October 28 it rolls over
to October 28–November 27 automatically, including when the helper stays running.
Prev/Next shifts both endpoints by one month and fetches that period.
Dates are sent as UTC midnight ISO timestamps to
`https://logtime-med.1337.ma/api/get_log` using a JSON POST. No API key is required.

Requests run in a daemon thread with a 12-second timeout. Results refresh every five minutes;
Refresh requests an earlier update. Results for an old selection never replace the selected
user/period. Successful results are cached under `~/goinfre/wallpaper-studio/cache/logtime`
when goinfre is available (otherwise the usual app cache). Cached hours remain visible if
a refresh fails, with an error message; an error retries after one minute.

New/default layouts include the card. To add it to an existing customized layout, append
this entry to its `widgets` array, preserving the other entries:

```json
{"id": "logtime", "component": "Logtime", "anchor": "bottom-left", "x": 32, "y": 32, "scale": 1}
```

Optional props `{"username": "another-login", "goal": 196}` override global preferences
for that one instance. Give multiple instances unique IDs. To change its look, edit your
`widgets.css`; `.logtime-login`, `.logtime-hours`, `.logtime-percent`, `.progress-ring`,
`.logtime-period` and `.logtime-card button` are available. Ring size uses `min-width` and
`min-height` in `em`; its color uses `color`, so palette colors and scaling work together.

## CSS styling and scaling

The default style is wallpaper-tinted glass: translucent surfaces, accent gradients,
highlighted borders and drop shadows. Text remains fully opaque. A softened, cached
copy of the wallpaper is drawn behind each card with the same rounded shape as its CSS.
The sampled area follows the card while dragging, so the frosted backdrop stays aligned
with the wallpaper.

Use **Frosted widget glass** in the GUI/TUI, or:

```sh
ws config set widget_blur true
ws config set widget_blur_radius 24
ws config set widget_blur false
```

The radius ranges from 0 to 64; 0 disables blur. This is a wallpaper-backed effect, not
compositor blur of arbitrary windows: video wallpapers use their cached poster frame.
When a wallpaper cannot be read, cards fall back to translucent, palette-tinted surfaces.
The softened image is cached at a small resolution and refreshed only when its source,
screen dimensions or blur settings change. No GNOME extension or extra pip dependency
is needed.

Set `class_name: "no-blur"` on an individual layout entry to omit its wallpaper backdrop.
Surface transparency and shadows remain editable in `widgets.css`:

```css
#ws-desktop-widgets.glass-ready .desktop-widget {
  background-color: alpha(@ws_sheet, 0.38);
  border-color: alpha(@ws_accent, 0.28);
  box-shadow: 0 0.6em 1.8em alpha(@ws_shadow, 0.28);
}
```

Appearance is CSS. GTK CSS does not support web layout properties such as `position`,
`top`, `left`, Flexbox or Grid; placement is handled by the layout file and arrange mode.
The shipped card design uses `em` units so font sizes, padding and rounded corners grow
together when scaled. Use relative units in your custom styles for the same behavior.
Fixed `px` values remain fixed when the card's base font changes.

Each card has a stable CSS ID, `#widget-<id>`, and the shared `.desktop-widget` class:

```css
/* All cards */
#ws-desktop-widgets .desktop-widget {
  border-radius: 1.5em;
  background-color: alpha(@ws_sheet, 0.50);
  color: @ws_ink;
  padding: 1.25em;
}

/* Only the clock instance whose id is "clock" */
#widget-clock .clock-time {
  font-family: monospace;
  font-size: 3.8em;
  color: @ws_accent;
}

/* A class supplied by a layout entry */
#ws-desktop-widgets .personal-note {
  background-color: alpha(@ws_paper, 0.95);
}
```

`@ws_paper`, `@ws_sheet`, `@ws_ink`, `@ws_muted`, `@ws_accent`, `@ws_accent_text`, `@ws_shadow` and `@ws_on_accent` follow the
wallpaper palette. Do not edit generated `theme.css`. For the control panel, edit `app.css`.
The TUI can open the layout and styles in `VISUAL`/`EDITOR`, falling back to `nano`.

## Add your own card

Create `~/.config/wallpaper-studio/widgets/greeting.py`:

```python
from wallpaper_studio.components import Column, Text, component

@component
def Widget(config, name="sel-mlil"):
    return Column(
        Text("HELLO", class_name="widget-label", align="start"),
        Text(name, class_name="greeting-name"),
        spacing=8,
    )
```

Add this object to the `widgets` list in `layout.json`:

```json
{
  "id": "hello",
  "component": "greeting",
  "anchor": "bottom-left",
  "x": 32,
  "y": 32,
  "props": {"name": "Your name"},
  "scale": 1
}
```

It appears automatically in the layout and GUI widget switches. No registration in the
app is needed. Custom files are ordinary Python code executed as your user. Use absolute
imports such as `from wallpaper_studio.components import ...`.

Available elements:

| Element | Native GTK | Main props |
|---|---|---|
| `Column(*children)` | Vertical box | `spacing` |
| `Row(*children)` | Horizontal box | `spacing` |
| `Text(text)` | Label | `wrap`, `max_width_chars` |
| `Progress(value)` | Progress bar | Fraction 0..1, optional `text` |
| `Button(text)` | Button | `on_click` callback, `sensitive` |
| `Ring(value, *children)` | Drawing area + overlay | Fraction 0..1, children inside the arc |

All support `class_name`, `visible`, `expand`, `align` and stable sibling `key` values.
Lists are flattened; `None` and `False` children are skipped. A component may return None.
The runtime refreshes once per second and updates native widgets in place, preserving
keyed children when reordered. Keep component functions fast: fetch network data in a
provider and render cached results. Don't perform blocking network calls inside render functions.

For a stateful card, use `model = use_model(MyModel, key="my-data")` inside your component
(import it from `wallpaper_studio.components`). The runtime creates the model once per
layout entry and reuses it across renders. A model can expose navigation and background
fetch methods; pass those to `Button(on_click=model.refresh)`. Button clicks rerender
immediately. The runtime calls the model's optional `close()` method when the card is
disabled, removed, replaced or the helper exits. Keep background work independent of GTK;
consume results on the main thread, as `wallpaper_studio/logtime.py` does. Navigation and
Refresh are inactive during arrange mode so a drag cannot accidentally change the period.

For future ranking cards, a provider can atomically write cached data such as
`~/.cache/wallpaper-studio/student.json`. Keep credentials and ranking calculations in
that provider; show the data's refresh time in the widget. Define the ranking period and
population before implementing the leaderboard. User components do not create their own
windows, GTK applications or event loops.

## Keep-awake

```sh
ws config set awake_method mouse
ws config set awake_interval 60
ws awake 60
ws awake off
ws config set awake_method inhibit
```

Mouse mode saves the pointer position, sends an XTEST movement to `(0, 0)` and immediately
returns to the saved coordinates. If already at `(0, 0)`, it uses a one-pixel excursion.
No keys or clicks are sent. Movement is skipped while keys or mouse buttons are held,
and requires logind to report an active, unlocked session. The GNOME inhibitor remains
active alongside mouse mode. If XTEST/libXtst or session information is unavailable,
only inhibition remains. Old `awake_method: "key"` preferences migrate to mouse mode.

`awake off`, expiry and logout stop keep-awake. `restore` also hides the full widget
layout and leaves arrange mode. Test whether synthetic input satisfies the school
machine's idle monitor; this depends on that environment.

## Framework files and verification

`components.py` defines the GTK-independent component API; `gtk_renderer.py` translates
it to GTK 3; `layout.py` loads placements and custom modules; `widget_runtime.py` owns
one desktop window and its layout. Built-in components live in `widgets/`. The control
panel uses GTK 4/libadwaita in a separate process.

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 tests/smoke_widgets.py     # GTK 3 display required
/usr/bin/python3 tests/smoke_controls.py    # GTK 4 display required
```

Check window stacking, desktop-icon clicks, live dragging/resizing, monitor changes,
manual locking and the school's idle timeout on the target GNOME/X11 session.

Useful references: [GTK 3 CSS](https://docs.gtk.org/gtk3/css-overview.html),
[CSS properties](https://docs.gtk.org/gtk3/css-properties.html),
[GTK 3 API](https://docs.gtk.org/gtk3/),
[GTK 4 API](https://docs.gtk.org/gtk4/),
[PyGObject](https://pygobject.gnome.org/getting_started.html),
[XTEST](https://www.x.org/releases/current/doc/libXtst/xtestlib.html).
