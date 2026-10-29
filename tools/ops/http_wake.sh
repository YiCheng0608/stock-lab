#!/usr/bin/env bash
# Waker of the event monitor in the scheduler container (#338, B3): asks the wake
# listener on the Windows host (tools/ops/wake_listener.py) to wake the coordinator.
# monitor.sh runs it as `--waker <this script>` with the waker arguments TERMINAL TEXT;
# neither is sent: the listener takes the terminal from the coordinator heartbeat and
# words the line itself, so nothing the container holds reaches the terminal as text.
#
# Usage: http_wake.sh TERMINAL TEXT
# Exit: 0 sent; 3 not idle; 1 anything else (no listener, token refused, no heartbeat on
#   the host, throttled...), which monitor.sh records as a failed wake, tried again
#   after 10 minutes.
# Environment: STOCK_WAKE_TOKEN (the env file, docs/OPERATIONS.md §6.8), STOCK_WAKE_URL
#   (default http://host.docker.internal:47338/wake).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"
[ $# = 2 ] || die "usage: http_wake.sh TERMINAL TEXT" 64
answer="$(listener_post /wake)"
status=$?
case "$status $answer" in
  '0 {"result": "sent"}') exit 0 ;;
  '0 {"result": "not_idle"}') exit 3 ;;
esac
echo "http_wake.sh: ${answer:-no answer}" >&2
exit 1
