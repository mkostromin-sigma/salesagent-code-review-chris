#!/usr/bin/env bash
# Install the salesagent review harness into a salesagent working copy.
# Usage: ./install.sh [TARGET_DIR]   (TARGET_DIR defaults to the current directory)
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$(pwd)}"

if [ ! -f "$TARGET/CLAUDE.md" ] || [ ! -d "$TARGET/src" ]; then
  echo "warning: '$TARGET' doesn't look like a salesagent checkout (no CLAUDE.md / src/)." >&2
  echo "         The review agents reference the target repo's CLAUDE.md, src/, tests/, and skills." >&2
fi

mkdir -p \
  "$TARGET/.claude/agents" \
  "$TARGET/.claude/commands" \
  "$TARGET/.claude/rules/private/memory" \
  "$TARGET/.claude/rules/private/detectors"

cp "$HARNESS_DIR"/.claude/agents/review-*.md             "$TARGET/.claude/agents/"
cp "$HARNESS_DIR"/.claude/commands/full-review.md         "$TARGET/.claude/commands/"
cp "$HARNESS_DIR"/.claude/rules/private/review-charter.md \
   "$HARNESS_DIR"/.claude/rules/private/reviewer-tooling.md "$TARGET/.claude/rules/private/"
cp "$HARNESS_DIR"/.claude/rules/private/detectors/*.py    "$TARGET/.claude/rules/private/detectors/"
cp "$HARNESS_DIR"/.claude/rules/private/memory/*.md       "$TARGET/.claude/rules/private/memory/"

echo "Installed review harness into $TARGET/.claude/"
echo "  agents: $(ls "$TARGET"/.claude/agents/review-*.md | wc -l | tr -d ' ')  |  detectors: $(ls "$TARGET"/.claude/rules/private/detectors/*.py | wc -l | tr -d ' ')  |  memory: $(ls "$TARGET"/.claude/rules/private/memory/*.md | wc -l | tr -d ' ')"
echo "Run a review from the repo root:  /full-review <PR# | path/glob | (empty = working tree)>"
