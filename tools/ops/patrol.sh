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
# Then the commitments not kept yet (commit.sh, #534), past-due ones marked. When this
# session reached the handoff condition (2 compactions, or the context of its last model
# call above STOCK_CONTEXT_LIMIT, #710), the last line says so again and the exit code is
# 10, so neither a grep of the event lines nor `| tail -1` misses it (#534: the header
# line was filtered out and a coordinator went on for 6 compactions).
#
# The context comes from this session's transcript (session_cost.py context): found by
# session id under $CLAUDE_CONFIG_DIR/projects, then $HOME/.claude/projects, or named by
# --transcript / STOCK_TRANSCRIPT. A transcript not found or not understood is a warning
# only (#710 決定 6877357244); from the 3rd patrol in a row without it the line before the
# last says so.
#
# Files written: <data>/logs/coordinator-heartbeat.json (through a temporary file in the
# same directory and mv), <data>/logs/compactions/<session>.context-misses (the patrols in
# a row the context could not be read; removed once it is), and with --done one line in
# <data>/logs/events-done.jsonl.
#
# Exit: 0; 10 the handoff condition holds (whether or not every part of the listing could
#   be read, such as the questions 未查完); 2 a file could not be written or read back, a
#   --done failed; 3 another session's heartbeat was kept;
#   64 bad arguments.
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
#   --heartbeat-only  write the heartbeat and stop (take_over.sh's first step)
#   --transcript PATH this session's transcript, default $STOCK_TRANSCRIPT, then found
#                     by session id
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
# Environment: STOCK_CONTEXT_LIMIT, the context in tokens above which the handoff
#   condition holds, default 450000 (docs/COORDINATOR.md 自動換手機制).
# Test hook: PATROL_NOW (epoch seconds).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" max_gh=1 take_over=0 done_args=()
heartbeat_only=0 transcript="${STOCK_TRANSCRIPT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --take-over) take_over=1; shift; continue ;;
    --heartbeat-only) heartbeat_only=1; shift; continue ;;
    --session-id | --terminal | --done | --max-gh | --data-dir | --python | --transcript)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --session-id) session_id="$2" ;;
        --terminal) handle="$2" ;;
        --done) done_args+=("$2") ;;
        --max-gh) max_gh="$2" ;;
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
        --transcript) transcript="$2" ;;
      esac
      shift 2
      continue
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
done
case "$max_gh" in '' | *[!0-9]*) die "--max-gh must be a number" 64 ;; esac
context_limit="${STOCK_CONTEXT_LIMIT:-450000}"
case "$context_limit" in '' | *[!0-9]* | 0*) die "STOCK_CONTEXT_LIMIT 要是正整數（token 數）：$context_limit" 64 ;; esac
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
[ "$heartbeat_only" = 0 ] || exit 0

# 2. compaction count and handoff marker
count_file="$logs/compactions/$session_id.count"
count=0
[ -f "$count_file" ] && count="$(tr -dc '0-9' <"$count_file")"
count="${count:-0}"
# Strip leading zeros so 08 is not read as octal.
count="$((10#$count))"
handoff_due=0
if [ "$count" -ge 2 ]; then
  handoff_due=1
  echo "壓縮 $count 次：已達換手條件（手冊「統籌 session」自動換手機制）"
else
  echo "壓縮 $count 次"
fi
# The context of this session's last model call (#710).
misses_file="$logs/compactions/$session_id.context-misses"
context_due=0 context="" misses=0
if [ -n "$transcript" ]; then
  context_out="$("$python" -X utf8 "$script_dir/session_cost.py" context --transcript "$transcript" 2>&1)"
else
  context_out="$("$python" -X utf8 "$script_dir/session_cost.py" context --session-id "$session_id" 2>&1)"
fi
context_rc=$?
if [ "$context_rc" = 0 ] && [[ "$context_out" =~ ^([0-9]+)\ (.*)$ ]]; then
  context="${BASH_REMATCH[1]}" context_path="${BASH_REMATCH[2]}"
  rm -f "$misses_file"
  pct="$(awk -v a="$context" -v b="$context_limit" 'BEGIN { printf "%.0f%%", 100 * a / b }')"
  if [ "$context" -gt "$context_limit" ]; then
    context_due=1
    echo "context：$context（門檻 $context_limit，$pct）：已達換手條件（$context_path）"
  else
    echo "context：$context（門檻 $context_limit，$pct）（$context_path）"
  fi
else
  [ -f "$misses_file" ] && misses="$(tr -dc '0-9' <"$misses_file")"
  misses="$((10#${misses:-0} + 1))"
  mkdir -p "$logs/compactions" 2>/dev/null
  printf '%s\n' "$misses" >"$misses_file" 2>/dev/null || true
  echo "context：未讀到（${context_out:-session_cost.py exit $context_rc}；連續 $misses 次）"
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
# Commitments kept across sessions (#534): what the coordinators promised and did not do yet.
"$python" -X utf8 "$script_dir/commitments.py" list "$logs" "$now" \
  || echo "未兌現的承諾：讀不了承諾檔（$logs/commitments.jsonl）"
echo "其餘依手冊：處理上面的未處理事件（PR 的 CI 與合併、未回覆的提問、名額空缺就派工）與到期的承諾，處理完以 --done <seq>、commit.sh done <id> 標記；monitor 停擺時看 logs/monitor.log"
if [ "$misses" -ge 3 ]; then
  echo "context 已連續 $misses 次讀不到：換手只剩壓縮次數一個條件，請查紀錄檔位置（見上方 context 行）"
fi
# Last, so no filter of the lines above hides it (#534).
if [ "$handoff_due" = 1 ] || [ "$context_due" = 1 ]; then
  why=""
  [ "$handoff_due" = 1 ] && why="已壓縮 $count 次（門檻 2 次）"
  [ "$context_due" = 1 ] && why="${why:+$why、}context $context 超過門檻 $context_limit"
  if [ -f "$marker" ]; then
    echo "已達換手條件：本 session $why，換手標記已寫，換手中：不合併、不派工、不留言，等新統籌在 #1 留言（patrol exit 10）"
  else
    echo "已達換手條件：本 session $why，現在照 docs/COORDINATOR.md「統籌 session」自動換手機制換手（patrol exit 10）"
  fi
  exit 10
fi
