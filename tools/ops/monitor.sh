#!/usr/bin/env bash
# Coordinator event monitor (Issue #316; docs/GITHUB_WORKFLOW.md 無人值守運作,
# docs/OPERATIONS.md §6.6), resident under Windows Task Scheduler
# (tools/ops/Register-Monitor.ps1). No LLM: every --interval seconds it polls the open
# PRs (CI, mergeStateStatus), the repository's new Issue/PR comments, the task
# worktrees and the job logs, appends the events not queued yet to
# <data>/logs/events.jsonl (tools/ops/event_queue.py) and sends the coordinator terminal
# of the heartbeat one line "有 N 個事件…" for them. When the queue has waited an hour
# with no coordinator heartbeat since, it comments on #1 asking the user to open a
# coordinator; it never opens a session itself (#1 6245309556, 6320448594).
#
# gh: at most 2 calls per poll (open PRs, then comments; the #1 comment takes the
# comments' turn) and polls at least 60 seconds apart: the 5000/hour API limit is
# shared by every session on the account. One monitor at a time (logs/monitor.lock/).
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
# Test hook: MONITOR_NOW (epoch seconds, with --once).
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
# for 10 minutes, was left by a killed run and is taken over.
if ! mkdir "$lock_dir" 2>/dev/null; then
  owner="$(cat "$lock_dir/pid" 2>/dev/null)"
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
printf '%s\n' "$$" >"$lock_dir/pid"
trap 'rm -rf "$lock_dir"' EXIT
trap 'exit 143' INT TERM

poll() {
  local now gh_calls=0 since summary new pending wake terminal stale_line key body url
  local args=() ro=() work notes="" text out
  now="$(clock)"
  work="$lock_dir/work"
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
  gh_calls=$((gh_calls + 1))
  if gh pr list --repo "$GH_REPO" --state open --limit 30 \
    --json number,title,url,isDraft,headRefOid,mergeStateStatus,statusCheckRollup,labels \
    >"$work/prs.json" 2>"$work/gh.err"; then
    args+=(--prs "$work/prs.json")
  else
    notes="$notes prs=failed"
  fi

  # 3. the #1 comment or new comments
  if [ -n "$key" ] && [ "$record_only" = 1 ]; then
    eq note-stale "$logs" "$now" "$key" -
    notes="$notes stale=planned"
  elif [ -n "$key" ]; then
    gh_calls=$((gh_calls + 1))
    printf '%s\n' "$body" >"$work/comment.md"
    if url="$(gh issue comment 1 --repo "$GH_REPO" --body-file "$work/comment.md" 2>>"$work/gh.err")"; then
      url="$(printf '%s' "$url" | tr -d '\r' | tail -n 1)"
      eq note-stale "$logs" "$now" "$key" "${url:-?}"
      notes="$notes stale=commented url=$url"
    else
      notes="$notes stale=comment_failed"
    fi
  fi
  if [ -z "$key" ]; then
    since="$(eq since "$logs" "$now")"
    gh_calls=$((gh_calls + 1))
    if gh api "repos/$GH_REPO/issues/comments?since=$since&sort=updated&direction=asc&per_page=100" \
      >"$work/comments.json" 2>>"$work/gh.err"; then
      args+=(--comments "$work/comments.json")
    else
      notes="$notes comments=failed"
    fi
  fi

  # 4. task worktrees (Orca, no gh)
  if "$orca_exe" worktree list --json >"$work/worktrees.json" 2>/dev/null; then
    args+=(--worktrees "$work/worktrees.json")
  else
    notes="$notes worktrees=failed"
  fi

  # 5. queue, then wake
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
  elif [ "$wake" = 1 ]; then
    text="有 $pending 個事件，請處理佇列：bash tools/ops/patrol.sh（處理完以 --done 標記）"
    if "$orca_exe" terminal send --terminal "$terminal" --text "$text" --enter --json \
      >"$work/send.json" 2>/dev/null && cj ok <"$work/send.json"; then
      eq note-wake "$logs" "$now" 1 "$terminal" sent
      notes="$notes wake=sent terminal=$terminal"
    else
      eq note-wake "$logs" "$now" 0 "$terminal" send_failed
      notes="$notes wake=failed terminal=$terminal"
    fi
  fi
  eq beat "$logs" "$now" "$mode" "$gh_calls" "$$"
  log poll "gh_calls=$gh_calls $summary$notes" >/dev/null
  echo "poll $(iso "$now") gh_calls=$gh_calls ${summary}${notes}"
}

log start "interval_s=$interval pid=$$" >/dev/null
while :; do
  poll
  [ "$once" = 1 ] && break
  sleep "$interval"
done
