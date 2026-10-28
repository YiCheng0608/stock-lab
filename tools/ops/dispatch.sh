#!/usr/bin/env bash
# Start an engineer session on an Issue (Issue #282; docs/GITHUB_WORKFLOW.md 任務流程第 2 步):
# Orca worktree from the latest base (origin/master, or --base: a long-lived integration
# branch such as origin/feat/docker, #332), branch task/<issue>-<slug>, a visible
# terminal running claude, and, only after `orca terminal wait --for tui-idle` reports
# satisfied:true, one line pointing at the UTF-8 task file outside the worktree (#315):
#   請用 Read 工具讀取任務檔 <path>（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。
# <path> is the task file's absolute path (C:/… on Windows). The task text is never typed
# into the terminal, so it has no size limit and no character in it needs escaping.
# claude starts with --add-dir "<the task file's directory>", so reading it needs no
# permission prompt whatever the session's permission mode.
# Sets the board to 開發中.
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
# Prints one JSON line (worktree, branch, head, terminal, task_file, sent, turn_started,
# board, error).
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
case "$task_file" in *$'\n'* | *$'\r'*) die "任務檔路徑不能有換行" 64 ;; esac
find_python
cj utf8 "$task_file" || die "任務檔不存在、是空的或不是 UTF-8：$task_file" 64
# The engineer session opens the file itself: an absolute path in the spelling a Windows
# program opens (C:/…, not /c/…).
task_path="$(cd "$(dirname -- "$task_file")" && pwd)/$(basename -- "$task_file")" \
  && task_path="$(native "$task_path")" || die "任務檔路徑無法轉成絕對路徑：$task_file" 64
task_dir="${task_path%/*}"
case "$task_dir" in '' | *:) task_dir="$task_dir/" ;; esac
# --command is typed into the terminal's shell (cmd, PowerShell or bash); inside double
# quotes none of them expands a path free of these characters.
case "$task_dir" in *['"$`%!']*) die "任務檔目錄不能含 \" \$ \` % !（會進 claude 的 --add-dir）：$task_dir" 64 ;; esac
notice="請用 Read 工具讀取任務檔 $task_path（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。"

branch="task/$issue-$slug"
name="task-$issue-$slug"
path="" head="" base="" handle="" sent=false started=false board=""

report() { # report EXIT [ERROR]
  local error=null
  [ -n "${2:-}" ] && error="$(json_str "$2")"
  printf '{"issue":%s,"worktree":%s,"branch":%s,"head":%s,"base":%s,"terminal":%s,"task_file":%s,"sent":%s,"turn_started":%s,"board":%s,"error":%s}\n' \
    "$issue" "$(json_str "$path")" "$(json_str "$branch")" "$(json_str "$head")" "$(json_str "$base")" \
    "$(json_str "$handle")" "$(json_str "$task_path")" "$sent" "$started" "$(json_str "$board")" "$error"
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

out="$(orca terminal create --worktree "id:$repo_id::$path" --title "#$issue $slug" \
  --command "claude --model $model --effort $effort --add-dir \"$task_dir\"" --json)" || report 1 "orca terminal create 失敗"
handle="$(printf '%s' "$out" | cj get result.terminal.handle)" || report 1 "orca terminal create 沒有回傳 handle"

# The flag is --timeout-ms: with a wrong flag wait returns ok:false at once and the text
# sent next is swallowed by Claude Code's start-up screen. Only satisfied:true sends.
out="$(orca terminal wait --terminal "$handle" --for tui-idle --timeout-ms "$wait_ms" --json)"
printf '%s' "$out" | cj satisfied || report 1 "terminal 未就緒（wait 沒有 satisfied:true），任務未送出"

out="$(orca terminal send --terminal "$handle" --text "$notice" --enter \
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
