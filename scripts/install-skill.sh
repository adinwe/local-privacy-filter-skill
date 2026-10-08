#!/bin/zsh
set -eu
REPOSITORY_ROOT="${0:A:h:h}"
SOURCE="$REPOSITORY_ROOT/skills/local-privacy-filter"
INSTALL_AGENT="codex"
CUSTOM_SKILLS_PARENT=""
AGENT_SPECIFIED=0
DIRECTORY_SPECIFIED=0
usage() {
  print 'Usage: install-skill.sh [--agent codex|claude] [--skills-dir DIRECTORY]'
}
invalid_arguments() {
  print -u2 -- "$1"
  usage >&2
  exit 2
}
while (( $# > 0 )); do
  case "$1" in
    --agent)
      (( $# >= 2 )) || invalid_arguments '--agent requires codex or claude.'
      (( AGENT_SPECIFIED == 0 )) || invalid_arguments 'Specify --agent only once.'
      [[ "$2" == codex || "$2" == claude ]] || invalid_arguments 'Supported agents are codex and claude.'
      INSTALL_AGENT="$2"
      AGENT_SPECIFIED=1
      shift 2
      ;;
    --skills-dir)
      (( $# >= 2 )) || invalid_arguments '--skills-dir requires a directory.'
      (( DIRECTORY_SPECIFIED == 0 )) || invalid_arguments 'Specify --skills-dir only once.'
      [[ -n "$2" && "$2" != --* ]] || invalid_arguments '--skills-dir requires a nonempty directory.'
      CUSTOM_SKILLS_PARENT="$2"
      DIRECTORY_SPECIFIED=1
      shift 2
      ;;
    --help|-h)
      (( $# == 1 && AGENT_SPECIFIED == 0 && DIRECTORY_SPECIFIED == 0 )) || invalid_arguments 'Use --help on its own.'
      usage
      exit 0
      ;;
    *) invalid_arguments "Unknown argument: $1" ;;
  esac
done
if (( DIRECTORY_SPECIFIED )); then
  SKILLS_PARENT="$CUSTOM_SKILLS_PARENT"
elif [[ "$INSTALL_AGENT" == claude ]]; then
  SKILLS_PARENT="$HOME/.claude/skills"
else
  SKILLS_PARENT="${CODEX_HOME:-$HOME/.codex}/skills"
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
if [[ "$INSTALL_AGENT" == claude ]]; then
  print 'Open a new Claude Code session, then enter:'
  print '/local-privacy-filter Set up the local filter on this Mac and open it.'
else
  print 'Open a new Codex chat (restart Codex if needed), then send:'
  print 'Use $local-privacy-filter to set up the local filter on this Mac and open it.'
fi
print 'First setup downloads dependencies and the public model. Filtering runs locally.'
