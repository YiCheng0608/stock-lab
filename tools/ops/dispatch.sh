#!/usr/bin/env bash
# Start an engineer session on an Issue (Issue #282; docs/GITHUB_WORKFLOW.md 任務流程第 2 步):
# Orca worktree from the latest origin/master, branch task/<issue>-<slug>, a visible
# terminal running claude, and the task text from a UTF-8 file sent only after
# `orca terminal wait --for tui-idle` reports satisfied:true. Sets the board to 開發中.
#
# Usage: dispatch.sh <issue> <slug> --task-file <path> [options]
#   --model M         default claude-opus-5-5
#   --effort E        default high
#   --repo-id ID      Orca repo id; default: the repo whose remote is YiCheng0608/stock-lab
#   --wait-ms N       tui-idle wait, default 60000
#   --submit-wait S   seconds to watch for turn_started after sending, default 30
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --no-board        leave the board alone (a dry run on a throwaway branch)
# Prints one JSON line (worktree, branch, head, terminal, sent, turn_started, board, error).
# Exit 0 when sent and started; 1 before sending (nothing was sent); 3 sent but the turn
# was not seen starting (read the terminal, do not resend); 4 board update failed;
# 2/64 bad setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

issue="" slug="" task_file="" model="claude-opus-5-5" effort="high" repo_id=""
wait_ms=60000 submit_wait=30 set_board=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) sed -n '2,19p' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-board) set_board=0 ;;
    --task-file | --model | --effort | --repo-id | --wait-ms | --submit-wait | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --task-file) task_file="$2" ;;
        --model) model="$2" ;;
        --effort) effort="$2" ;;
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
git -C "$repo_root" fetch --quiet origin master || report 1 "git fetch origin master 失敗"
base="$(git -C "$repo_root" rev-parse origin/master)" || report 1 "讀不到 origin/master"
orca_repo_id

out="$(orca worktree create --repo "id:$repo_id" --name "$name" --no-parent --setup skip --json)" \
  || report 1 "orca worktree create 失敗：$(printf '%s' "$out" | cj get error.message)"
path="$(printf '%s' "$out" | cj get result.worktree.path)" || report 1 "orca worktree create 沒有回傳 path"
orca_branch="$(printf '%s' "$out" | cj get result.worktree.branch)" || report 1 "orca worktree create 沒有回傳 branch"
orca_branch="${orca_branch#refs/heads/}"
head="$(git -C "$path" rev-parse HEAD)" || report 1 "讀不到新 worktree 的 HEAD"
[ "$head" = "$base" ] || report 1 "新 worktree 的 HEAD 不是最新 origin/master，未開 terminal"
if [ "$orca_branch" != "$branch" ]; then
  git -C "$path" branch -m "$orca_branch" "$branch" || report 1 "branch 改名失敗：$orca_branch → $branch"
fi

out="$(orca terminal create --worktree "id:$repo_id::$path" --title "#$issue $slug" \
  --command "claude --model $model --effort $effort" --json)" || report 1 "orca terminal create 失敗"
handle="$(printf '%s' "$out" | cj get result.terminal.handle)" || report 1 "orca terminal create 沒有回傳 handle"

# The flag is --timeout-ms: with a wrong flag wait returns ok:false at once and the text
# sent next is swallowed by Claude Code's start-up screen. Only satisfied:true sends.
out="$(orca terminal wait --terminal "$handle" --for tui-idle --timeout-ms "$wait_ms" --json)"
printf '%s' "$out" | cj satisfied || report 1 "terminal 未就緒（wait 沒有 satisfied:true），任務未送出"

# No CR: in Claude Code's prompt a carriage return is Enter and would submit early.
out="$(orca terminal send --terminal "$handle" --text "$(tr -d '\r' <"$task_file")" --enter \
  --wait-submit "$submit_wait" --json)" || report 1 "orca terminal send 失敗，任務未確認送出（先 terminal read 再決定）"
[ "$(printf '%s' "$out" | cj get result.send.accepted)" = true ] || report 1 "orca terminal send 未被接受"
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
