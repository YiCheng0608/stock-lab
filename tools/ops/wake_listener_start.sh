#!/usr/bin/env bash
# Start the wake listener (tools/ops/wake_listener.py, #338) unless it already runs: the
# coordinator session runs this when it takes over and when it handles the queue
# (docs/GITHUB_WORKFLOW.md 統籌 session, 無人值守運作). The listener only wakes the
# coordinator, so it lives with the coordinator sessions, not as a Windows startup item
# (the user's decision, #338). It reads the coordinator heartbeat before every wake, so
# a listener left by an earlier coordinator wakes the new one: it is kept, not replaced.
#
# The listener runs in the background (nohup) and outlives this shell and the tool call
# that ran it, but not the Orca terminal of the session that started it: closing a
# terminal ends all its processes (seen 2026-10-29, with PowerShell's Start-Process too).
# So a coordinator that closed its predecessor's terminal runs this again
# (docs/OPERATIONS.md §6.8).
# The token file's path is written here, not in the coordinator's command: a command
# naming it is stopped by the agent guard (AGENTS.md).
#
# Usage: wake_listener_start.sh [--status]
#   --status   report only, start nothing (patrol.sh)
# Exit: 0 the listener answers (it ran, or now runs; --status: it runs); 1 it could not
#   be started (the reason is printed; --status: it does not run); 2 another program
#   holds the port.
# Test hooks: WAKE_LISTENER_PORT, WAKE_LISTENER_TOKEN_FILE, WAKE_LISTENER_ORCA (the
#   listener's --orca, which it needs when STOCK_WAKE_TEST is set).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

status_only=0
case "${1:-}" in
  '') ;;
  --status) status_only=1 ;;
  *) die "usage: wake_listener_start.sh [--status]" 64 ;;
esac
port="${WAKE_LISTENER_PORT:-47338}"
# The env file of the release checkout, which compose gives the scheduler (OPERATIONS §6.8).
token_file="${WAKE_LISTENER_TOKEN_FILE:-C:/Users/YiCheng/stock-lab-release/.env}"
logs="$data_dir/logs"

# state: up (the listener answers /health), down (nothing listens) or taken (something
# else answers on the port).
state() {
  local out
  out="$(curl -sS -m 5 "http://127.0.0.1:$port/health" 2>/dev/null)"
  case $? in
    0) case "$out" in *'"service": "stock-lab-wake"'*) echo up ;; *) echo taken ;; esac ;;
    7) echo down ;;
    *) echo taken ;;
  esac
}

now="$(state)"
case "$now" in
  up)
    echo "wake listener：執行中（127.0.0.1:$port）"
    exit 0
    ;;
  taken)
    echo "wake listener：127.0.0.1:$port 被別的程序占用，listener 無法啟動；查占用者：Get-NetTCPConnection -LocalPort $port" >&2
    exit 2
    ;;
esac
if [ "$status_only" = 1 ]; then
  echo "wake listener：沒在跑（容器的 monitor 無法喚醒統籌；跑 bash tools/ops/wake_listener_start.sh）"
  exit 1
fi

find_python
mkdir -p "$logs" || die "建不了 $logs" 1
out_file="$logs/wake-listener.out"
orca_args=()
[ -n "${WAKE_LISTENER_ORCA:-}" ] && orca_args=(--orca "$WAKE_LISTENER_ORCA")
nohup "$python" -X utf8 "$script_dir/wake_listener.py" --token-file "$token_file" \
  --data-dir "$data_dir" --port "$port" "${orca_args[@]}" </dev/null >>"$out_file" 2>&1 &
pid=$!  # this shell's pid of it, which on Windows is not the one Stop-Process takes
for _ in $(seq 1 40); do
  if [ "$(state)" = up ]; then
    echo "wake listener：已啟動（127.0.0.1:$port，日誌 $logs/wake-listener.log；停止：Stop-Process -Id (Get-NetTCPConnection -LocalPort $port -State Listen).OwningProcess）"
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.25
done
echo "wake listener：啟動失敗：$(tail -n 1 "$out_file" 2>/dev/null)" >&2
kill "$pid" 2>/dev/null
exit 1
