#!/usr/bin/env bash
# Install this repo as a local Cursor plugin.
# Usage: ./install.sh
# Symlinks (or copies) this checkout to ~/.cursor/plugins/local/salesagent-review-harness
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="salesagent-review-harness"
LOCAL_PLUGINS="${HOME}/.cursor/plugins/local"
DEST="${LOCAL_PLUGINS}/${PLUGIN_NAME}"

require_file() {
  if [ ! -e "$1" ]; then
    echo "error: missing required plugin file: $1" >&2
    exit 1
  fi
}

require_file "${HARNESS_DIR}/.cursor-plugin/plugin.json"
require_file "${HARNESS_DIR}/skills/code-review-chris/SKILL.md"
require_file "${HARNESS_DIR}/skills/code-review-chris/references/review-charter.md"
require_file "${HARNESS_DIR}/skills/code-review-chris/references/reviewer-tooling.md"
require_file "${HARNESS_DIR}/skills/code-review-chris/scripts/disposition_ledger.py"

agent_count="$(find "${HARNESS_DIR}/agents" -maxdepth 1 -name 'review-*.md' | wc -l | tr -d ' ')"
if [ "${agent_count}" -lt 8 ]; then
  echo "error: expected ≥8 agents/review-*.md, found ${agent_count}" >&2
  exit 1
fi

detector_count="$(find "${HARNESS_DIR}/skills/code-review-chris/scripts" -maxdepth 1 -name '*.py' | wc -l | tr -d ' ')"
if [ "${detector_count}" -lt 10 ]; then
  echo "error: expected ≥10 detector scripts, found ${detector_count}" >&2
  exit 1
fi

# Soft-warn when cwd does not look like salesagent — reviews still need that workspace open.
if [ ! -f "${PWD}/AGENTS.md" ] && [ ! -f "${PWD}/CLAUDE.md" ]; then
  echo "note: current directory does not look like a salesagent checkout (no AGENTS.md / CLAUDE.md)." >&2
  echo "      Install will succeed; open a salesagent workspace when running /code-review-chris." >&2
elif [ ! -d "${PWD}/src" ]; then
  echo "note: current directory has AGENTS.md/CLAUDE.md but no src/ — confirm you are in salesagent." >&2
fi

mkdir -p "${LOCAL_PLUGINS}"

if [ -L "${DEST}" ] || [ -e "${DEST}" ]; then
  if [ -L "${DEST}" ]; then
    current="$(readlink "${DEST}")"
    if [ "${current}" = "${HARNESS_DIR}" ]; then
      echo "Already installed: ${DEST} → ${HARNESS_DIR}"
    else
      rm "${DEST}"
      ln -s "${HARNESS_DIR}" "${DEST}"
      echo "Updated symlink: ${DEST} → ${HARNESS_DIR}"
    fi
  else
    echo "error: ${DEST} exists and is not a symlink. Remove it and re-run." >&2
    exit 1
  fi
else
  ln -s "${HARNESS_DIR}" "${DEST}"
  echo "Installed: ${DEST} → ${HARNESS_DIR}"
fi

echo "  agents: ${agent_count}  |  detectors: ${detector_count}  |  skill: code-review-chris"
echo
echo "Next steps:"
echo "  1. Reload Cursor (or open Customize → Plugins) so the local plugin is discovered."
echo "  2. Open a salesagent working copy as the workspace."
echo "  3. Run:  /code-review-chris <PR# | path/glob | (empty = working tree)>"
echo
echo "HARNESS_ROOT for agents/detectors: ${HARNESS_DIR}"
