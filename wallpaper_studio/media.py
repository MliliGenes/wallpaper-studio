"""GTK-independent wallpaper discovery shared by graphical and terminal controls."""
import os

from .settings import load_config

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".jxl", ".bmp", ".tif", ".tiff", ".gif")
VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi")


def is_video(path):
    return bool(path) and path.lower().endswith(VIDEO_EXT)


def is_wallpaper(path):
    return path.lower().endswith(IMAGE_EXT + VIDEO_EXT)


def wallpapers(folder=None):
    folder = folder or load_config()["folder"]
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    return [os.path.join(folder, name) for name in names
            if not name.startswith(".") and is_wallpaper(name)
            and os.path.isfile(os.path.join(folder, name))]
