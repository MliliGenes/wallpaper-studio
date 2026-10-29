"""User-owned styles are seeded once; shipped defaults remain available as fallbacks."""
import os
from pathlib import Path

from . import storage

DIRECTORY = Path(__file__).with_name("styles")


def ensure_user_styles():
    from .layout import ensure_layout
    ensure_layout()
    os.makedirs(storage.CONFIG_DIR, exist_ok=True)
    for name in ("app.css", "widgets.css"):
        try:
            with open(os.path.join(storage.CONFIG_DIR, name), "x") as target:
                target.write(f"/* Your overrides; changes reload automatically. See docs/widgets.md. */\n")
        except FileExistsError:
            pass
