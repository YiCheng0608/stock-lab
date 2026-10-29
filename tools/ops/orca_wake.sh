#!/usr/bin/env bash
# The waker of the event monitor (#338): wakes the coordinator terminal through the local
# Orca CLI, the way monitor.sh did itself in #316. monitor.sh runs it as
# `--waker <this script>` for each due wake; another waker (none, or one that reaches Orca
# from somewhere else) is swapped in with --waker without touching the queue logic.
#
# Usage: orca_wake.sh TERMINAL TEXT
#   Sends TEXT with Enter into TERMINAL only once `orca terminal wait --for tui-idle`
#   answers satisfied:true (AGENTS #282): text sent into a busy session or an open
#   question could answer it.
# Exit: 0 sent; 3 not idle (no answer, a timeout or a missing terminal included); 1 the
#   send failed. Environment: ORCA_EXE (default orca on PATH, then
#   $LOCALAPPDATA/Programs/orca/resources/bin/orca.exe), WAKE_WAIT_MS (default 15000),
#   MONITOR_CALL_TIMEOUT (seconds per orca call, default 120).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"
[ $# = 2 ] || die "usage: orca_wake.sh TERMINAL TEXT" 64
terminal="$1" text="$2"
find_python
orca_exe="${ORCA_EXE:-}"
if [ -z "$orca_exe" ]; then
  if command -v orca >/dev/null 2>&1; then
    orca_exe=orca
  else
    # The scheduler's PATH has no orca.
    orca_exe="${LOCALAPPDATA:-}/Programs/orca/resources/bin/orca.exe"
  fi
fi
call() { timeout -k 10 "${MONITOR_CALL_TIMEOUT:-120}" "$@"; }
out="$(call "$orca_exe" terminal wait --terminal "$terminal" --for tui-idle \
  --timeout-ms "${WAKE_WAIT_MS:-15000}" --json 2>/dev/null)"
printf '%s' "$out" | cj satisfied || exit 3
out="$(call "$orca_exe" terminal send --terminal "$terminal" --text "$text" --enter --json 2>/dev/null)" \
  && printf '%s' "$out" | cj ok || exit 1
exit 0
