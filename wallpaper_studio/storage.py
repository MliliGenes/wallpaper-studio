"""Small, GTK-independent file store shared by the CLI, window and desktop helper."""
import contextlib
import fcntl
import json
import os
import tempfile

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "wallpaper-studio")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "wallpaper-studio")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
STATE = os.path.join(CONFIG_DIR, "state.json")
ORIGINALS = os.path.join(CONFIG_DIR, "originals.json")
THEME_CSS = os.path.join(CONFIG_DIR, "theme.css")
APP_CSS = os.path.join(CONFIG_DIR, "app.css")
WIDGETS_CSS = os.path.join(CONFIG_DIR, "widgets.css")
HOOKS = os.path.join(CONFIG_DIR, "hooks")
LOCK = os.path.join(CONFIG_DIR, ".lock")
HELPER_LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wallpaper-studio.lock")
AWAKE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wallpaper-studio-awake.json")
BUILT_IN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wallpapers")


def read_json(path, default):
    try:
        with open(path) as f:
            result = json.load(f)
        return result if isinstance(result, dict) else default
    except (OSError, ValueError):
        return default


def write(path, text):
    """Replace atomically so readers never see a half-written file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


@contextlib.contextmanager
def locked():
    """Serialize read/modify/write operations across processes. Not reentrant."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
