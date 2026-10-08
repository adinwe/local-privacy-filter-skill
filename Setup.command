#!/bin/zsh
set -eu
REPOSITORY_ROOT="${0:A:h}"
"$REPOSITORY_ROOT/skills/local-privacy-filter/assets/app/setup.sh" "$@"
print '\nPress Return to close this window.'
read -r REPLY
