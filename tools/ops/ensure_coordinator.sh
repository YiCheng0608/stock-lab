#!/usr/bin/env bash
# Coordinator watchdog, run every 15 minutes by Windows Task Scheduler
# (tools/ops/Register-Watchdog.ps1). From the heartbeat file it decides
# whether a coordinator session is alive, wakes a stalled one or opens a new
# one, then checks the scheduled jobs for anomalies and comments on #1.
# Rules: docs/GITHUB_WORKFLOW.md "統籌 session"; locations and operation:
# docs/OPERATIONS.md §6. Every run appends to <data>/logs/ensure_coordinator.log.
#
# Usage: ensure_coordinator.sh [--dry-run] [--data-dir DIR] [--python EXE]
#                              [--handoff-file FILE]
#   --dry-run       decide and print the actions; no orca open/create/send, no comment
#   --data-dir      default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python        default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --handoff-file  send this text instead of the manual's handoff text (drills)
# Test hooks: WATCHDOG_NOW (epoch seconds), WATCHDOG_ORCA_WAIT_SECONDS (60),
# WATCHDOG_ORCA_RETRY_SECONDS (5), STOCK_COORDINATOR_WORKTREE (orca selector).
set -u
export LANG=C.UTF-8 LC_ALL=C.UTF-8

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
dry_run=0
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}"
python="${STOCK_PYTHON:-}"
handoff_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --data-dir) data_dir="${2:?--data-dir needs a value}"; shift ;;
    --python) python="${2:?--python needs a value}"; shift ;;
    --handoff-file) handoff_file="${2:?--handoff-file needs a value}"; shift ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
  shift
done

WAKE_TEXT='看門狗：心跳逾時，請先寫心跳檔並依手冊巡檢；若額度仍未重置就回一句『額度未重置』。'
COORDINATOR_COMMAND='claude --model claude-opus-5-5 --effort medium --autocompact 400k'
COORDINATOR_TITLE='統籌'
GH_REPO='YiCheng0608/stock-lab'
FRESH_SECONDS=3600         # heartbeat this recent: coordinator alive
STALE_SECONDS=7200         # older than this (or terminal gone): open a new one
HANDOFF_SECONDS=900        # a handoff marker this recent: handoff in progress
WAKE_EVERY_SECONDS=3600    # at most one wake text per hour
OPEN_EVERY_SECONDS=7200    # at most one open attempt per two hours
LOCK_STALE_SECONDS=1800
NEWS_INTERVAL_SECONDS=7200
ORCA_WAIT_SECONDS="${WATCHDOG_ORCA_WAIT_SECONDS:-60}"
ORCA_RETRY_SECONDS="${WATCHDOG_ORCA_RETRY_SECONDS:-5}"

now="${WATCHDOG_NOW:-$(date -u +%s)}"
logs="$data_dir/logs"
log_file="$logs/ensure_coordinator.log"
heartbeat="$logs/coordinator-heartbeat.json"
lock_dir="$logs/ensure_coordinator.lock"
mkdir -p "$logs" || exit 1

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
epoch_of() { date -u -d "$1" +%s 2>/dev/null; }

# log EVENT "key=value ..." "說明": one line in the log, echoed to stdout.
log() {
  local line
  line="$(iso "$now") $1"
  [ -n "$2" ] && line="$line $2"
  [ "$dry_run" = 1 ] && line="$line dry_run=1"
  line="$line | $3"
  printf '%s\n' "$line" >>"$log_file"
  printf '%s\n' "$line"
}

# Epoch of the newest log line for EVENT (optionally containing TEXT).
last_event() {
  local stamp
  stamp="$(grep -F " $1 " "$log_file" 2>/dev/null | grep -F -- "${2:-}" | tail -n 1 | cut -d' ' -f1)"
  [ -n "$stamp" ] && epoch_of "$stamp"
}

# --- lock ---------------------------------------------------------------
if ! mkdir "$lock_dir" 2>/dev/null; then
  lock_age=$(( $(date -u +%s) - $(stat -c %Y "$lock_dir" 2>/dev/null || date -u +%s) ))
  if [ "$lock_age" -lt "$LOCK_STALE_SECONDS" ]; then
    log locked "lock_age_s=$lock_age" "上一次執行仍持有 lock，本次略過"
    exit 0
  fi
  rm -rf "$lock_dir"
  mkdir "$lock_dir" 2>/dev/null || { log locked "" "無法取得 lock，本次略過"; exit 0; }
  log lock_stale_removed "lock_age_s=$lock_age" "lock 已超過 30 分鐘，視為殘留並移除"
fi
trap 'rm -rf "$lock_dir"' EXIT
work="$lock_dir"

# --- python helper --------------------------------------------------------
if [ -z "$python" ]; then
  for candidate in "$repo_root/.venv/Scripts/python.exe" "$repo_root/.venv/bin/python" python3 python; do
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then python="$candidate"; break; fi
  done
fi
if [ -z "$python" ] || ! "$python" -c 'import sys' >/dev/null 2>&1; then
  log python_missing "python=${python:-none}" "找不到可用的 Python，無法判讀 JSON；本次只寫日誌"
  exit 1
fi
helper() { "$python" -X utf8 "$script_dir/watchdog_helper.py" "$@"; }

# --- 1. Orca ----------------------------------------------------------------
# Orca adds its CLI to PATH only inside its own terminals; the scheduler does not.
if ! command -v orca >/dev/null 2>&1 && [ -n "${LOCALAPPDATA:-}" ] && command -v cygpath >/dev/null 2>&1; then
  orca_dir="$(cygpath -u "$LOCALAPPDATA")/Programs/orca/resources/bin"
  [ -f "$orca_dir/orca.exe" ] && PATH="$orca_dir:$PATH"
fi
if ! command -v orca >/dev/null 2>&1; then
  log orca_not_found "" "PATH 與 Orca 安裝目錄都找不到 orca CLI；本次只檢查異常"
fi
terminals="$work/terminals.json"
orca_list() { orca terminal list --json >"$terminals" 2>>"$work/orca.err" && helper ok "$terminals"; }
orca_ready=0
if ! command -v orca >/dev/null 2>&1; then
  :
elif orca_list; then
  orca_ready=1
elif [ "$dry_run" = 1 ]; then
  log orca_unavailable "" "Orca 未回應；dry-run 不啟動 Orca（實跑會 orca open 並等待最多 ${ORCA_WAIT_SECONDS} 秒）"
else
  log orca_open "" "Orca 未回應，執行 orca open"
  orca open --json >"$work/open.json" 2>>"$work/orca.err" || true
  started=$SECONDS
  while :; do
    if orca_list; then orca_ready=1; break; fi
    [ $((SECONDS - started)) -ge "$ORCA_WAIT_SECONDS" ] && break
    sleep "$ORCA_RETRY_SECONDS"
  done
  [ "$orca_ready" = 1 ] || log orca_unavailable "" "orca open 後 ${ORCA_WAIT_SECONDS} 秒內仍無法列出 terminal；本次只寫日誌"
fi

# --- 2. heartbeat -----------------------------------------------------------
hb_handle=""
hb_age=""
if [ -f "$heartbeat" ]; then
  hb_handle="$(helper field "$heartbeat" terminal_handle 2>/dev/null)"
  written="$(helper field "$heartbeat" written_at 2>/dev/null)"
  if written_epoch="$(epoch_of "$written")"; then
    hb_age=$((now - written_epoch))
  fi
fi
age_text() { if [ -n "$hb_age" ]; then echo "心跳 $((hb_age / 60)) 分鐘前"; else echo "沒有可讀的心跳檔"; fi; }

handoff_marker() {
  local file
  for file in "$logs"/handoff-*.json; do
    [ -f "$file" ] || continue
    if [ $((now - $(stat -c %Y "$file"))) -le "$HANDOFF_SECONDS" ]; then
      basename "$file"
      return 0
    fi
  done
  return 1
}

# --- 3. wake a stalled coordinator ------------------------------------------------
wake() {
  local last
  if last="$(last_event wake_sent)" && [ $((now - last)) -lt "$WAKE_EVERY_SECONDS" ]; then
    log wake_rate_limited "handle=$hb_handle last=$(iso "$last")" "$(age_text)；喚醒文 60 分鐘內已送過，本次不送"
    return
  fi
  if [ "$dry_run" = 1 ]; then
    log wake_planned "handle=$hb_handle" "$(age_text)且 terminal 仍連線；將送喚醒文：$WAKE_TEXT"
    return
  fi
  if orca terminal send --terminal "$hb_handle" --text "$WAKE_TEXT" --enter --json >"$work/send.json" 2>>"$work/orca.err" \
    && helper ok "$work/send.json"; then
    log wake_sent "handle=$hb_handle" "$(age_text)且 terminal 仍連線；已送喚醒文"
  else
    log wake_failed "handle=$hb_handle" "喚醒文送出失敗：$(tail -n 1 "$work/orca.err" 2>/dev/null)"
  fi
}

# --- 5. open a new coordinator ------------------------------------------------
orca_step() { # orca_step NAME args...: run orca, keep JSON in $work/NAME.json
  local name="$1"
  shift
  orca "$@" --json >"$work/$name.json" 2>>"$work/orca.err" && helper ok "$work/$name.json"
}

open_coordinator() {
  local state="$1" last selector old_handle="" text handle satisfied
  if last="$(last_event coordinator_open_attempt)" && [ $((now - last)) -lt "$OPEN_EVERY_SECONDS" ]; then
    log open_rate_limited "last=$(iso "$last")" "$(age_text)；120 分鐘內已嘗試開過統籌，本次不開"
    return
  fi
  selector="${STOCK_COORDINATOR_WORKTREE:-}"
  if [ -z "$selector" ] && orca_step worktrees worktree list; then
    selector="$(helper master-worktree "$work/worktrees.json" "$repo_root")"
    [ -n "$selector" ] && selector="id:$selector"
  fi
  if [ -z "$selector" ]; then
    log open_failed "stage=worktree" "找不到 master 管理 checkout 的 Orca worktree，無法開統籌"
    return
  fi
  [ "$state" = missing ] || old_handle="$hb_handle"
  if [ -n "$handoff_file" ]; then
    text="$(cat "$handoff_file")"
  else
    text="$(helper handoff-text "$repo_root/docs/GITHUB_WORKFLOW.md" "$old_handle")" || {
      log open_failed "stage=handoff_text" "docs/GITHUB_WORKFLOW.md 找不到接手文，無法開統籌"
      return
    }
  fi
  local reason
  reason="$(age_text)，舊 terminal ${hb_handle:-無}：$state"
  if [ "$dry_run" = 1 ]; then
    log coordinator_open_planned "old=${hb_handle:-none} state=$state" "將開新統籌（$reason）"
    printf '將執行：\n'
    printf '  orca terminal create --worktree %s --title "%s" --command "%s" --json\n' "$selector" "$COORDINATOR_TITLE" "$COORDINATOR_COMMAND"
    printf '  orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json\n'
    printf '  orca terminal send --terminal <handle> --text "<接手文>" --enter --json\n'
    printf '  orca terminal rename --terminal <handle> --title "%s" --json\n' "$COORDINATOR_TITLE"
    printf '將送出的接手文：\n%s\n' "$text"
    return
  fi
  if ! orca_step create terminal create --worktree "$selector" --title "$COORDINATOR_TITLE" --command "$COORDINATOR_COMMAND" \
    || ! handle="$(helper find "$work/create.json" handle)" || [ -z "$handle" ]; then
    log coordinator_open_attempt "handle=none" "開統籌：terminal create 失敗"
    log open_failed "stage=create" "terminal create 失敗：$(tail -n 1 "$work/orca.err" 2>/dev/null)"
    return
  fi
  log coordinator_open_attempt "handle=$handle old=${hb_handle:-none} state=$state" "開統籌（$reason）"
  satisfied=""
  for timeout in 60000 120000; do
    orca_step wait terminal wait --terminal "$handle" --for tui-idle --timeout-ms "$timeout" \
      && satisfied="$(helper find "$work/wait.json" satisfied)"
    [ "$satisfied" = true ] && break
  done
  if [ "$satisfied" != true ]; then
    orca_step close terminal close --terminal "$handle" || true
    log open_failed "stage=wait handle=$handle" "新 terminal 未就緒（tui-idle 兩次逾時），未送接手文並已關閉"
    return
  fi
  if ! orca_step send terminal send --terminal "$handle" --text "$text" --enter; then
    orca_step close terminal close --terminal "$handle" || true
    log open_failed "stage=send handle=$handle" "接手文送出失敗，已關閉新 terminal"
    return
  fi
  orca_step rename terminal rename --terminal "$handle" --title "$COORDINATOR_TITLE" \
    || log rename_failed "handle=$handle" "標題改名失敗（不影響判定）"
  local written_at tmp
  written_at="$(iso "$now")"
  tmp="$heartbeat.tmp.$$"
  printf '{"session_id":"","terminal_handle":"%s","written_at":"%s","written_by":"ensure_coordinator"}\n' \
    "$handle" "$written_at" >"$tmp" && mv -f "$tmp" "$heartbeat"
  log coordinator_opened "handle=$handle" "已開新統籌、送出接手文並把新 handle 寫入心跳檔"
}

# --- 2～5. decide ---------------------------------------------------------------
check_coordinator() {
  local marker state=missing
  if [ -n "$hb_age" ] && [ "$hb_age" -le "$FRESH_SECONDS" ]; then
    log coordinator_alive "handle=${hb_handle:-none}" "$(age_text)，統籌在線；不動作"
    return
  fi
  if marker="$(handoff_marker)"; then
    log handoff_in_progress "marker=$marker" "$(age_text)；換手標記在 15 分鐘內，換手進行中；不動作"
    return
  fi
  if [ -n "$hb_handle" ]; then
    state="$(helper terminal-state "$terminals" "$hb_handle")" || state=missing
  fi
  if [ -n "$hb_age" ] && [ "$hb_age" -le "$STALE_SECONDS" ] && [ "$state" = alive ]; then
    wake
  else
    open_coordinator "$state"
  fi
}
[ "$orca_ready" = 1 ] && check_coordinator

# --- 6. anomalies (gh and files only) -----------------------------------------------
taipei=$((now + 28800))
taipei_date="$(date -u -d "@$taipei" +%Y%m%d)"
taipei_hm="$(date -u -d "@$taipei" +%H%M)"
taipei_dow="$(date -u -d "@$taipei" +%u)"

anomaly() { # anomaly KEY SUMMARY: at most one #1 comment per key per Taipei day
  local key="$1" body
  if grep -qF " anomaly_commented key=$key date=$taipei_date" "$log_file" 2>/dev/null; then
    log anomaly_already_commented "key=$key date=$taipei_date" "今日已就此異常留言，不再留"
    return
  fi
  body="待使用者：$2

（看門狗 \`tools/ops/ensure_coordinator.sh\` 自動留言，同一異常每日最多一則；日誌 \`$log_file\`。）"
  if [ "$dry_run" = 1 ]; then
    log anomaly_planned "key=$key date=$taipei_date" "將在 #1 留言"
    printf '將在 #1 留言：\n%s\n' "$body"
    return
  fi
  printf '%s\n' "$body" >"$work/comment.md"
  if gh issue comment 1 --repo "$GH_REPO" --body-file "$work/comment.md" >"$work/gh.out" 2>>"$work/gh.err"; then
    log anomaly_commented "key=$key date=$taipei_date url=$(tail -n 1 "$work/gh.out")" "已在 #1 留言：$2"
  else
    log anomaly_comment_failed "key=$key" "#1 留言失敗：$(tail -n 1 "$work/gh.err" 2>/dev/null)"
  fi
}

# daily: a weekday's log needs an end line by 21:30 Taipei (only once daily logs exist).
if compgen -G "$logs/daily-*.log" >/dev/null && [ "$taipei_dow" -le 5 ] && [ $((10#$taipei_hm)) -ge 2130 ]; then
  daily_log="$logs/daily-$taipei_date.log"
  if [ ! -f "$daily_log" ]; then
    anomaly daily_no_end "daily 排程：台北 $taipei_date 已過 21:30，\`$daily_log\` 不存在（今日未執行）。"
  elif ! grep -qE '^===== .* end exit=' "$daily_log"; then
    anomaly daily_no_end "daily 排程：台北 $taipei_date 已過 21:30，\`$daily_log\` 沒有結束列（可能卡住或中斷）。"
  fi
fi

# news: runs every 2 hours; three missed runs in a row (only once news logs exist).
newest=0
for file in "$logs"/news-*.log; do
  [ -f "$file" ] || continue
  mtime="$(stat -c %Y "$file")"
  [ "$mtime" -gt "$newest" ] && newest="$mtime"
done
if [ "$newest" -gt 0 ] && [ $((now - newest)) -gt $((3 * NEWS_INTERVAL_SECONDS)) ]; then
  anomaly news_no_log "news 排程：最新日誌寫於 $(iso "$newest")，已連續 3 次（每 2 小時一次）沒有新日誌。"
fi

# news_llm: the last three batches all pending (read-only database).
if [ -f "$data_dir/stock.db" ]; then
  pending="$(helper news-llm-pending "$data_dir/stock.db" 3 2>>"$work/helper.err")" || pending=error
  case "$pending" in
    3) anomaly news_llm_pending "news_llm：最近連續 3 批判讀都是 pending（可能未登入 Claude Code 或額度用盡），請查 \`/api/ingestion-runs?q=news_llm\`。" ;;
    error) log news_llm_check_failed "" "讀取 stock.db 失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)" ;;
  esac
fi
exit 0
