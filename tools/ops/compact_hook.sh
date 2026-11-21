#!/usr/bin/env bash
# PreCompact hook: count context compactions per Claude Code session.
# Writes <STOCK_DATA_DIR>/logs/compactions/<session_id>.count (one integer) and
# appends one line per compaction to <session_id>.log: the UTC time, the hook's
# trigger (auto or manual) and which conversation compacted, e.g.
# "2026-10-28T01:23:45Z trigger=auto agent_id=none" (#316). A subagent's compaction
# comes with the parent's session_id and transcript_path, and with agent_id and
# agent_type (#811, measured on Claude Code 2.1.325): the line then has
# "agent_id=<id> agent_type=<type>"; the main conversation's has "agent_id=none". The
# count still has both, so the coordinator's patrol counts its main conversation's
# compactions in its transcript and reads this count only when that cannot be read
# (docs/ops/COORDINATOR_REFERENCE.md, "換手偵測"). Every session writes them, engineers too; the
# coordinator's are the ones whose session id its heartbeat names.
# Test hook: COMPACT_HOOK_NOW (epoch seconds).
set -u
input="$(cat 2>/dev/null || true)"
field() { printf '%s' "$input" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)"/\1/'; }
session_id="$(field session_id)"
[ -n "$session_id" ] || exit 0
case "$session_id" in *[!A-Za-z0-9_-]*) exit 0 ;; esac
trigger="$(field trigger)"
case "$trigger" in '' | *[!a-z]*) trigger=unknown ;; esac
agent="agent_id=none"
agent_id="$(field agent_id)"
if [ -n "$agent_id" ]; then
  case "$agent_id" in *[!A-Za-z0-9_-]*) agent_id=unknown ;; esac
  agent_type="$(field agent_type)"
  case "$agent_type" in '' | *[!A-Za-z0-9_.:-]*) agent_type=unknown ;; esac
  agent="agent_id=$agent_id agent_type=$agent_type"
fi
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
printf '%s trigger=%s %s\n' "$(t="${COMPACT_HOOK_NOW:-$(date -u +%s)}"; date -u -d "@$t" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$t" +%Y-%m-%dT%H:%M:%SZ)" "$trigger" "$agent" >> "$dir/$session_id.log"
exit 0
