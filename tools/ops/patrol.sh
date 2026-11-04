#!/usr/bin/env bash
# Coordinator patrol (Issue #282, #316, #401; docs/COORDINATOR.md 無人值守運作), in
# the handbook's order: write the heartbeat, read this session's compaction count and
# handoff marker, then the event queue the monitor (tools/ops/monitor.sh) keeps: its
# heartbeat, its last open PR snapshot, the schedule jobs' latest log lines as it read them,
# then the unanswered questions (a 提問 comment no 決定 comment links to, #401) and the
# events not handled yet. Prints a short summary. PRs, CI and new comments come from the
# queue: GitHub is polled by the monitor only (#316 AC-4). The one gh call is the questions'
# GraphQL query, as whether a question is answered needs every open thread's comments as
# they are now (closed Issues, which 決定 links which), which the queue's events do not hold.
#
# Files written: <data>/logs/coordinator-heartbeat.json (through a temporary file in the
# same directory and mv), and with --done one line in <data>/logs/events-done.jsonl.
#
# Usage: patrol.sh [options]
#   --session-id ID   default $CLAUDE_CODE_SESSION_ID
#   --terminal H      default $ORCA_TERMINAL_HANDLE
#   --done X          mark events handled before listing the rest: X is an event id, or
#                     a seq for every event not done up to it (pending or quiet, #440);
#                     repeatable
#   --max-gh N        at most N gh calls, default 1 (the questions); 0 prints the
#                     questions as not read (未查完)
#   --take-over       overwrite another session's heartbeat younger than an hour (a new
#                     coordinator taking over without the old one's handoff marker)
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
# Test hook: PATROL_NOW (epoch seconds).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" max_gh=1 take_over=0 done_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --take-over) take_over=1; shift; continue ;;
    --session-id | --terminal | --done | --max-gh | --data-dir | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --session-id) session_id="$2" ;;
        --terminal) handle="$2" ;;
        --done) done_args+=("$2") ;;
        --max-gh) max_gh="$2" ;;
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      continue
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
done
case "$max_gh" in '' | *[!0-9]*) die "--max-gh must be a number" 64 ;; esac
case "$session_id" in '' | *[!A-Za-z0-9_-]*) die "--session-id（或 CLAUDE_CODE_SESSION_ID）必填，只能有英數、_、-" 64 ;; esac
case "$handle" in '' | -* | *[!A-Za-z0-9_-]*) die "--terminal（或 ORCA_TERMINAL_HANDLE）必填，只能有英數、_、-，不能以 - 開頭" 64 ;; esac
iso_re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
find_python

now="${PATROL_NOW:-$(date -u +%s)}"
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
logs="$data_dir/logs"
heartbeat="$logs/coordinator-heartbeat.json"
[ -d "$logs" ] || die "資料目錄沒有 logs/：$logs" 2

# 1. heartbeat. Another session's heartbeat younger than an hour (the handbook's liveness
# window) is kept unless that session left a handoff marker or --take-over is given
# (#283 review L7). A heartbeat that cannot be read (not JSON, no session id, a bad
# written_at) is treated the same: kept unless --take-over (#283 review L3).
prev_session="" prev_at=""
if [ -e "$heartbeat" ]; then
  prev_session="$(cj get session_id <"$heartbeat" 2>/dev/null)" || prev_session=""
  prev_at="$(cj get written_at <"$heartbeat" 2>/dev/null)" || prev_at=""
  prev_epoch=""
  [[ "$prev_at" =~ $iso_re ]] && prev_epoch="$(date -u -d "$prev_at" +%s 2>/dev/null)"
  case "$prev_session" in '' | *[!A-Za-z0-9_-]*) prev_epoch="" ;; esac
  if [ "$take_over" = 0 ]; then
    [ -n "$prev_epoch" ] || die "心跳檔讀不懂（session_id 或 written_at 缺少或格式不對），視同另一個 session 的心跳，未覆寫；確定接手才加 --take-over：$heartbeat" 3
    if [ "$prev_session" != "$session_id" ] && [ ! -f "$logs/handoff-$prev_session.json" ] \
      && [ $((now - prev_epoch)) -lt 3600 ]; then
      die "心跳檔屬於另一個統籌 session $prev_session（${prev_at}，$(((now - prev_epoch) / 60)) 分鐘前），它沒有換手標記，未覆寫；確定接手才加 --take-over" 3
    fi
  fi
fi
written_at="$(iso "$now")"
tmp="$logs/.coordinator-heartbeat.json.tmp.$$"
if ! printf '{"session_id":"%s","terminal_handle":"%s","written_at":"%s"}' "$session_id" "$handle" "$written_at" >"$tmp" \
  || ! mv -f "$tmp" "$heartbeat"; then
  rm -f "$tmp"
  die "寫不進心跳檔：$heartbeat" 2
fi
[ "$(cj get written_at <"$heartbeat")" = "$written_at" ] || die "心跳檔讀回不符：$heartbeat" 2
echo "心跳 $written_at session=$session_id terminal=$handle（$heartbeat）"

# 2. compaction count and handoff marker
count_file="$logs/compactions/$session_id.count"
count=0
[ -f "$count_file" ] && count="$(tr -dc '0-9' <"$count_file")"
count="${count:-0}"
if [ "$count" -ge 2 ]; then
  echo "壓縮 $count 次：已達換手條件（手冊「統籌 session」自動換手機制）"
else
  echo "壓縮 $count 次"
fi
marker="$logs/handoff-$session_id.json"
if [ -f "$marker" ]; then echo "換手標記存在：$marker（換手中，不合併、不派工、不留言）"; else echo "換手標記：無"; fi

# 3. the event queue: mark what was handled, then the monitor and what is left
eq() { "$python" -X utf8 "$script_dir/event_queue.py" "$@"; }
if [ ${#done_args[@]} -gt 0 ]; then
  eq done "$logs" "$now" "$session_id" "${done_args[@]}" || die "--done 失敗（見上一行）" 2
fi
# The monitor's heartbeat, open PRs and job log lines from its last poll: in the
# scheduler container the job logs are in the volume, out of this shell's reach (#338).
eq status "$logs" "$now"
# The wake listener the scheduler container's monitor wakes this session through (#338).
bash "$script_dir/wake_listener_start.sh" --status 2>&1
# Questions nobody answered (#401): one GraphQL call reads the open Issues and PRs with
# their comments; coordinator_json.py decides which 提問 has no 決定 linking to it.
gh_calls=0
if [ "$gh_calls" -lt "$max_gh" ]; then
  gh_calls=$((gh_calls + 1))
  if out="$(gh api graphql -f owner="${GH_REPO%%/*}" -f name="${GH_REPO#*/}" \
    -f query="$(cj questions-query)")" && lines="$(printf '%s' "$out" | cj questions "$now")"; then
    n="$(printf '%s\n' "$lines" | grep -c '^#')"
    echo "未回覆的提問：$n 則$(printf '%s\n' "$lines" | grep -q '^未查完' && echo '（未查完）')"
    [ -n "$lines" ] && printf '%s\n' "$lines" | sed 's/^/  /'
  else
    echo "未回覆的提問：未查完（gh api graphql 失敗）"
  fi
else
  echo "未回覆的提問：未查完（gh 呼叫已達上限 $max_gh）"
fi
echo "gh 呼叫：$gh_calls／上限 $max_gh"
eq pending "$logs"
echo "其餘依手冊：處理上面的未處理事件（PR 的 CI 與合併、未回覆的提問、名額空缺就派工），處理完以 --done <seq> 標記；monitor 停擺時看 logs/monitor.log"
