"""Installer-only bulk-data migration. Keep canonical links stable across upgrades."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from . import storage

APP_ID = "io.github.WallpaperStudio"
MARKER = ".wallpaper-studio-install.json"
BASE_THEMES = ("adw-gtk3", "adw-gtk3-dark")


def remove_path(path):
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def publish_link(link, target):
    """Replace a legacy directory only after its replacement is ready; roll back on error."""
    link, target = Path(link), Path(target)
    if link == target:
        return
    if link.is_symlink() and link.resolve() == target.resolve():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = link.with_name(f".{link.name}-link-{token}")
    backup = link.with_name(f".{link.name}-previous-{token}")
    moved = False
    try:
        temporary.symlink_to(target, target_is_directory=True)
        if link.exists() and not link.is_symlink():
            link.rename(backup)
            moved = True
        try:
            os.replace(temporary, link)
        except BaseException:
            if moved:
                backup.rename(link)
            raise
    finally:
        if temporary.is_symlink():
            temporary.unlink()
    if moved:
        remove_path(backup)


def migrate_directory(link, target):
    """Copy first, then publish a link and free the former home directory."""
    link, target = Path(link), Path(target)
    if link == target:
        target.mkdir(parents=True, exist_ok=True)
        return
    if link.is_symlink() and link.resolve() == target.resolve():
        target.mkdir(parents=True, exist_ok=True)
        return
    if link.exists():
        if not link.is_dir():
            raise ValueError(f"Expected an application directory: {link}")
        def newest(source, destination):
            destination = Path(destination)
            if not destination.exists() or os.stat(source).st_mtime_ns > destination.stat().st_mtime_ns:
                shutil.copy2(source, destination)
            return str(destination)
        shutil.copytree(link, target, dirs_exist_ok=True, copy_function=newest)
    else:
        target.mkdir(parents=True, exist_ok=True)
    publish_link(link, target)


def link_themes(paths):
    for name in BASE_THEMES:
        link, target = Path(paths.theme_links) / name, Path(paths.themes) / name
        if link.exists() or target.exists():
            migrate_directory(link, target)


def install(source, paths, interpreter):
    source, target = Path(source), Path(paths.app)
    for name in ("wallpaper_studio", "wallpapers", "wallpaper-studio"):
        if not (source / name).exists():
            raise ValueError(f"Missing installation source: {source / name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".wallpaper-studio-install-", dir=target.parent))
    backup = target.with_name(f".wallpaper-studio-previous-{uuid.uuid4().hex}")
    moved = False
    try:
        shutil.copytree(source / "wallpaper_studio", staging / "wallpaper_studio",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(source / "wallpapers", staging / "wallpapers")
        shutil.copy2(source / "wallpaper-studio", staging / "wallpaper-studio")
        launcher = staging / "wallpaper-studio"
        lines = launcher.read_text().splitlines(keepends=True)
        launcher.write_text(f"#!{interpreter}\n" + "".join(lines[1:]))
        (staging / MARKER).write_text(json.dumps({"app_id": APP_ID, **asdict(paths)}, indent=2) + "\n")
        migrate_directory(paths.cache_link, paths.cache)
        link_themes(paths)
        if target.exists() or target.is_symlink():
            target.rename(backup)
            moved = True
        try:
            staging.rename(target)
        except BaseException:
            if moved:
                backup.rename(target)
            raise
        try:
            publish_link(paths.install_link, target)
        except BaseException:
            remove_path(target)
            if moved:
                backup.rename(target)
            raise
        if moved:
            remove_path(backup)
    finally:
        if staging.exists():
            remove_path(staging)


def helper_pattern(paths):
    canonical = Path(paths.install_link)
    launchers = {str(canonical / "wallpaper-studio"), str(Path(paths.app) / "wallpaper-studio"),
                 str(canonical.resolve() / "wallpaper-studio")}
    # pkill/pgrep use POSIX ERE, which does not support Python's (?:...) groups.
    return r"^[^ ]+ (" + "|".join(re.escape(path) for path in sorted(launchers)) + r") desktop$|^[^ ]*python3[^ ]* -m wallpaper_studio desktop$"


def uninstall(paths):
    """Only remove bulk locations identified by this app's installation marker."""
    marker = Path(paths.install_link) / MARKER
    if marker.exists():
        info = json.loads(marker.read_text())
        if info.get("app_id") != APP_ID:
            raise ValueError("Refusing to remove an installation with an unknown app marker")
        actual = Path(paths.install_link).resolve()
        if actual != Path(info["app"]).resolve():
            raise ValueError("Installation path does not match its marker")
        cache = Path(info["cache"])
        cache_link = Path(info["cache_link"])
        if cache.resolve() not in {Path(paths.cache).resolve(), Path(paths.cache_link).resolve()}:
            raise ValueError("Cache path does not match this installation's storage locations")
        if cache_link != cache and cache_link.is_symlink() and cache_link.resolve() == cache.resolve():
            cache_link.unlink()
        remove_path(cache)
        link = Path(paths.install_link)
        if link.is_symlink():
            link.unlink()
        remove_path(actual)
    else:
        # Legacy installation: remove the canonical app directory and cache only.
        remove_path(paths.install_link)
        remove_path(paths.cache_link)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("paths", "install", "link-themes", "helper-pattern", "uninstall"))
    parser.add_argument("--source", default=".")
    parser.add_argument("--python", default="/usr/bin/python3")
    args = parser.parse_args(argv)
    paths = storage.PATHS
    if args.command == "paths":
        print(paths.app)
        print(paths.cache)
        print(paths.themes)
    elif args.command == "helper-pattern":
        print(helper_pattern(paths))
    elif args.command == "install":
        install(args.source, paths, args.python)
    elif args.command == "link-themes":
        link_themes(paths)
    else:
        uninstall(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
