#!/usr/bin/env bash
# Schedule watchdog, run every 15 minutes by Windows Task Scheduler
# (tools/ops/Register-Watchdog.ps1). Checks the daily, news and news-llm jobs
# for anomalies from their logs and the read-only database, and comments on
# #1. Operation: docs/OPERATIONS.md §6.1. Every run appends to
# <data>/logs/watchdog.log.
#
# Usage: watchdog.sh [--dry-run] [--data-dir DIR] [--python EXE]
#   --dry-run       decide and print the actions; no comment
#   --data-dir      default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python        default $STOCK_PYTHON, then this checkout's .venv, then python3
# Test hook: WATCHDOG_NOW (epoch seconds).
set -u
export LANG=C.UTF-8 LC_ALL=C.UTF-8

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
dry_run=0
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}"
python="${STOCK_PYTHON:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --data-dir) data_dir="${2:?--data-dir needs a value}"; shift ;;
    --python) python="${2:?--python needs a value}"; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
  shift
done

GH_REPO='YiCheng0608/stock-lab'
LOCK_STALE_SECONDS=1800
NEWS_INTERVAL_SECONDS=7200

now="${WATCHDOG_NOW:-$(date -u +%s)}"
logs="$data_dir/logs"
log_file="$logs/watchdog.log"
lock_dir="$logs/watchdog.lock"
mkdir -p "$logs" || exit 1

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }

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

# --- python helper (read-only database check) ----------------------------------
found=0  # 1 once an anomaly is reported or a check could not run
if [ -z "$python" ]; then
  for candidate in "$repo_root/.venv/Scripts/python.exe" "$repo_root/.venv/bin/python" python3 python; do
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then python="$candidate"; break; fi
  done
fi
if [ -z "$python" ] || ! "$python" -c 'import sys' >/dev/null 2>&1; then
  log python_missing "python=${python:-none}" "找不到可用的 Python，跳過 news_llm 檢查；日誌檢查照做"
  python=""
  found=1
fi
helper() { "$python" -X utf8 "$script_dir/watchdog_helper.py" "$@"; }

# --- anomalies (gh and files only) -----------------------------------------------
taipei=$((now + 28800))
taipei_date="$(date -u -d "@$taipei" +%Y%m%d)"
taipei_hm="$(date -u -d "@$taipei" +%H%M)"
taipei_dow="$(date -u -d "@$taipei" +%u)"

anomaly() { # anomaly KEY SUMMARY: at most one #1 comment per key per Taipei day
  local key="$1" body
  found=1
  if grep -qF " anomaly_commented key=$key date=$taipei_date" "$log_file" 2>/dev/null; then
    log anomaly_already_commented "key=$key date=$taipei_date" "今日已就此異常留言，不再留"
    return
  fi
  body="待使用者：$2

（看門狗 \`tools/ops/watchdog.sh\` 自動留言，同一異常每日最多一則；日誌 \`$log_file\`。）"
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
if [ -n "$python" ] && [ -f "$data_dir/stock.db" ]; then
  pending="$(helper news-llm-pending "$data_dir/stock.db" 3 2>>"$work/helper.err")" || pending=error
  case "$pending" in
    3) anomaly news_llm_pending "news_llm：最近連續 3 批判讀都是 pending（可能未登入 Claude Code 或額度用盡），請查 \`/api/ingestion-runs?q=news_llm\`。" ;;
    error) found=1; log news_llm_check_failed "" "讀取 stock.db 失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)" ;;
  esac
fi
[ "$found" = 0 ] && log schedules_ok "" "排程無異常"
exit 0
