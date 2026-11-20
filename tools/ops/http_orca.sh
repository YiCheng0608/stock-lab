#!/usr/bin/env bash
# `orca worktree list --json` for the event monitor in the scheduler container (#338): the
# container has no Orca, so the host's wake listener (tools/ops/wake_listener.py) answers
# POST /worktrees with the task worktrees' branches, in the envelope monitor.sh reads.
# monitor.sh runs it as `--orca <this script>`. `terminal list --json` is POST /terminals
# (#873): the engineer terminals of the task worktrees with their agentWait and the menu's
# command (wake_listener.py engineer_terminals), not Orca's own listing. It knows no
# other orca command.
#
# Usage: http_orca.sh worktree list --json | http_orca.sh terminal list --json
# Exit: 0 with the envelope on stdout; 1 when the listener gives no list (then the poll
#   records no slot event, rather than taking it for free slots, and leaves the engineer
#   menus as they were); 64 another command.
# Environment: as tools/ops/http_wake.sh.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"
case "$*" in
  "worktree list --json") listener_post /worktrees ;;
  "terminal list --json") listener_post /terminals ;;
  *) die "http_orca.sh: only 'worktree list --json' or 'terminal list --json'" 64 ;;
esac
