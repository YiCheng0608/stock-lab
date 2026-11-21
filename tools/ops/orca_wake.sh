#!/usr/bin/env bash
# The waker of the event monitor (#338): wakes the coordinator terminal through the local
# Orca CLI, the way monitor.sh did itself in #316. monitor.sh runs it as
# `--waker <this script>` for each due wake; another waker (none, or one that reaches Orca
# from somewhere else) is swapped in with --waker without touching the queue logic.
#
# Usage: orca_wake.sh TERMINAL TEXT
#   Sends TEXT with Enter into TERMINAL only once `orca terminal wait --for tui-idle`
#   answers satisfied:true (GUARDRAILS #282): text sent into a busy session or an open
#   question could answer it.
# Exit: 0 sent; 3 not idle (no answer, a timeout or a missing terminal included); 4 the
#   coordinator stopped at a permission or trust menu (#720): the wait timed out and
#   `orca terminal show` names the menu (agentWait), or the send was refused with
#   agent_prompt_blocked; 1 the send failed. Nothing here answers the menu: that is the
#   user's decision. Environment: ORCA_EXE (default orca on PATH, then
#   $LOCALAPPDATA/Programs/orca/resources/bin/orca.exe), WAKE_WAIT_MS (default 15000),
#   MONITOR_CALL_TIMEOUT (seconds per orca call, default 120).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"
[ $# = 2 ] || die "usage: orca_wake.sh TERMINAL TEXT" 64
terminal="$1" text="$2"
# A handle orca could read as an option is never sent to (event_queue.py HANDLE).
case "$terminal" in [A-Za-z0-9_]*) ;; *) die "orca_wake.sh: not a handle: $terminal" 64 ;; esac
case "$terminal" in *[!A-Za-z0-9_-]*) die "orca_wake.sh: not a handle: $terminal" 64 ;; esac
find_python
orca_exe="${ORCA_EXE:-}"
if [ -z "$orca_exe" ]; then
  if command -v orca >/dev/null 2>&1; then
    orca_exe=orca
  else
    # The scheduler's PATH has no orca. Orca's install directory: Windows, then macOS.
    orca_exe="${LOCALAPPDATA:-}/Programs/orca/resources/bin/orca.exe"
    [ -x "$orca_exe" ] || [ ! -x /Applications/Orca.app/Contents/Resources/bin/orca ] || orca_exe=/Applications/Orca.app/Contents/Resources/bin/orca
  fi
fi
call() { timeout -k 10 "${MONITOR_CALL_TIMEOUT:-120}" "$@"; }
out="$(call "$orca_exe" terminal wait --terminal="$terminal" --for tui-idle \
  --timeout-ms "${WAKE_WAIT_MS:-15000}" --json 2>/dev/null)"
if ! printf '%s' "$out" | cj satisfied; then
  # agentWait is not in Orca's CLI docs: `orca terminal show` fills it from the runtime's
  # getTerminalInteractiveWait (Orca's app.asar, read 2026-11-15): null when the agent
  # waits on nothing, an object ({"source": "hook"|"title"|"prompt-text", ...}) while it
  # shows a permission or trust menu, absent when Orca cannot tell. An Orca release may
  # drop or rename it: anything but an object (absent, null, a failed show, no JSON) is
  # read as before, not idle.
  out="$(call "$orca_exe" terminal show --terminal="$terminal" --json 2>/dev/null)"
  waiting_on="$(printf '%s' "$out" | cj get result.terminal.agentWait 2>/dev/null)"
  case "$waiting_on" in '{'*) exit 4 ;; esac
  exit 3
fi
out="$(call "$orca_exe" terminal send --terminal="$terminal" --text "$text" --enter --json 2>/dev/null)"
printf '%s' "$out" | cj ok && exit 0
# The menu opened between the wait and the send: Orca refuses a text-plus-Enter prompt
# to an agent at a permission or trust menu (orca skills get orca-cli).
[ "$(printf '%s' "$out" | cj get error.code 2>/dev/null)" = agent_prompt_blocked ] && exit 4
exit 1
