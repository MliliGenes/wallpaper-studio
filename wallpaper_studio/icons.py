"""Offline Font Awesome Free SVG catalog; safe to import without GTK."""
from functools import lru_cache
from pathlib import Path
import re

DIRECTORY = Path(__file__).with_name("assets") / "fontawesome" / "solid"


def available_icons():
    return tuple(sorted(path.stem for path in DIRECTORY.glob("*.svg")))


def validate_icon(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Icon names must be simple names such as 'play' or 'volume-high'")
    if not (DIRECTORY / f"{name}.svg").is_file():
        raise ValueError(f"Unknown icon: {name}; see wallpaper_studio.icons.available_icons()")
    return name


@lru_cache(maxsize=128)
def svg_data(name):
    return (DIRECTORY / f"{validate_icon(name)}.svg").read_bytes()
