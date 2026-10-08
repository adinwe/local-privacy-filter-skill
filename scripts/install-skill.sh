#!/bin/zsh
set -eu
REPOSITORY_ROOT="${0:A:h:h}"
SOURCE="$REPOSITORY_ROOT/skills/local-privacy-filter"
SKILLS_PARENT="${CODEX_HOME:-$HOME/.codex}/skills"
if (( $# > 0 )); then
  if [[ "$1" != "--skills-dir" || $# != 2 ]]; then
    print -u2 'Usage: install-skill.sh [--skills-dir DIRECTORY]'
    exit 2
  fi
  SKILLS_PARENT="$2"
fi
DESTINATION="$SKILLS_PARENT/local-privacy-filter"
if [[ ! -f "$SOURCE/SKILL.md" || ! -f "$SOURCE/assets/app/privacy_filter/engine.py" ]]; then
  print -u2 "The downloaded package is incomplete. Download the complete repository ZIP."
  exit 1
fi
mkdir -p "$SKILLS_PARENT"
INSTALL_STAGE=$(mktemp -d "$SKILLS_PARENT/.local-privacy-filter-install.XXXXXX")
trap '[[ ! -d "$INSTALL_STAGE" ]] || rm -rf -- "$INSTALL_STAGE"' EXIT
while IFS= read -r -d '' SOURCE_FILE; do
  RELATIVE_FILE="${SOURCE_FILE#$SOURCE/}"
  mkdir -p "$INSTALL_STAGE/${RELATIVE_FILE:h}"
  cp -p -- "$SOURCE_FILE" "$INSTALL_STAGE/$RELATIVE_FILE"
done < <(/usr/bin/find "$SOURCE" \( -type d \( -name .venv -o -name .python -o -name models -o -name .setup-cache -o -name .document-setup-cache -o -name .runtime -o -name __pycache__ -o -name .git \) -prune \) -o \( -type f ! -name '*.pyc' ! -name '.DS_Store' -print0 \))
if [[ -e "$DESTINATION" || -L "$DESTINATION" ]]; then
  BACKUP="$SKILLS_PARENT/local-privacy-filter.backup-$(date +%Y%m%d-%H%M%S)-${RANDOM}"
  mv -- "$DESTINATION" "$BACKUP"
  print "Your previous skill was preserved at: $BACKUP"
fi
mv -- "$INSTALL_STAGE" "$DESTINATION"
print "Installed the skill at: $DESTINATION"
print 'Open a new Codex chat (restart Codex if needed), then send:'
print 'Use $local-privacy-filter to set up the local filter on this Mac and open it.'
print 'First setup downloads dependencies and the public model. Filtering runs locally.'
