#!/bin/zsh
set -eu
REPOSITORY_ROOT="${0:A:h}"
"$REPOSITORY_ROOT/scripts/install-skill.sh" --agent claude
print '\nPress Return to close this window.'
read -r REPLY
