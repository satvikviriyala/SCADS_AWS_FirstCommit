#!/usr/bin/env bash
set -euo pipefail

# Run this from the root of a clone of satvikviriyala/SCADS_AWS_FirstCommit.
# It copies the planning handoff into the repository without touching .git.

SOURCE_DIR="${1:-../SCADS_AWS_FirstCommit_handoff}"

if [[ ! -d ".git" ]]; then
  echo "ERROR: run from the SCADS_AWS_FirstCommit git repository root." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: handoff directory not found: $SOURCE_DIR" >&2
  exit 1
fi

cp -R "$SOURCE_DIR"/. .
echo "SCADS planning handoff copied into repository."
echo
git status --short
echo
echo "Review the files, then commit with something like:"
echo '  git add README.md CLAUDE.md AGENTS.md MEMORY.md PLAN.md MASTER_PROMPT.md docs phases'
echo '  git commit -m "docs: add SCADS architecture and implementation handoff"'
