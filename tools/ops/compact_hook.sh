#!/usr/bin/env bash
# PreCompact hook: count context compactions per Claude Code session.
# Writes <STOCK_DATA_DIR>/logs/compactions/<session_id>.count (one integer) and
# appends one line per compaction to <session_id>.log: the UTC time and the
# hook's trigger (auto or manual), e.g. "2026-10-28T01:23:45Z trigger=auto"
# (#316). Every session writes them, engineers too; the coordinator's are the
# ones whose session id its heartbeat names. The coordinator reads its own count
# during patrol to decide on handoff (docs/GITHUB_WORKFLOW.md, "統籌 session").
# Test hook: COMPACT_HOOK_NOW (epoch seconds).
set -u
input="$(cat 2>/dev/null || true)"
field() { printf '%s' "$input" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)"/\1/'; }
session_id="$(field session_id)"
[ -n "$session_id" ] || exit 0
case "$session_id" in *[!A-Za-z0-9_-]*) exit 0 ;; esac
trigger="$(field trigger)"
case "$trigger" in '' | *[!a-z]*) trigger=unknown ;; esac
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
printf '%s trigger=%s\n' "$(date -u -d "@${COMPACT_HOOK_NOW:-$(date -u +%s)}" +%Y-%m-%dT%H:%M:%SZ)" "$trigger" >> "$dir/$session_id.log"
exit 0
