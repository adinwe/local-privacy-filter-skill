#!/bin/zsh
set -e
PRIVACY_FILTER_ROOT="${0:A:h}"
if [[ ! -x "$PRIVACY_FILTER_ROOT/.venv/bin/python" ]]; then
  print "The local privacy filter environment is missing. Complete local setup first."
  exit 1
fi
exec "$PRIVACY_FILTER_ROOT/.venv/bin/python" "$PRIVACY_FILTER_ROOT/launch.py" "$@"
