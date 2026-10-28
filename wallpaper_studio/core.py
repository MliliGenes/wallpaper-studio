"""Everything Wallpaper Studio changes, in one place: the wallpaper, the colours, and the way back.

State lives in ~/.config/wallpaper-studio:
    config.json      your choices (light/dark/auto, folder, rotation, transparency)
    state.json       the wallpaper in use and its palette; the desktop helper watches this file
    originals.json   every setting as it was before the first change, for "Restore"
    theme.css        the generated GTK colours, imported by ~/.config/gtk-{3,4}.0/gtk.css
"""
import contextlib
import fcntl
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

from gi.repository import Gio, GLib

from . import palette

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "wallpaper-studio")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "wallpaper-studio")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
STATE = os.path.join(CONFIG_DIR, "state.json")
ORIGINALS = os.path.join(CONFIG_DIR, "originals.json")
THEME_CSS = os.path.join(CONFIG_DIR, "theme.css")
HOOKS = os.path.join(CONFIG_DIR, "hooks")
LOCK = os.path.join(CONFIG_DIR, ".lock")
HELPER_LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wallpaper-studio.lock")
# lives in the session's runtime folder, which is emptied at logout: "keep awake" never outlives a session
AWAKE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wallpaper-studio-awake.json")
FOREVER = -1

# wallpapers that come with the app, shown until you pick a folder of your own
BUILT_IN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wallpapers")

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".jxl", ".bmp", ".tif", ".tiff", ".gif")
VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi")

DEFAULT_CONFIG = {
    "mode": "auto",                 # light | dark | auto (follows the clock)
    "light_from": 7,                # auto mode: light from 07:00 ...
    "dark_from": 19,                # ... dark from 19:00
    "folder": BUILT_IN,
    "rotate_hours": 0,              # 0 = never change by itself
    "glass": False,                 # see-through windows
    "terminal": True,               # recolour GNOME Terminal
    "lock_screen": True,            # use the wallpaper on the lock screen
}

# settings we touch, saved once before the first change so Restore can put them back
TOUCHED = [
    ("org.gnome.desktop.interface", "gtk-theme"),
    ("org.gnome.desktop.interface", "color-scheme"),
    ("org.gnome.desktop.background", "primary-color"),
    ("org.gnome.desktop.screensaver", "picture-uri"),
]
TERMINAL = "/org/gnome/terminal/legacy/profiles:"
CSS_IMPORT = '@import url("file://{}"); /* wallpaper-studio */\n'


def is_video(path):
    return bool(path) and path.lower().endswith(VIDEO_EXT)


def is_wallpaper(path):
    return path.lower().endswith(IMAGE_EXT + VIDEO_EXT)


# --- files ------------------------------------------------------------------------

def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def load_config():
    return {**DEFAULT_CONFIG, **_read_json(CONFIG, {})}


def save_config(**changes):
    config = {**load_config(), **changes}
    _write(CONFIG, json.dumps(config, indent=2) + "\n")
    return config


def load_state():
    return _read_json(STATE, {})


def _save_state(state):
    _write(STATE, json.dumps(state, indent=2) + "\n")


@contextlib.contextmanager
def locked():
    """One change at a time: the window, the timer and the command line can overlap."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOCK, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def helper_running():
    """True if the desktop helper (which draws the wallpaper) is running in this session."""
    try:
        with open(HELPER_LOCK, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def awake_until():
    """When "keep screen awake" ends: a timestamp, FOREVER, or None when it's off."""
    until = _read_json(AWAKE, {}).get("until")
    if until is None or until == FOREVER or until > time.time():
        return until
    return None


def awake_minutes():
    """The length chosen for the current "keep awake", or None when it's off."""
    return _read_json(AWAKE, {}).get("minutes") if awake_until() is not None else None


def keep_awake(minutes):
    """Stop the screen locking from idleness for this many minutes (FOREVER: until turned off, None: off now).

    The desktop helper holds GNOME's own idle inhibitor, as video players do; it ends at logout."""
    until = None if minutes is None else FOREVER if minutes == FOREVER else time.time() + minutes * 60
    _write(AWAKE, json.dumps({"until": until, "minutes": minutes}) + "\n")
    start_helper()


def start_helper():
    if not helper_running():
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # by its full path, so install.sh can tell this install's helper from any other
        subprocess.Popen([sys.executable, os.path.join(root, "wallpaper-studio"), "desktop"], cwd=root,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


# --- settings ---------------------------------------------------------------------

def _settings(schema):
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(schema, True) is None:
        return None
    return Gio.Settings.new(schema)


def _set(schema, key, value):
    """Set a GNOME setting if it exists and isn't locked by the administrator."""
    s = _settings(schema)
    if s is None or key not in s.list_keys() or not s.is_writable(key):
        return False
    s.set_value(key, value)
    return True


def _dconf(*args):
    try:
        return subprocess.run(["dconf", *args], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def _save_originals():
    if os.path.exists(ORIGINALS):
        return
    saved = {}
    for schema, key in TOUCHED:
        s = _settings(schema)
        if s is not None and key in s.list_keys():
            saved[f"{schema} {key}"] = s.get_value(key).print_(True)
    saved["terminal-default"] = _dconf("read", f"{TERMINAL}/default")
    saved["terminal-list"] = _dconf("read", f"{TERMINAL}/list")
    _write(ORIGINALS, json.dumps(saved, indent=2) + "\n")


# --- wallpaper --------------------------------------------------------------------

def _cache_name(path, ext):
    st = os.stat(path)
    key = f"{os.path.realpath(path)}:{st.st_size}:{st.st_mtime_ns}"
    return hashlib.sha1(key.encode()).hexdigest()[:16] + ext


def video_frame(video):
    """A still from the video (2 s in, or the first frame), cached; None if VLC can't read it."""
    out = os.path.join(CACHE_DIR, "frames", _cache_name(video, ".jpg"))
    if os.path.exists(out):
        return out
    if not shutil.which("cvlc"):
        return None
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with tempfile.TemporaryDirectory(dir=os.path.dirname(out)) as tmp:
        for start in (["--start-time=2"], []):
            # software decoding: the snapshot filter can't read hardware-decoded frames
            subprocess.run(
                ["cvlc", "--intf", "dummy", "--no-audio", "--avcodec-hw=none", "--vout", "dummy",
                 "--video-filter=scene", "--scene-format=jpg", "--scene-ratio=1000", "--scene-prefix=f",
                 f"--scene-path={tmp}", *start, "--run-time=1", "--play-and-exit", video],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
            frames = sorted(f for f in os.listdir(tmp) if f.endswith(".jpg"))
            if frames:
                os.replace(os.path.join(tmp, frames[0]), out)
                return out
    return None


def still_of(path):
    """The picture itself, or for a video its still frame."""
    return video_frame(path) if is_video(path) else path


def set_wallpaper(path):
    """Show a picture or video on the desktop and recolour everything from it."""
    path = os.path.realpath(path)
    if not os.path.isfile(path) or not is_wallpaper(path):
        raise ValueError(f"not a picture or video: {path}")
    still = still_of(path)
    if still is None:
        raise ValueError("couldn't read a frame from this video (is VLC installed?)")
    pal = palette.from_image(still)
    with locked():
        _save_state({"wallpaper": path, "still": still, "palette": pal, "changed": time.time()})
    apply_theme()


def wallpapers(folder=None):
    folder = folder or load_config()["folder"]
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if not n.startswith(".") and is_wallpaper(n) and os.path.isfile(os.path.join(folder, n))]


def next_wallpaper():
    """A random different wallpaper from the folder; returns it, or None if there's nothing to pick."""
    current = load_state().get("wallpaper")
    choices = [p for p in wallpapers() if os.path.realpath(p) != current]
    if not choices:
        return None
    pick = random.choice(choices)
    set_wallpaper(pick)
    return pick


# --- colours ----------------------------------------------------------------------

def effective_mode(config=None):
    config = config or load_config()
    if config["mode"] in ("light", "dark"):
        return config["mode"]
    return "light" if config["light_from"] <= time.localtime().tm_hour < config["dark_from"] else "dark"


THEMES_DIR = os.path.join(HOME, ".local/share/themes")
# GTK re-reads a theme's files only when the theme *name* changes (and never re-reads gtk.css), so the
# colours live in a small theme of our own and every recolour flips between two identical copies of it:
# one setting change, and every running GTK 3 app restyles itself on the spot
OUR_THEMES = ("Wallpaper Studio A", "Wallpaper Studio B")


def _theme_dir(name):
    for d in (THEMES_DIR, os.path.join(HOME, ".themes"), "/usr/share/themes"):
        if os.path.isdir(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def _write_themes(dark):
    """Our theme: adw-gtk3 (or GTK's built-in Adwaita) underneath, the wallpaper colours on top."""
    adw = _theme_dir("adw-gtk3-dark" if dark else "adw-gtk3")
    base3 = Gio.File.new_for_path(os.path.join(adw, "gtk-3.0", "gtk.css")).get_uri() if adw else \
        f"resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained{'-dark' if dark else ''}.css"
    base4 = f"resource:///org/gtk/libgtk/theme/Default/Default-{'dark' if dark else 'light'}.css"
    colours = Gio.File.new_for_path(THEME_CSS).get_uri()
    for name in OUR_THEMES:
        d = os.path.join(THEMES_DIR, name)
        _write(os.path.join(d, "index.theme"), f"[X-GNOME-Metatheme]\nName={name}\nType=X-GNOME-Metatheme\n"
                                               "Comment=Made by Wallpaper Studio from your wallpaper\n")
        for version, base in (("gtk-3.0", base3), ("gtk-4.0", base4)):
            css = f'@import url("{base}");\n@import url("{colours}");\n'
            _write(os.path.join(d, version, "gtk.css"), css)
            _write(os.path.join(d, version, "gtk-dark.css"), css)


def _switch_theme():
    current = Gio.Settings.new("org.gnome.desktop.interface").get_string("gtk-theme")
    _set("org.gnome.desktop.interface", "gtk-theme",
         GLib.Variant("s", OUR_THEMES[1] if current == OUR_THEMES[0] else OUR_THEMES[0]))


def _add_import(gtk_css):
    line = CSS_IMPORT.format(THEME_CSS)
    try:
        with open(gtk_css) as f:
            text = f.read()
    except OSError:
        text = ""
    if line in text:
        return
    kept = "".join(l for l in text.splitlines(True) if "/* wallpaper-studio */" not in l)
    _write(gtk_css, line + kept)


def _remove_import(gtk_css):
    try:
        with open(gtk_css) as f:
            text = f.read()
    except OSError:
        return
    kept = "".join(l for l in text.splitlines(True) if "/* wallpaper-studio */" not in l)
    if kept.strip():
        _write(gtk_css, kept)
    else:
        os.remove(gtk_css)


def _reload_gtk(theme):
    # switching through another theme makes running GTK 3 apps reload gtk.css
    _set("org.gnome.desktop.interface", "gtk-theme", GLib.Variant("s", "HighContrast" if theme == "Adwaita" else "Adwaita"))
    Gio.Settings.sync()
    _set("org.gnome.desktop.interface", "gtk-theme", GLib.Variant("s", theme))


def _terminal_profile(p):
    """A 'Wallpaper Studio' profile in GNOME Terminal, made the default."""
    uid_file = os.path.join(CONFIG_DIR, "terminal-profile")
    try:
        with open(uid_file) as f:
            uid = f.read().strip()
    except OSError:
        uid = subprocess.run(["uuidgen"], capture_output=True, text=True, check=False).stdout.strip()
        if not uid:
            return
        _write(uid_file, uid + "\n")
    listed = _dconf("read", f"{TERMINAL}/list")
    if uid not in listed:
        ids = [x.strip(" '") for x in listed.strip("[]").split(",") if x.strip(" '")] or \
              ["b1dcc9dd-5262-4d8d-a863-c897e6d979b9"]   # GNOME Terminal's built-in default profile
        _dconf("write", f"{TERMINAL}/list", str(ids + [uid]))
    _dconf("write", f"{TERMINAL}/default", f"'{uid}'")
    path = f"{TERMINAL}/:{uid}/"
    for key, value in {
        "visible-name": "'Wallpaper Studio'", "use-theme-colors": "false",
        "background-color": f"'{p['paper']}'", "foreground-color": f"'{p['ink']}'",
        "bold-color-same-as-fg": "true", "palette": str(p["ansi"]),
        "cursor-colors-set": "true", "cursor-background-color": f"'{p['accent']}'",
        "cursor-foreground-color": f"'{p['paper']}'",
        "highlight-colors-set": "true", "highlight-background-color": f"'{p['accent']}'",
        "highlight-foreground-color": f"'{p['on_accent']}'",
    }.items():
        _dconf("write", path + key, value)


def _lock_screen(still):
    if _set("org.gnome.desktop.screensaver", "picture-uri", GLib.Variant("s", Gio.File.new_for_path(still).get_uri())):
        # the 42 school lock screen reads the picture when its helper starts
        subprocess.run(["systemctl", "--user", "try-restart", "codam-web-greeter.service"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def apply_theme():
    """Recolour the session from the current wallpaper, in the current light/dark mode."""
    with locked():
        state, config = load_state(), load_config()
        if "palette" not in state:
            return
        mode = effective_mode(config)
        dark = mode == "dark"
        p = state["palette"][mode]
        _save_originals()

        _write(THEME_CSS, palette.gtk_css(p, dark, config["glass"]))
        _write_themes(dark)
        # GTK 3 apps take the colours from the theme, live. libadwaita apps ignore themes and only
        # read gtk-4.0/gtk.css when they start, so it imports the colours too (the Wallpaper Studio
        # window reloads it itself). A gtk-3.0 import would pin GTK 3 apps to their start-up colours.
        _remove_import(os.path.join(HOME, ".config", "gtk-3.0", "gtk.css"))
        _add_import(os.path.join(HOME, ".config", "gtk-4.0", "gtk.css"))

        _set("org.gnome.desktop.interface", "color-scheme", GLib.Variant("s", "prefer-dark" if dark else "default"))
        _switch_theme()
        _set("org.gnome.desktop.background", "primary-color", GLib.Variant("s", p["paper"]))
        if config["terminal"] and shutil.which("dconf"):
            _terminal_profile(p)
        if config["lock_screen"] and state.get("still"):
            _lock_screen(state["still"])
        Gio.Settings.sync()

        state["mode"] = mode
        _save_state(state)
        _run_hooks(p, mode)


def _run_hooks(p, mode):
    """Your own scripts in ~/.config/wallpaper-studio/hooks run after every recolour (see README).

    Each executable file there gets the palette in WS_* variables and runs in the background."""
    try:
        names = sorted(os.listdir(HOOKS))
    except OSError:
        return
    env = {**os.environ, "WS_MODE": mode, "WS_STATE": STATE}
    env.update({f"WS_{k.upper()}": v for k, v in p.items() if k != "ansi"})
    env.update({f"WS_ANSI_{i}": c for i, c in enumerate(p["ansi"])})
    for name in names:
        path = os.path.join(HOOKS, name)
        if not name.startswith(".") and os.path.isfile(path) and os.access(path, os.X_OK):
            subprocess.Popen([path], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)


def restore():
    """Put back every setting as it was before Wallpaper Studio, and take the wallpaper away."""
    with locked():
        saved = _read_json(ORIGINALS, None)
        if saved:
            for name, value in saved.items():
                if name == "terminal-default":
                    _dconf("write", f"{TERMINAL}/default", value) if value else _dconf("reset", f"{TERMINAL}/default")
                elif name == "terminal-list":
                    _dconf("write", f"{TERMINAL}/list", value) if value else _dconf("reset", f"{TERMINAL}/list")
                else:
                    schema, key = name.split(" ")
                    _set(schema, key, GLib.Variant.parse(None, value, None, None))
            os.remove(ORIGINALS)
        uid_file = os.path.join(CONFIG_DIR, "terminal-profile")
        if os.path.exists(uid_file):
            with open(uid_file) as f:
                _dconf("reset", "-f", f"{TERMINAL}/:{f.read().strip()}/")
            os.remove(uid_file)
        for version in ("gtk-3.0", "gtk-4.0"):
            _remove_import(os.path.join(HOME, ".config", version, "gtk.css"))
        with contextlib.suppress(FileNotFoundError):
            os.remove(THEME_CSS)
        theme = Gio.Settings.new("org.gnome.desktop.interface").get_string("gtk-theme")
        if theme in OUR_THEMES:          # nothing was saved to go back to
            _set("org.gnome.desktop.interface", "gtk-theme", GLib.Variant("s", "Adwaita"))
        else:
            _reload_gtk(theme)
        Gio.Settings.sync()
        for name in OUR_THEMES:
            shutil.rmtree(os.path.join(THEMES_DIR, name), ignore_errors=True)
        _save_state({})
