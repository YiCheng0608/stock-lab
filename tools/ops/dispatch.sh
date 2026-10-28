#!/usr/bin/env bash
# Start an engineer session on an Issue (Issue #282; docs/GITHUB_WORKFLOW.md 任務流程第 2 步):
# Orca worktree from the latest base (origin/master, or --base: a long-lived integration
# branch such as origin/feat/docker, #332), branch task/<issue>-<slug>, a visible
# terminal running claude with COMPOSE_PROJECT_NAME=task-<issue> (#339), and the task
# text from a UTF-8 file sent only after `orca terminal wait --for tui-idle` reports
# satisfied:true. Sets the board to 開發中.
#
# Usage: dispatch.sh <issue> <slug> --task-file <path> [options]
#   --model M         default claude-opus-5-5
#   --effort E        default high
#   --base REF        origin/<branch> to start from, default origin/master; fetched first,
#                     and the new worktree's HEAD must be its tip
#   --repo-id ID      Orca repo id; default: the repo whose remote is YiCheng0608/stock-lab
#   --wait-ms N       tui-idle wait, default 60000
#   --submit-wait S   seconds to watch for turn_started after sending, default 30
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --no-board        leave the board alone (a dry run on a throwaway branch)
# Prints one JSON line (worktree, branch, head, terminal, sent, turn_started, board, error).
# Exit 0 when sent and started; 1 before sending (nothing was sent); 3 the text may be
# in the terminal but the turn was not seen starting, or the send itself failed or was
# not accepted ("sent": null, read the terminal, do not resend); 4 board update failed;
# 2/64 bad setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

issue="" slug="" task_file="" model="claude-opus-5-5" effort="high" repo_id=""
base_ref="origin/master"
wait_ms=60000 submit_wait=30 set_board=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-board) set_board=0 ;;
    --task-file | --model | --effort | --base | --repo-id | --wait-ms | --submit-wait | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --task-file) task_file="$2" ;;
        --model) model="$2" ;;
        --effort) effort="$2" ;;
        --base) base_ref="$2" ;;
        --repo-id) repo_id="$2" ;;
        --wait-ms) wait_ms="$2" ;;
        --submit-wait) submit_wait="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      continue
      ;;
    -*) die "unknown argument: $1" 64 ;;
    *)
      if [ -z "$issue" ]; then issue="$1"
      elif [ -z "$slug" ]; then slug="$1"
      else die "unexpected argument: $1" 64
      fi
      ;;
  esac
  shift
done

case "$issue" in '' | *[!0-9]*) die "<issue> must be a number" 64 ;; esac
case "$slug" in '' | -* | *[!a-z0-9-]*) die "<slug> uses a-z, 0-9 and '-' only" 64 ;; esac
case "$model$effort" in *[!A-Za-z0-9._-]*) die "--model/--effort: letters, digits, '.', '_', '-' only" 64 ;; esac
case "$wait_ms$submit_wait" in *[!0-9]*) die "--wait-ms/--submit-wait must be numbers" 64 ;; esac
# A ref git and orca take as one argument: origin/<branch>, no option or range spelling.
base_branch="${base_ref#origin/}"
case "$base_ref" in origin/?*) ;; *) die "--base must be origin/<branch>: $base_ref" 64 ;; esac
case "$base_branch" in -* | /* | */ | *..* | *[!A-Za-z0-9._/-]*) die "--base: bad branch name: $base_ref" 64 ;; esac
[ -n "$task_file" ] || die "--task-file is required" 64
find_python
cj utf8 "$task_file" || die "任務檔不存在、是空的或不是 UTF-8：$task_file" 64
[ "$(wc -c <"$task_file")" -le 30000 ] || die "任務檔超過 30000 bytes（Windows 命令列上限）" 64

branch="task/$issue-$slug"
name="task-$issue-$slug"
path="" head="" base="" handle="" sent=false started=false board=""

report() { # report EXIT [ERROR]
  local error=null
  [ -n "${2:-}" ] && error="$(json_str "$2")"
  printf '{"issue":%s,"worktree":%s,"branch":%s,"head":%s,"base":%s,"terminal":%s,"sent":%s,"turn_started":%s,"board":%s,"error":%s}\n' \
    "$issue" "$(json_str "$path")" "$(json_str "$branch")" "$(json_str "$head")" "$(json_str "$base")" \
    "$(json_str "$handle")" "$sent" "$started" "$(json_str "$board")" "$error"
  [ -n "${2:-}" ] && printf 'dispatch.sh: %s\n' "$2" >&2
  exit "$1"
}

git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch" && report 1 "branch $branch 已存在，未建 worktree"
git -C "$repo_root" fetch --quiet origin "$base_branch" || report 1 "git fetch origin $base_branch 失敗"
base="$(git -C "$repo_root" rev-parse "$base_ref")" || report 1 "讀不到 $base_ref"
orca_repo_id

# Without --base orca uses the repo's default base, as before #332; the HEAD check below
# holds either way.
from_base=()
[ "$base_ref" = origin/master ] || from_base=(--base-branch "$base_ref")
out="$(orca worktree create --repo "id:$repo_id" --name "$name" --no-parent --setup skip \
  "${from_base[@]+"${from_base[@]}"}" --json)" \
  || report 1 "orca worktree create 失敗：$(printf '%s' "$out" | cj get error.message)"
path="$(printf '%s' "$out" | cj get result.worktree.path)" || report 1 "orca worktree create 沒有回傳 path"
orca_branch="$(printf '%s' "$out" | cj get result.worktree.branch)" || report 1 "orca worktree create 沒有回傳 branch"
orca_branch="${orca_branch#refs/heads/}"
head="$(git -C "$path" rev-parse HEAD)" || report 1 "讀不到新 worktree 的 HEAD"
[ "$head" = "$base" ] || report 1 "新 worktree 的 HEAD 不是最新 $base_ref，未開 terminal"
if [ "$orca_branch" != "$branch" ]; then
  git -C "$path" branch -m "$orca_branch" "$branch" || report 1 "branch 改名失敗：$orca_branch → $branch"
fi

# The task's compose project (docs/GITHUB_WORKFLOW.md 本機檢查, #339): a docker compose run
# without -p uses task-<issue>, not the directory name. The prefix is POSIX shell syntax, for
# Orca's default Git Bash; in another shell claude does not start, the wait below is not
# satisfied and nothing is sent.
out="$(orca terminal create --worktree "id:$repo_id::$path" --title "#$issue $slug" \
  --command "COMPOSE_PROJECT_NAME=task-$issue claude --model $model --effort $effort" --json)" \
  || report 1 "orca terminal create 失敗"
handle="$(printf '%s' "$out" | cj get result.terminal.handle)" || report 1 "orca terminal create 沒有回傳 handle"

# The flag is --timeout-ms: with a wrong flag wait returns ok:false at once and the text
# sent next is swallowed by Claude Code's start-up screen. Only satisfied:true sends.
out="$(orca terminal wait --terminal "$handle" --for tui-idle --timeout-ms "$wait_ms" --json)"
printf '%s' "$out" | cj satisfied || report 1 "terminal 未就緒（wait 沒有 satisfied:true），任務未送出"

# No CR: in Claude Code's prompt a carriage return is Enter and would submit early.
out="$(orca terminal send --terminal "$handle" --text "$(tr -d '\r' <"$task_file")" --enter \
  --wait-submit "$submit_wait" --json)" \
  || { sent=null; report 3 "orca terminal send 失敗，文字可能已送出：先 orca terminal read，不要重送"; }
[ "$(printf '%s' "$out" | cj get result.send.accepted)" = true ] \
  || { sent=null; report 3 "orca terminal send 未回報接受，文字可能已送出：先 orca terminal read，不要重送"; }
sent=true
case " $(printf '%s' "$out" | cj stages) " in *" turn_started "*) started=true ;; esac
# Read back: the terminal tail goes to stderr for the coordinator to look at.
orca terminal read --terminal "$handle" --limit 15 --json | cj get result.terminal.tail \
  | "$python" -X utf8 -c 'import json,sys; [print("  |", l, file=sys.stderr) for l in json.load(sys.stdin)]' || true
[ "$started" = true ] || report 3 "已送出但 ${submit_wait} 秒內未見 turn_started；先 orca terminal read 檢查，不要重送"

if [ "$set_board" = 1 ]; then
  board="$(board_set "$issue" 開發中)" || { board=failed; report 4 "看板未設成開發中，請手動設定"; }
else
  board=skipped
fi
report 0
