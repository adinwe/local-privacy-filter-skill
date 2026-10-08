#!/bin/zsh
set -eu
REPOSITORY_ROOT="${0:A:h}"
exec "$REPOSITORY_ROOT/skills/local-privacy-filter/assets/app/Privacy Filter.command" "$@"
