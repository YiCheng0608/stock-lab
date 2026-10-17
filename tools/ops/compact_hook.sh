#!/usr/bin/env bash
# PreCompact hook: count context compactions per Claude Code session.
# Writes <STOCK_DATA_DIR>/logs/compactions/<session_id>.count (one integer).
# The coordinator reads its own file during patrol to decide on handoff
# (docs/GITHUB_WORKFLOW.md, "統籌 session").
set -u
input="$(cat 2>/dev/null || true)"
session_id="$(printf '%s' "$input" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)"/\1/')"
[ -n "$session_id" ] || exit 0
case "$session_id" in *[!A-Za-z0-9_-]*) exit 0 ;; esac
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}"
dir="$data_dir/logs/compactions"
mkdir -p "$dir" 2>/dev/null || exit 0
file="$dir/$session_id.count"
count=0
if [ -f "$file" ]; then
  count="$(tr -dc '0-9' < "$file")"
  count="${count:-0}"
fi
printf '%s\n' "$((count + 1))" > "$file"
exit 0
