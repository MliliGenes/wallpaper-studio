"""Validated preferences. This module deliberately has no GTK or display dependency."""
import json
import math
import os

from .storage import BUILT_IN, CONFIG, locked, read_json, write

DEFAULT_CONFIG = {
    "mode": "auto",
    "light_from": 7,
    "dark_from": 19,
    "folder": BUILT_IN,
    "rotate_hours": 0,
    "glass": False,
    "terminal": True,
    "lock_screen": True,
    "clock": True,
    "clock_format": "%H:%M",
    "clock_date_format": "%A, %d %B",
    "clock_top": 32,
    "awake_method": "key",  # GNOME inhibitor plus an XTEST F15 tap; "inhibit" disables taps
    "awake_interval": 60,
}

DESCRIPTIONS = {
    "mode": "light, dark or auto",
    "light_from": "Hour light mode begins (0–23)",
    "dark_from": "Hour dark mode begins (0–23); may cross midnight",
    "folder": "Wallpaper folder",
    "rotate_hours": "Hours between random wallpapers (0 disables rotation)",
    "glass": "Transparent app windows",
    "terminal": "Recolour GNOME Terminal",
    "lock_screen": "Update the lock-screen picture",
    "clock": "Show the desktop clock",
    "clock_format": "strftime time format",
    "clock_date_format": "strftime date format; empty hides the date",
    "clock_top": "Clock offset below the primary monitor's work area, in pixels",
    "awake_method": "key (inhibitor + F15 tap) or inhibit (GNOME only)",
    "awake_interval": "Seconds between keep-awake taps (10–300)",
}


def validate(key, value):
    if key not in DEFAULT_CONFIG:
        raise ValueError(f"unknown setting: {key}; run 'wallpaper-studio config list'")
    default = DEFAULT_CONFIG[key]
    if isinstance(default, bool):
        if isinstance(value, str) and value.lower() in ("true", "false", "on", "off", "1", "0"):
            value = value.lower() in ("true", "on", "1")
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
    elif key in ("light_from", "dark_from", "clock_top", "awake_interval"):
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(f"{key} must be an integer") from None
        lo, hi = (0, 23) if key.endswith("_from") else (10, 300) if key == "awake_interval" else (0, 2000)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f"{key} must be an integer from {lo} to {hi}")
    elif key == "rotate_hours":
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                raise ValueError("rotate_hours must be a nonnegative number") from None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("rotate_hours must be a nonnegative finite number")
    else:
        if not isinstance(value, str) or "\0" in value or "\n" in value:
            raise ValueError(f"{key} must be a single-line string")
        if key == "mode" and value not in ("light", "dark", "auto"):
            raise ValueError("mode must be light, dark or auto")
        if key == "awake_method" and value not in ("key", "inhibit"):
            raise ValueError("awake_method must be key or inhibit")
        if key == "folder":
            value = os.path.abspath(os.path.expanduser(value))
            if not os.path.isdir(value):
                raise ValueError(f"folder does not exist: {value}")
        if key in ("clock_format", "clock_date_format") and (len(value) > 128 or (key == "clock_format" and not value)):
            raise ValueError(f"{key} must be {'1–128' if key == 'clock_format' else '0–128'} characters")
    return value


def load_config():
    result = DEFAULT_CONFIG.copy()
    for key, value in read_json(CONFIG, {}).items():
        try:
            result[key] = validate(key, value)
        except ValueError:
            pass  # a stale or hand-edited value must not crash the login helper
    return result


def save_config(**changes):
    changes = {key: validate(key, value) for key, value in changes.items()}
    with locked():
        config = {**load_config(), **changes}
        write(CONFIG, json.dumps(config, indent=2) + "\n")
    return config


def reset_config(key=None):
    if key is not None:
        if key not in DEFAULT_CONFIG:
            raise ValueError(f"unknown setting: {key}")
        return save_config(**{key: DEFAULT_CONFIG[key]})
    return save_config(**DEFAULT_CONFIG)


def is_light_hour(hour, light_from, dark_from):
    """Half-open interval with support for night shifts crossing midnight."""
    if light_from < dark_from:
        return light_from <= hour < dark_from
    if light_from > dark_from:
        return hour >= light_from or hour < dark_from
    return False  # equal hours: always dark
