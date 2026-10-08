#!/bin/sh
# Portable bootstrap: select Python automatically, then delegate all setup.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd -- "$APP_DIR/../.." && pwd)
INSTALL_SCRIPT="$SKILL_DIR/scripts/install.py"
if [ ! -f "$INSTALL_SCRIPT" ]; then
  printf '%s\n' 'The skill package is incomplete. Download a fresh copy.' >&2
  exit 1
fi

# An existing app is always checked with its own interpreter and never replaced.
if [ -x "$APP_DIR/.venv/bin/python" ]; then
  exec "$APP_DIR/.venv/bin/python" -B "$INSTALL_SCRIPT" "$@"
fi
for SETUP_ARG in "$@"; do
  if [ "$SETUP_ARG" = '--check-only' ]; then
    CHECK_PYTHON=$(command -v python3 || true)
    if [ -n "$CHECK_PYTHON" ] && [ "$CHECK_PYTHON" != '/usr/bin/python3' ]; then
      exec "$CHECK_PYTHON" -B "$INSTALL_SCRIPT" "$@"
    fi
    printf '%s\n' 'No app environment is installed. No files were changed and no downloads were attempted.'
    exit 1
  fi
done
for LOCAL_FOLDER in .venv .python .setup-cache models; do
  if [ -L "$APP_DIR/$LOCAL_FOLDER" ]; then
    printf '%s\n' 'An app installation folder points elsewhere. Use a fresh skill folder; setup will not change that installation.' >&2
    exit 1
  fi
done
if [ -e "$APP_DIR/.venv" ]; then
  printf '%s\n' 'An unfinished environment folder already exists. Preserve it and set up a fresh skill folder.' >&2
  exit 1
fi
if [ "$(uname -s)" != 'Darwin' ] || [ "$(uname -m)" != 'arm64' ]; then
  printf '%s\n' 'This package requires an Apple Silicon Mac running macOS 14 or newer.' >&2
  exit 1
fi
MAC_VERSION=$(/usr/bin/sw_vers -productVersion)
MAC_MAJOR=${MAC_VERSION%%.*}
if [ "$MAC_MAJOR" -lt 14 ]; then
  printf '%s\n' 'This package requires macOS 14 or newer.' >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Install uv first, then rerun setup. With existing Homebrew: brew install uv.' >&2
  printf '%s\n' 'Official instructions: https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
FREE_KIB=$(df -Pk "$APP_DIR" | awk 'NR == 2 {print $4}')
if [ -z "$FREE_KIB" ] || [ "$FREE_KIB" -lt 6291456 ]; then
  printf '%s\n' 'Setup needs at least 6 GiB free disk space for about 2 GiB of installed files plus downloads and cache.' >&2
  exit 1
fi
export UV_CACHE_DIR="$APP_DIR/.setup-cache"
export UV_PYTHON_INSTALL_DIR="$APP_DIR/.python"
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec uv run --no-project --no-sync --no-env-file --no-config --managed-python --python 3.12 python -B "$INSTALL_SCRIPT" "$@"
