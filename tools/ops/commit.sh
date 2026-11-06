#!/usr/bin/env bash
# The coordinator's commitments (Issue #534; docs/COORDINATOR.md 無人值守運作 統籌承諾):
# a 統籌承諾 comment on the Issue, then this, so the promise outlives the session that
# made it. A one-off timer of the session is a reminder only: it dies with the session,
# the file does not. patrol.sh lists what is not kept yet, the ones past due marked, and
# take_over.sh prints the list to the next coordinator. The file and its fields are
# described in commitments.py.
#
# File written: <data>/logs/commitments.jsonl (one line appended per add or done).
#
# Usage:
#   commit.sh add --due DUE --url URL --text TEXT
#       DUE   when it is to be kept: 2026-11-07T09:23+08:00, 2026-11-07T01:23:00Z, or
#             none (no set time, such as "after the merge")
#       URL   the 統籌承諾 comment (…/issues/<n>#issuecomment-<id>); the Issue comes from it
#       TEXT  what is to be done, one line
#     prints the new id (c<N>)
#   commit.sh done ID [--url URL]   kept; URL is the comment that says so
#   commit.sh list                  what is not kept yet (as patrol.sh prints it)
# Options for all: --data-dir DIR (default $STOCK_DATA_DIR, then $HOME/stock-lab-data),
#   --python EXE (default $STOCK_PYTHON, then this checkout's .venv, then python3),
#   --session-id ID (default $CLAUDE_CODE_SESSION_ID; recorded, may be empty).
# Exit: 0 done; 64 bad arguments (nothing written); 3 done of an id never added; 2 no
#   logs/ directory or no Python.
# Test hook: PATROL_NOW (epoch seconds).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

command="${1:-}"
case "$command" in
  -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
  '') die "要給 add、done 或 list（--help 看用法）" 64 ;;
  add | done | list) shift ;;
  *) die "unknown command: $command（add、done、list）" 64 ;;
esac
session_id="${CLAUDE_CODE_SESSION_ID:-}" args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir | --python | --session-id)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
        --session-id) session_id="$2" ;;
      esac
      shift 2
      ;;
    *) args+=("$1"); shift ;;
  esac
done
case "$session_id" in *[!A-Za-z0-9_-]*) die "--session-id 只能有英數、_、-" 64 ;; esac
logs="$data_dir/logs"
[ -d "$logs" ] || die "資料目錄沒有 logs/：$logs" 2
find_python
now="${PATROL_NOW:-$(date -u +%s)}"
c() { "$python" -X utf8 "$script_dir/commitments.py" "$@"; }
case "$command" in
  list)
    [ ${#args[@]} -eq 0 ] || die "list 不收參數：${args[*]}" 64
    c list "$logs" "$now"
    ;;
  *) c "$command" "$logs" "$now" "$session_id" "${args[@]+"${args[@]}"}" ;;
esac
