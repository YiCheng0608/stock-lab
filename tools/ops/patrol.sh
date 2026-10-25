#!/usr/bin/env bash
# Coordinator patrol (Issue #282; docs/GITHUB_WORKFLOW.md 無人值守運作), in the handbook's
# order: write the heartbeat, read this session's compaction count and handoff marker,
# open PRs with CI and mergeStateStatus, Issue/PR comments since --since, and the
# schedule jobs' latest log lines. Prints a short summary.
#
# The only file written is <data>/logs/coordinator-heartbeat.json (through a temporary
# file in the same directory and mv). gh calls stop at --max-gh: the 5000/hour API limit
# is shared by every session on the account.
#
# Usage: patrol.sh [options]
#   --session-id ID   default $CLAUDE_CODE_SESSION_ID
#   --terminal H      default $ORCA_TERMINAL_HANDLE
#   --since ISO       comments after this UTC time (2026-10-25T12:00:00Z); default the
#                     previous heartbeat of the same session, else one hour ago
#   --max-gh N        at most N gh calls, default 2 (open PRs, comments)
#   --take-over       overwrite another session's heartbeat younger than an hour (a new
#                     coordinator taking over without the old one's handoff marker)
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
# Test hook: PATROL_NOW (epoch seconds).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" since="" max_gh=2 take_over=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --take-over) take_over=1; shift; continue ;;
    --session-id | --terminal | --since | --max-gh | --data-dir | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --session-id) session_id="$2" ;;
        --terminal) handle="$2" ;;
        --since) since="$2" ;;
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
case "$session_id" in '' | *[!A-Za-z0-9_-]*) die "--session-id（或 CLAUDE_CODE_SESSION_ID）必填，只能有英數、_、-" 64 ;; esac
case "$handle" in '' | *[!A-Za-z0-9_-]*) die "--terminal（或 ORCA_TERMINAL_HANDLE）必填，只能有英數、_、-" 64 ;; esac
case "$max_gh" in '' | *[!0-9]*) die "--max-gh must be a number" 64 ;; esac
iso_re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
[ -z "$since" ] || [[ "$since" =~ $iso_re ]] || die "--since 格式是 2026-10-25T12:00:00Z" 64
find_python

now="${PATROL_NOW:-$(date -u +%s)}"
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
logs="$data_dir/logs"
heartbeat="$logs/coordinator-heartbeat.json"
[ -d "$logs" ] || die "資料目錄沒有 logs/：$logs" 2

# 1. heartbeat. Another session's heartbeat younger than an hour (the handbook's liveness
# window) is kept unless that session left a handoff marker or --take-over is given
# (#283 review L7). A heartbeat that cannot be read (not JSON, no session id, a bad
# written_at) is treated the same: kept unless --take-over (#283 review L3). The same
# session's previous heartbeat is the default --since.
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
  [ -n "$prev_epoch" ] || prev_session=""
fi
[ -n "$since" ] || { [ "$prev_session" = "$session_id" ] && since="$prev_at"; }
[ -n "$since" ] || since="$(iso $((now - 3600)))"
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

# 3. gh: open PRs, then new comments
gh_calls=0
gh_budget() { # gh_budget WHAT: take one call from the budget or say what was skipped
  if [ "$gh_calls" -ge "$max_gh" ]; then
    echo "略過 $1：gh 呼叫已達上限 $max_gh"
    return 1
  fi
  gh_calls=$((gh_calls + 1))
}
if gh_budget "open PR"; then
  if out="$(gh pr list --repo "$GH_REPO" --state open --limit 30 \
    --json number,title,isDraft,mergeStateStatus,statusCheckRollup,labels)"; then
    lines="$(printf '%s' "$out" | cj prs)"
    echo "open PR：$( [ -n "$lines" ] && printf '%s' "$lines" | grep -c . || echo 0) 個"
    [ -n "$lines" ] && printf '%s\n' "$lines" | sed 's/^/  /'
  else
    echo "open PR：gh pr list 失敗"
  fi
fi
if gh_budget "新留言"; then
  if out="$(gh api "repos/$GH_REPO/issues/comments?since=$since&per_page=100")"; then
    lines="$(printf '%s' "$out" | cj comments)"
    n="$( [ -n "$lines" ] && printf '%s\n' "$lines" | grep -c '^#' || echo 0)"
    echo "$since 之後的新留言：$n 則$( [ "$n" -ge 100 ] && echo '（已達一頁上限，可能還有）')"
    [ -n "$lines" ] && printf '%s\n' "$lines" | sed 's/^/  /'
  else
    echo "新留言：gh api 失敗"
  fi
fi
echo "gh 呼叫：$gh_calls／上限 $max_gh"

# 4. schedule jobs: the newest log of each job
latest() { local f last=""; for f in "$logs"/$1; do [ -f "$f" ] && last="$f"; done; printf '%s' "$last"; }
for job in daily news; do
  file="$(latest "$job-*.log")"
  if [ -z "$file" ]; then
    echo "排程 $job：沒有日誌"
    continue
  fi
  end="$(grep -E '^===== .* end ' "$file" | tail -n 1 | tr -d '\r')"
  echo "排程 $job：$(basename "$file") ${end:-（沒有結束列，可能執行中或中斷）}"
done
if [ -f "$logs/watchdog.log" ]; then
  echo "看門狗：$(tail -n 1 "$logs/watchdog.log" | tr -d '\r')"
else
  echo "看門狗：沒有日誌"
fi
echo "其餘巡檢依手冊：監看是否存活、進行中 Issue 的提問、名額空缺就派工、背景工作是否卡住"
