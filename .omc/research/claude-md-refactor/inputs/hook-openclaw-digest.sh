#!/usr/bin/env bash
# SessionStart hook: inject latest OpenClaw memory digest into Claude context.
# Bounded to ~60 lines. No files are written. Refreshes automatically each session.

set -euo pipefail

MEM_DIR="/root/.openclaw/workspace/memory"
MAX_LINES=60

latest=$(find "$MEM_DIR" -maxdepth 1 -type f -name '2[0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]*.md' -printf '%T@ %p\n' 2>/dev/null \
  | sort -nr | head -1 | cut -d' ' -f2-)

if [[ -z "${latest:-}" || ! -f "$latest" ]]; then
  exit 0
fi

fname=$(basename "$latest")

printf '=== OpenClaw memory digest (%s, head -%d) ===\n' "$fname" "$MAX_LINES"
head -n "$MAX_LINES" "$latest"
printf '\n=== end digest — full file: %s ===\n' "$latest"
