#!/usr/bin/env bash
# Manage the private instance's real workspace config, which lives OUTSIDE git.
#   scripts/private-workspace.sh init       copy the public template into the private directory
#   scripts/private-workspace.sh validate   run the workspace loader/schema on the private directory
#
# Directory: PRIVATE_WORKSPACES_DIR (environment, else the line in .env.private, else
# ./data/private/workspaces). Only that one variable is read from .env.private.
set -euo pipefail

cd "$(dirname "$0")/.."
SLUG="david-moreno"
TEMPLATE="workspaces/$SLUG"

dir="${PRIVATE_WORKSPACES_DIR:-}"
if [[ -z "$dir" && -f .env.private ]]; then
  dir=$(grep -E '^PRIVATE_WORKSPACES_DIR=' .env.private | tail -n1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]$//" || true)
fi
dir="${dir:-./data/private/workspaces}"

cmd_init() {
  local target="$dir/$SLUG"
  if [[ -e "$target" ]]; then
    echo "Already exists, not overwriting: $target"
  else
    mkdir -p "$dir"
    cp -r "$TEMPLATE" "$target"
    echo "Created $target from the public template."
  fi
  cat <<MSG

Next steps:
  1. Edit $target/workspace.yaml (real contact email, prices, CORS origins) and the files in
     $target/knowledge-base/. Set profile.draft to false when the TODO(david) values are gone.
  2. scripts/private-workspace.sh validate
  3. docker compose --env-file .env.private -f docker-compose.yml -f docker-compose.private.yml up -d agent
     (the directory is a read-only bind mount: a restart of the agent is enough to pick up edits)
MSG
}

cmd_validate() {
  [[ -d "$dir" ]] || { echo "Missing $dir. Run: scripts/private-workspace.sh init" >&2; exit 1; }
  local abs
  abs=$(cd "$dir" && pwd)
  # Same loader the agent runs at startup, production rules, on the private directory.
  local code='
import os, sys
from pathlib import Path
from lead_qualifier.workspaces.loader import WorkspaceConfigError, load_workspaces
try:
    registry = load_workspaces(Path(os.environ["WORKSPACES_DIR"]), app_env="production",
                               enabled=frozenset({os.environ["ENABLED_WORKSPACES"]}))
except WorkspaceConfigError as error:
    print(error, file=sys.stderr)
    sys.exit(1)
print("OK:", ", ".join(w.slug for w in registry.all()))
'
  if command -v uv >/dev/null 2>&1; then
    (cd apps/agent && APP_ENV=production WORKSPACES_DIR="$abs" ENABLED_WORKSPACES="$SLUG" uv run python -c "$code")
  elif [[ -x apps/agent/.venv/bin/python ]]; then
    (cd apps/agent && APP_ENV=production WORKSPACES_DIR="$abs" ENABLED_WORKSPACES="$SLUG" .venv/bin/python -c "$code")
  else
    docker run --rm -v "$abs:/srv/private-workspaces:ro" -e APP_ENV=production \
      -e WORKSPACES_DIR=/srv/private-workspaces -e ENABLED_WORKSPACES="$SLUG" \
      leadq-agent:local python -c "$code"
  fi
}

case "${1:-}" in
  init) cmd_init ;;
  validate) cmd_validate ;;
  *) echo "Usage: $0 init | validate" >&2; exit 2 ;;
esac
