"""Allowlisted cache cleaner. Run python3 -m wallpaper_studio.cleaner to preview."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import stat
import subprocess

# Never include profiles, installed extensions, WebStorage, or Git repositories.
CACHES = (
    ('.config/Code/CachedExtensionVSIXs', 'code'),
    ('.config/Code/CachedData', 'code'),
    ('.config/Code/Cache', 'code'),
    ('.config/Code/Code Cache', 'code'),
    ('.config/Code/GPUCache', 'code'),
    ('.cache/mozilla', 'firefox'),
    ('snap/firefox/common/.cache', 'firefox'),
    ('.cache/mesa_shader_cache', 'shaders'),
)


def eligible(home, relative):
    path = home / relative
    # Reject symlinks in every component; never traverse relocated application data.
    for parent in (path, *path.parents):
        if parent == home:
            break
        if parent.is_symlink():
            return None
    return path if path.is_dir() else None


def size(path):
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for name in files:
            try:
                info = (Path(root) / name).lstat()
                if stat.S_ISREG(info.st_mode):
                    total += info.st_blocks * 512
            except FileNotFoundError:
                pass
    return total


def run_cleaner(apply=False, home=None):
    home = Path(home or Path.home()).absolute()
    running = set(subprocess.check_output(['ps', '-u', str(os.getuid()), '-o', 'comm='], text=True).split())
    lines, total = [], 0
    for relative, app in CACHES:
        path = eligible(home, relative)
        if path is None:
            continue
        if (app == 'code' and running & {'code', 'code-insiders'}) or (app == 'firefox' and any('firefox' in p for p in running)):
            lines.append(f'Skipped (app running): {relative}')
            continue
        amount = size(path)
        if apply:
            # Keep the root directory and its permissions. rmtree does not follow symlinks.
            for child in path.iterdir():
                if child.is_symlink() or not child.is_dir():
                    child.unlink()
                else:
                    shutil.rmtree(child)
        total += amount
        lines.append(f'{amount / 1024**2:.1f} MiB  {relative}')
    action = 'Removed' if apply else 'Available'
    return f'{action}: {total / 1024**2:.1f} MiB\n' + '\n'.join(lines)


class CleanerModel:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.status = 'Scan to estimate removable caches.'

    def start(self, apply=False):
        if self.future is None:
            self.status = 'Cleaning…' if apply else 'Scanning…'
            self.future = self.pool.submit(run_cleaner, apply)

    def view(self):
        if self.future is not None and self.future.done():
            try:
                self.status = self.future.result()
            except Exception as error:
                self.status = f'Cleanup failed: {error}'
            self.future = None
        return self.status, self.future is not None

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Remove allowlisted cache contents')
    parser.add_argument('--gui', action='store_true', help='Open a GNOME cleanup dialog')
    args = parser.parse_args()
    if args.gui:
        preview = run_cleaner()
        choice = subprocess.run(['zenity', '--question', '--title=Home Cleaner', '--width=620',
                                 '--no-markup', '--text=' + preview,
                                 '--ok-label=Clean caches', '--cancel-label=Close'])
        if choice.returncode == 0:
            result = run_cleaner(True)
            subprocess.run(['zenity', '--info', '--no-markup', '--title=Home Cleaner', '--text=' + result])
    else:
        print(run_cleaner(args.apply))


if __name__ == '__main__':
    main()
