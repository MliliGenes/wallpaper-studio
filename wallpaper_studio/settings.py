"""Validated preferences. This module deliberately has no GTK or display dependency."""
import json
import math
import os
import re

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
    "lock_password": "",
    "clock": True,
    "clock_format": "%H:%M",
    "clock_date_format": "%A, %d %B",
    "clock_top": 32,
    "widgets_enabled": True,
    "layout_edit": False,
    "layout_grid": True,
    "layout_grid_size": 32,
    "layout_grid_gap": 8,
    "widget_blur": True,
    "widget_blur_radius": 24,
    "logtime_username": "",
    "logtime_goal": 180,
    "awake_method": "mouse",  # GNOME inhibitor plus a pointer round trip; "inhibit" disables movement
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
    "lock_password": "Password for Wallpaper Studio's optional lock overlay (empty disables it)",
    "clock": "Show the desktop clock",
    "clock_format": "strftime time format",
    "clock_date_format": "strftime date format; empty hides the date",
    "clock_top": "Clock offset below the primary monitor's work area, in pixels",
    "widgets_enabled": "Show the desktop widget layout",
    "layout_edit": "Arrange mode: drag inside to move, resize any edge/corner, scroll to scale text",
    "layout_grid": "Snap widget positions and sizes to the grid",
    "layout_grid_size": "Grid cell size in pixels (8–128)",
    "layout_grid_gap": "Space between grid cells in pixels (0–64)",
    "widget_blur": "Frosted wallpaper backdrop behind widget cards",
    "widget_blur_radius": "Gaussian blur strength in wallpaper pixels (0–64; 0 disables blur)",
    "logtime_username": "1337 login for the Logtime widget; empty pauses requests",
    "logtime_goal": "Target hours per Logtime period (default 180; configurable)",
    "awake_method": "mouse (inhibitor + pointer round trip) or inhibit (GNOME only)",
    "awake_interval": "Seconds between keep-awake movements (10–300)",
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
    elif key in ("light_from", "dark_from", "clock_top", "awake_interval", "widget_blur_radius", "layout_grid_size", "layout_grid_gap"):
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(f"{key} must be an integer") from None
        lo, hi = (8, 128) if key == "layout_grid_size" else (0, 64) if key == "layout_grid_gap" else (0, 23) if key.endswith("_from") else (10, 300) if key == "awake_interval" else (0, 64) if key == "widget_blur_radius" else (0, 2000)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f"{key} must be an integer from {lo} to {hi}")
    elif key in ("rotate_hours", "logtime_goal"):
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                raise ValueError(f"{key} must be a number") from None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a nonnegative finite number")
        if key == "logtime_goal" and not 0 < value <= 10000:
            raise ValueError("logtime_goal must be greater than 0 and at most 10000 hours")
    else:
        if not isinstance(value, str) or "\0" in value or "\n" in value:
            raise ValueError(f"{key} must be a single-line string")
        if key == "mode" and value not in ("light", "dark", "auto"):
            raise ValueError("mode must be light, dark or auto")
        if key == "logtime_username":
            value = value.strip()
            if value and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
                raise ValueError("logtime_username must contain letters, numbers, underscores or hyphens (1–64 characters)")
        if key == "lock_password" and len(value) > 128:
            raise ValueError("lock_password must be at most 128 characters")
        if key == "awake_method":
            if value == "key":  # migrate existing preferences from the former F15 implementation
                value = "mouse"
            if value not in ("mouse", "inhibit"):
                raise ValueError("awake_method must be mouse or inhibit")
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
