#!/usr/bin/env bash
# Schedule watchdog, run every 15 minutes by Windows Task Scheduler
# (tools/ops/Register-Watchdog.ps1). Checks the daily, news and news-llm jobs
# for anomalies from their logs and the read-only database, the data
# invariants in that database and the event monitor's heartbeat (#316), and
# comments on #1. Operation: docs/OPERATIONS.md §6.1. Every run appends to
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
arguments=("$@")
dry_run=0
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}"
python="${STOCK_PYTHON:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --data-dir) data_dir="${2:?--data-dir needs a value}"; shift ;;
    --python) python="${2:?--python needs a value}"; shift ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
  shift
done

GH_REPO='YiCheng0608/stock-lab'
NEWS_INTERVAL_SECONDS=7200
# The daily result is read from 22:00 Taipei: by then the 21:30 trigger has
# written its schedule_runs row, so an 18:30 partial is not reported early.
DAILY_RESULT_AFTER_HM=2200

now="${WATCHDOG_NOW:-$(date -u +%s)}"
logs="$data_dir/logs"
log_file="$logs/watchdog.log"
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

# --- python (lock and read-only database checks) --------------------------------
found=0  # 1 once an anomaly is reported or a check could not run
python_missing=""
if [ -z "$python" ]; then
  for candidate in "$repo_root/.venv/Scripts/python.exe" "$repo_root/.venv/bin/python" python3 python; do
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then python="$candidate"; break; fi
  done
fi
if [ -z "$python" ] || ! "$python" -c 'import sys' >/dev/null 2>&1; then
  python_missing="${python:-none}"
  python=""
fi

# --- lock -----------------------------------------------------------------------
# The file lock of the scheduled jobs (backend/worker/job.py): Python holds it
# and runs this script again as its child; the OS drops it when Python ends,
# killed or not, and the child ends with it (#313; replaces the lock directory
# that a killed run left behind for 30 minutes, #224). Without Python the run
# goes unlocked; the task's IgnoreNew still keeps scheduled runs apart.
if [ -n "$python" ] && [ -z "${WATCHDOG_LOCK_HELD:-}" ]; then
  case "$data_dir" in
    /*|[A-Za-z]:*) lock_file="$data_dir/locks/watchdog.lock" ;;
    *) lock_file="$PWD/$data_dir/locks/watchdog.lock" ;;
  esac
  (cd "$repo_root/backend" && WATCHDOG_LOCK_HELD=1 exec "$python" -X utf8 -m worker.job \
    lock "$lock_file" -- "$BASH" "$script_dir/watchdog.sh" "${arguments[@]}")
  status=$?
  if [ "$status" = 75 ]; then
    log locked "" "上一次執行仍持有 lock，本次略過"
    exit 0
  fi
  exit "$status"
fi
work="$(mktemp -d "$logs/.watchdog.XXXXXX")" || exit 1
trap 'rm -rf "$work"' EXIT

if [ -n "$python_missing" ]; then
  log python_missing "python=$python_missing" "找不到可用的 Python，跳過 DB 檢查（daily 結果、news_llm、資料不變量）；日誌檢查照做"
  found=1
fi
helper() { "$python" -X utf8 "$script_dir/watchdog_helper.py" "$@"; }

# --- anomalies (gh and files only) -----------------------------------------------
taipei=$((now + 28800))
taipei_date="$(date -u -d "@$taipei" +%Y%m%d)"
taipei_iso="$(date -u -d "@$taipei" +%Y-%m-%d)"
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

# daily: from 22:00 on a weekday, the day's runs in schedule_runs (read-only
# database) must have ended success or non_trading_day.
if [ -n "$python" ] && [ -f "$data_dir/stock.db" ] && compgen -G "$logs/daily-*.log" >/dev/null \
  && [ "$taipei_dow" -le 5 ] && [ $((10#$taipei_hm)) -ge "$DAILY_RESULT_AFTER_HM" ]; then
  result="$(helper daily-result "$data_dir/stock.db" "$taipei_iso" "$now" 2>>"$work/helper.err")" || result=error
  case "$result" in
    success|non_trading_day|running|skip) ;;
    none)
      # Without a log the daily_no_end check above has reported it already.
      [ -f "$logs/daily-$taipei_date.log" ] && anomaly daily_result "daily 排程：台北 $taipei_iso 有日誌但 \`schedule_runs\` 沒有這一天的 run（worker 未能啟動），請看 \`$logs/daily-$taipei_date.log\`。" ;;
    error) found=1; log daily_check_failed "" "讀取 stock.db 的 schedule_runs 失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)" ;;
    catchup_incomplete) anomaly daily_result "daily 排程：台北 $taipei_iso 當日成功，但補抓前幾個交易日沒有補齊（catchup），請查 \`python -m worker.cli schedule-runs --date $taipei_iso\` 的 catchup 步驟，必要時依 OPERATIONS §6.4 手動 backfill。" ;;
    *) anomaly daily_result "daily 排程：台北 $taipei_iso 的 daily 結果是 \`$result\`（不是 success／non_trading_day），請查 \`python -m worker.cli schedule-runs --date $taipei_iso\` 與 \`$logs/daily-$taipei_date.log\`。" ;;
  esac
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

# news_llm (read-only database): the last three batches all pending; and
# failures without batches (claude not found, API key in the environment,
# killed by the task limit): the last three runs failed.  The news logs'
# last three news_llm_exit values also catch a run that wrote no row at all
# (news_llm_results table missing).
llm_failed=""
if [ -n "$python" ] && [ -f "$data_dir/stock.db" ]; then
  pending="$(helper news-llm-pending "$data_dir/stock.db" 3 2>>"$work/helper.err")" \
    && failed_runs="$(helper news-llm-failed "$data_dir/stock.db" 3 "$now" 2>>"$work/helper.err")" \
    || pending=error
  case "$pending" in
    3) anomaly news_llm_pending "news_llm：最近連續 3 批判讀都是 pending（可能未登入 Claude Code 或額度用盡），請查 \`/api/ingestion-runs?q=news_llm\`。" ;;
    error) found=1; log news_llm_check_failed "" "讀取 stock.db 失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)" ;;
  esac
  [ "$pending" != error ] && [ "$failed_runs" = 3 ] \
    && llm_failed="24 小時內最近 3 筆 \`run_type=news_llm\` 的 run 都是 failed（執行逾 90 分鐘仍為 running 的也算）"
fi
# Only end lines of the last 24 hours, so stale logs (news stopped) are not
# reported again every day; the news_no_log check covers a stopped job.
yesterday="$(date -u -d "@$((taipei - 86400))" +%Y%m%d)"
llm_exits="$(for file in "$logs/news-$yesterday.log" "$logs/news-$taipei_date.log"; do
    [ -f "$file" ] && grep -E '^===== [^ ]+ end .*news_llm_exit=' "$file"
  done | tr -d '\r' | while read -r _ stamp rest; do
    at="$(date -d "$stamp" +%s 2>/dev/null)" || continue
    [ "$at" -ge $((now - 86400)) ] && [ "$at" -le "$now" ] && printf '%s\n' "${rest##*news_llm_exit=}"
  done | tail -n 3 | tr '\n' ' ')"
if [ "$(printf '%s' "$llm_exits" | wc -w)" -eq 3 ] && ! printf '%s' "$llm_exits" | grep -qvE '^((1|wrapper_error) )+$'; then
  llm_failed="${llm_failed:+$llm_failed；}news 日誌 24 小時內最後 3 次的 \`news_llm_exit\` 是 ${llm_exits% }"
fi
[ -n "$llm_failed" ] && anomaly news_llm_failed "news_llm：$llm_failed（可能找不到 claude、環境有 API 金鑰、表未建立或被排程逾時終止），請查 news 日誌的 news-llm 段落與 \`/api/ingestion-runs?q=news_llm\`。"

# The coordinator's event monitor (tools/ops/monitor.sh, OPERATIONS §6.6) writes
# its heartbeat every poll; ten minutes without one means nobody wakes the
# coordinator; ten polls in a row with a failed gh call mean it polls for nothing.
# No heartbeat file: the monitor is not registered, no check.
if [ -n "$python" ]; then
  beat="$(helper monitor-beat "$logs/monitor-heartbeat.json" "$now" 2>>"$work/helper.err")" || beat=error
  case "$beat" in
    stale\ *)
      read -r _ age at <<<"$beat"
      anomaly monitor_stale "事件 monitor：最後一次輪詢在 $at（$((age / 60)) 分鐘前），停擺超過 10 分鐘，統籌不會被喚醒。請依 OPERATIONS §6.6 查 \`$logs/monitor.log\` 與工作 \`\\stock-lab\\monitor\`，必要時重新啟動。" ;;
    gh_failed\ *)
      read -r _ polls since error <<<"$beat"
      anomaly monitor_gh_failed "事件 monitor：gh 從 $since 起連續 $polls 輪失敗（最後的錯誤：$error），佇列收不到 PR 與留言的事件。請查 \`gh auth status\` 與 \`$logs/monitor.log\`（OPERATIONS §6.6）。" ;;
    unreadable) anomaly monitor_stale "事件 monitor：\`$logs/monitor-heartbeat.json\` 讀不出輪詢時間，統籌可能不會被喚醒。請依 OPERATIONS §6.6 查 \`$logs/monitor.log\`。" ;;
    error) found=1; log monitor_check_failed "" "讀取 monitor 心跳失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)" ;;
  esac
fi

# Data invariants (read-only database), every run: the numbers go to stdout,
# a violation is reported like any other anomaly. The data is not repaired.
if [ -n "$python" ] && [ -f "$data_dir/stock.db" ]; then
  if checks="$(helper invariants "$data_dir/stock.db" "$taipei_iso" 2>>"$work/helper.err")"; then
    value() { printf '%s\n' $facts | sed -n "s/^$1=//p"; }  # value KEY: from this line's facts
    while read -r name state facts; do
      printf 'invariant %s %s %s\n' "$name" "$state" "$facts"
      [ "$state" = violation ] || continue
      case "$name" in
        future_trading_date) anomaly invariant_future_date "資料不變量：\`market_bars\` 最新 \`trading_date\` 是 $(value max_trading_date)，晚於台北今日 $(value today)（日期解析或來源錯誤），請查最近的 daily 日誌與 \`/api/ingestion-runs\`。" ;;
        latest_bar_provenance) anomaly invariant_bar_provenance "資料不變量：最新交易日 $(value trading_date) 的 $(value bars) 列 \`market_bars\` 中，$(value unknown_source) 列 \`source\` 是 \`unknown\` 或空、$(value null_data_as_of) 列沒有 \`data_as_of\`，請查該日的 daily 日誌與寫入來源。" ;;
        instrument_status_sync) anomaly invariant_status_sync "資料不變量：最近一次標的狀態同步被防呆略過（$(value skipped)；absent 為官方清單缺席、dormant 為 60 個交易日沒有行情列）：兩者合計超過該交易所現行標的的 5%，標的狀態沒有更新。請依 OPERATIONS §6.1 查該日 collect run 的 \`instrument_status_sync\`。" ;;
        execution_calendar) anomaly invariant_execution_calendar "資料不變量：最新訊號日 $(value signal_date) 的 $(value signals) 筆 analysis 訊號中，$(value without_date) 筆沒有規則最早執行日（\`earliest_execution_date\` 為空）：官方休市表缺該年度，或 daily 的 trading_calendar 步驟失敗。請依 OPERATIONS §6.3 查該日 analyze 步驟的 \`execution_calendar\` 與 trading_calendar 步驟，必要時跑 \`python -m worker.cli trading-calendar\`。" ;;
        strategy_levels) anomaly invariant_strategy_levels "資料不變量：daily run $(value run_id)（目標日 $(value target_date)）的 strategy_levels 步驟是 \`$(value status)\`：這一步不影響 run 狀態，個股頁策略總表的觀察價位不會更新。請依 OPERATIONS §6.3 查該 run 的 \`schedule_run_steps\` 錯誤，修正後跑 \`python -m worker.cli strategy-levels --date $(value target_date)\`。" ;;
        llm_done_provenance) anomaly invariant_llm_provenance "資料不變量：\`news_llm_results\` 的 $(value done) 列 \`llm_status=done\` 中，$(value missing_model) 列沒有 \`llm_model\`、$(value empty_prompt_version) 列 \`prompt_version\` 為空，請查 news 日誌的 news-llm 段落。" ;;
      esac
    done <<<"$checks"
  else
    found=1
    log invariants_check_failed "" "讀取 stock.db 的資料不變量失敗：$(tail -n 1 "$work/helper.err" 2>/dev/null)"
  fi
fi
[ "$found" = 0 ] && log schedules_ok "" "排程無異常"
exit 0
