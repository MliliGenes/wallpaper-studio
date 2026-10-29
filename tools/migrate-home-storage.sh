#!/usr/bin/env bash
# Move VS Code extensions and user Flatpak data to /goinfre, preserving their home paths.
set -euo pipefail

APPLY=false
if [[ ${1:-} == --apply ]]; then
  APPLY=true
elif [[ $# -gt 0 && ${1:-} != --help && ${1:-} != -h ]]; then
  echo "Usage: $0 [--apply]" >&2
  exit 2
fi
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo "Usage: $0 [--apply]"
  echo "Preview the migration by default; --apply performs it after verification."
  exit 0
fi

HOME_DIR=${HOME:?HOME is not set}
DEST_BASE=/goinfre/$(basename "$HOME_DIR")

migrate_dir() {
  local source=$1 target=$2 backup="${1}.migration-backup"

  if [[ -L $source ]]; then
    if [[ $(readlink -f -- "$source") == $(readlink -m -- "$target") && -d $target ]]; then
      echo "Already migrated: $source"
      return
    fi
    echo "Refusing existing symlink: $source" >&2
    return 1
  fi
  if [[ ! -d $source ]]; then
    echo "Missing source directory: $source" >&2
    return 1
  fi
  if [[ -e $target || -L $target || -e $backup || -L $backup ]]; then
    echo "Destination or backup already exists: $target or $backup" >&2
    return 1
  fi

  mkdir -p -- "$(dirname -- "$target")"
  mkdir -m 700 -- "$target"
  rsync -aH -- "$source/" "$target/"
  # Check file contents and metadata; do not alter either copy during verification.
  if [[ -n $(rsync -aHnci --delete -- "$source/" "$target/") ]]; then
    echo "Copy verification failed; source preserved: $source" >&2
    return 1
  fi

  mv -- "$source" "$backup"
  if ! ln -s -- "$target" "$source"; then
    mv -- "$backup" "$source"
    return 1
  fi
  rm -rf -- "$backup"
  echo "Migrated: $source -> $target"
}

if ! $APPLY; then
  printf 'Would migrate: %s -> %s\n' "$HOME_DIR/.vscode/extensions" "$DEST_BASE/vscode/extensions"
  printf 'Would migrate: %s -> %s\n' "$HOME_DIR/.local/share/flatpak" "$DEST_BASE/flatpak"
  exit 0
fi

if [[ ! -d /goinfre || ! -w /goinfre ]]; then
  echo "/goinfre is not mounted or writable." >&2
  exit 1
fi
if pgrep -u "$(id -u)" -x code >/dev/null || pgrep -u "$(id -u)" -x code-insiders >/dev/null; then
  echo "Close VS Code before migrating its extensions." >&2
  exit 1
fi
if command -v flatpak >/dev/null && [[ -n $(flatpak ps 2>/dev/null) ]]; then
  echo "Close running Flatpak applications before migrating their data." >&2
  exit 1
fi

migrate_dir "$HOME_DIR/.vscode/extensions" "$DEST_BASE/vscode/extensions"
migrate_dir "$HOME_DIR/.local/share/flatpak" "$DEST_BASE/flatpak"
