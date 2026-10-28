#!/usr/bin/env bash
# Coordinator event monitor (Issue #316; docs/GITHUB_WORKFLOW.md 無人值守運作,
# docs/OPERATIONS.md §6.6), resident under Windows Task Scheduler
# (tools/ops/Register-Monitor.ps1). No LLM: every --interval seconds it polls the open
# PRs (CI, mergeStateStatus), the repository's new Issue/PR comments, the task
# worktrees and the job logs, appends the events not queued yet to
# <data>/logs/events.jsonl (tools/ops/event_queue.py) and, once orca reports the
# coordinator terminal of the heartbeat idle, sends it one line "有 N 個事件…" for
# them. When the queue has waited an hour
# with no coordinator heartbeat since, it comments on #1 asking the user to open a
# coordinator; it never opens a session itself (#1 6245309556, 6320448594).
#
# gh: at most 2 calls per poll (open PRs, then comments; the #1 comment takes the
# comments' turn) and polls at least 60 seconds apart: the 5000/hour API limit is
# shared by every session on the account. Every gh and orca call ends within
# MONITOR_CALL_TIMEOUT seconds (120): a hung call would stop the polls, and the
# scheduled task never starts a second run while this one runs. One monitor at a time
# (logs/monitor.lock/).
# To stop it, create <data>/logs/monitor.stop: the monitor removes it and exits after
# the poll it is in (Register-Monitor.ps1 -Unregister does so; stopping the scheduled
# task may end only the PowerShell that hosts bash).
# Each poll appends a line to <data>/logs/monitor.log and rewrites
# <data>/logs/monitor-heartbeat.json, which the watchdog reads.
#
# Usage: monitor.sh [options]
#   --once            one poll, then exit
#   --interval S      seconds between polls, default 60, at least 60
#   --record-only     record events only: no wake, no comment (gh reads still count)
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --orca EXE        default orca on PATH, then
#                     $LOCALAPPDATA/Programs/orca/resources/bin/orca.exe
# Test hooks: MONITOR_NOW (epoch seconds, with --once), MONITOR_CALL_TIMEOUT.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

once=0 interval=60 record_only=0 orca_exe=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --once) once=1; shift; continue ;;
    --record-only) record_only=1; shift; continue ;;
    --interval | --data-dir | --python | --orca)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --interval) interval="$2" ;;
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
        --orca) orca_exe="$2" ;;
      esac
      shift 2
      continue
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
done
case "$interval" in '' | *[!0-9]*) die "--interval must be a number" 64 ;; esac
[ "$interval" -ge 60 ] || die "--interval 至少 60 秒（gh 限流全帳號共用）" 64
find_python
if [ -z "$orca_exe" ]; then
  if command -v orca >/dev/null 2>&1; then
    orca_exe=orca
  else
    # The scheduler's PATH has no orca.
    orca_exe="${LOCALAPPDATA:-}/Programs/orca/resources/bin/orca.exe"
  fi
fi

call_timeout="${MONITOR_CALL_TIMEOUT:-120}"
# The coordinator terminal must be idle within this long, or the wake waits.
wake_wait_ms=15000
call() { timeout -k 10 "$call_timeout" "$@"; }

logs="$data_dir/logs"
mkdir -p "$logs" || die "建不了 $logs" 2
log_file="$logs/monitor.log"
lock_dir="$logs/monitor.lock"
mode=wake
[ "$record_only" = 1 ] && mode=record-only
eq() { "$python" -X utf8 "$script_dir/event_queue.py" "$@"; }
clock() { if [ "$once" = 1 ] && [ -n "${MONITOR_NOW:-}" ]; then echo "$MONITOR_NOW"; else date -u +%s; fi; }
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
log() { # log EVENT TEXT
  local line
  line="$(iso "$(clock)") $1 mode=$mode $2"
  printf '%s\n' "$line" >>"$log_file"
  printf '%s\n' "$line"
}

# --- one monitor at a time. A lock whose pid is gone, or whose monitor has not beaten
# for 10 minutes, was left by a killed or hung run and is taken over. The lock holds
# "pid token": a monitor whose lock was taken over stops at its next check (each poll's
# start, before the #1 comment, before the queue) and leaves the new owner's lock and
# work directory alone (#316 review S3, S-a).
token="$$ $(date +%s%N)$RANDOM"
owns_lock() { [ "$(cat "$lock_dir/pid" 2>/dev/null)" = "$token" ]; }
keep_lock() {
  owns_lock && return 0
  log lock_lost "pid=$$ owner=$(cat "$lock_dir/pid" 2>/dev/null)"
  exit 0
}
if ! mkdir "$lock_dir" 2>/dev/null; then
  read -r owner _ <"$lock_dir/pid" 2>/dev/null || owner=""
  beat_age="$("$python" -X utf8 -c '
import json, sys, time
try:
    from datetime import datetime
    at = json.load(open(sys.argv[1], encoding="utf-8"))["written_at"]
    print(int(time.time() - datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()))
except Exception:
    print(999999)
' "$logs/monitor-heartbeat.json")"
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null && [ "$beat_age" -lt 600 ]; then
    log already_running "pid=$owner" >/dev/null
    echo "monitor 已在執行（pid $owner），本次不啟動"
    exit 0
  fi
  rm -rf "$lock_dir"
  mkdir "$lock_dir" 2>/dev/null || die "取不到 $lock_dir" 2
  log lock_stale_removed "pid=${owner:-?} beat_age_s=$beat_age"
fi
printf '%s\n' "$token" >"$lock_dir/pid"
trap 'owns_lock && rm -rf "$lock_dir"' EXIT
trap 'exit 143' INT TERM

gh_call() { # gh_call OUT ARGS...: one gh call of this poll, within the timeout
  local out="$1" err label status
  shift
  gh_calls=$((gh_calls + 1))
  err="$work/gh-$gh_calls.err"
  label="gh $1"
  [ "$1" = api ] || label="$label $2"
  call gh "$@" >"$out" 2>"$err"
  status=$?
  [ "$status" = 0 ] && return 0
  gh_failed=1
  # The error of this call, not a warning an earlier call of the poll wrote (S-c).
  if [ "$status" = 124 ]; then
    gh_error="$label: timeout ${call_timeout}s"
  else
    gh_error="$(tr -d '\r' <"$err" | grep -v '^[[:space:]]*$' | tail -n 1)"
    gh_error="$label: ${gh_error:-exit $status}"
  fi
  return "$status"
}

poll() {
  local now gh_calls=0 gh_failed=0 gh_error="" since summary new pending wake terminal
  local stale_line key body url args=() ro=() work notes="" text out
  keep_lock
  now="$(clock)"
  work="$lock_dir/work.$$"
  rm -rf "$work" && mkdir -p "$work"

  # 1. the #1 comment, when due, takes the comments' gh call this poll
  [ "$record_only" = 1 ] && ro=(--record-only)
  stale_line="$(eq stale "$logs" "$now" "${ro[@]}")"
  key="" body=""
  if [ -n "$stale_line" ]; then
    key="${stale_line%%$'\t'*}"
    body="${stale_line#*$'\t'}"
  fi

  # 2. open PRs
  if gh_call "$work/prs.json" pr list --repo "$GH_REPO" --state open --limit 30 \
    --json number,title,url,isDraft,headRefOid,mergeStateStatus,statusCheckRollup,labels; then
    args+=(--prs "$work/prs.json")
  else
    notes="$notes prs=failed"
  fi

  # 3. the #1 comment or new comments
  if [ -n "$key" ] && [ "$record_only" = 1 ]; then
    eq note-stale "$logs" "$now" "$key" -
    notes="$notes stale=planned"
  elif [ -n "$key" ]; then
    keep_lock
    printf '%s\n' "$body" >"$work/comment.md"
    if gh_call "$work/comment.out" issue comment 1 --repo "$GH_REPO" --body-file "$work/comment.md"; then
      url="$(tr -d '\r' <"$work/comment.out" | tail -n 1)"
      eq note-stale "$logs" "$now" "$key" "${url:-?}"
      notes="$notes stale=commented url=$url"
    else
      notes="$notes stale=comment_failed"
    fi
  fi
  if [ -z "$key" ]; then
    since="$(eq since "$logs" "$now")"
    if gh_call "$work/comments.json" \
      api "repos/$GH_REPO/issues/comments?since=$since&sort=updated&direction=asc&per_page=100"; then
      args+=(--comments "$work/comments.json")
    else
      notes="$notes comments=failed"
    fi
  fi

  # 4. task worktrees (Orca, no gh)
  if call "$orca_exe" worktree list --json >"$work/worktrees.json" 2>/dev/null; then
    args+=(--worktrees "$work/worktrees.json")
  else
    notes="$notes worktrees=failed"
  fi

  # 5. queue, then wake; not if another monitor took the lock over meanwhile
  keep_lock
  out="$(eq record "$logs" "$now" "${args[@]}")" || { log poll_failed "gh_calls=$gh_calls$notes"; return; }
  summary="$(printf '%s\n' "$out" | tail -n 1)"
  printf '%s\n' "$out" | grep '^event ' | sed 's/^/  /'
  read -r new pending _ wake terminal <<<"$summary"
  new="${new#new=}" pending="${pending#pending=}" wake="${wake#wake=}" terminal="${terminal#terminal=}"
  if [ "$wake" = 1 ] && [ "$record_only" = 1 ]; then
    # Nothing records a wake in this mode: say it once, for the poll with new events.
    [ "$new" = 0 ] || notes="$notes wake=planned"
  elif [ "$wake" = 1 ] && [ "$terminal" = - ]; then
    eq note-wake "$logs" "$now" 0 - no_heartbeat
    notes="$notes wake=failed(no_heartbeat)"
  elif [ "$wake" = 1 ] && ! { call "$orca_exe" terminal wait --terminal "$terminal" --for tui-idle \
    --timeout-ms "$wake_wait_ms" --json >"$work/wait.json" 2>/dev/null; cj satisfied <"$work/wait.json"; }; then
    # Only into an idle terminal (AGENTS #282): text sent into a busy session or an open
    # question could answer it. The wake is tried again after 10 minutes.
    eq note-wake "$logs" "$now" 0 "$terminal" not_idle
    notes="$notes wake=failed(not_idle) terminal=$terminal"
  elif [ "$wake" = 1 ]; then
    text="有 $pending 個事件，請處理佇列：bash tools/ops/patrol.sh（處理完以 --done 標記）"
    if call "$orca_exe" terminal send --terminal "$terminal" --text "$text" --enter --json \
      >"$work/send.json" 2>/dev/null && cj ok <"$work/send.json"; then
      eq note-wake "$logs" "$now" 1 "$terminal" sent
      notes="$notes wake=sent terminal=$terminal"
    else
      eq note-wake "$logs" "$now" 0 "$terminal" send_failed
      notes="$notes wake=failed terminal=$terminal"
    fi
  fi
  eq beat "$logs" "$now" "$mode" "$gh_calls" "$$" "$gh_failed" "$gh_error"
  [ "$gh_failed" = 1 ] && notes="$notes gh_error=$(printf '%s' "$gh_error" | cut -c1-120)"
  log poll "gh_calls=$gh_calls $summary$notes" >/dev/null
  echo "poll $(iso "$now") gh_calls=$gh_calls ${summary}${notes}"
}

# A stop file left from before this start was meant for an earlier monitor.
stop_file="$logs/monitor.stop"
[ -e "$stop_file" ] && rm -f "$stop_file" && log stop_file_removed "" >/dev/null
log start "interval_s=$interval pid=$$" >/dev/null
while :; do
  poll
  [ "$once" = 1 ] && break
  # In the background, so a TERM ends the monitor now, not after the sleep.
  sleep "$interval" &
  wait $!
  if [ -e "$stop_file" ]; then
    rm -f "$stop_file"
    log stopped "by=$stop_file"
    break
  fi
done
