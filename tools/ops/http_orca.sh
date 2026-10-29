#!/usr/bin/env bash
# `orca worktree list --json` for the event monitor in the scheduler container (#338): the
# container has no Orca, so the host's wake listener (tools/ops/wake_listener.py) answers
# POST /worktrees with the task worktrees' branches, in the envelope monitor.sh reads.
# monitor.sh runs it as `--orca <this script>`; it knows no other orca command.
#
# Usage: http_orca.sh worktree list --json
# Exit: 0 with the envelope on stdout; 1 when the listener gives no list (then the poll
#   records no slot event, rather than taking it for free slots); 64 another command.
# Environment: as tools/ops/http_wake.sh.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"
[ "$*" = "worktree list --json" ] || die "http_orca.sh: only 'worktree list --json'" 64
listener_post /worktrees
