#!/usr/bin/env bash
# Start an engineer session on an Issue (Issue #282; docs/WORKFLOW.md 任務流程第 2 步):
# Orca worktree from the latest base (origin/master, or --base: a long-lived integration
# branch listed in close_task.sh, origin/<branch>, #332), branch task/<issue>-<slug>, a visible
# terminal running claude with COMPOSE_PROJECT_NAME=task-<issue> (#339) and
# CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 (#595: Claude Code would otherwise kill the
# session's background shells when the host runs low on memory and tell the engineer to
# wait for a person; a shell holds little memory, the containers' memory is the VM's), and, only after
# `orca terminal wait --for tui-idle` reports satisfied:true, one line pointing at the
# UTF-8 task file outside the worktree (#315):
#   請用 Read 工具讀取任務檔 <path>（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。
# <path> is the task file's absolute path (C:/… on Windows). The task text is never typed
# into the terminal, so it has no size limit and no character in it needs escaping.
# claude starts with --settings '{"permissions":{"additionalDirectories":["<the task file's
# directory>"]}}', so reading it needs no permission prompt whatever the session's
# permission mode. Not --add-dir: from Claude Code 2.1.326 a directory given there that
# no trusted directory holds stops the start at a "Adding a new directory" trust menu,
# every session anew (#835 AC-1: tried in a separate terminal, the settings form asks
# nothing, in auto and in default mode).
# After tui-idle (it is satisfied with a menu open) and before the line is sent, the
# screen is read (orca terminal read --screen): a trust or permission menu on it
# (menu_marks below) sends nothing, not even Enter, and is exit 5; so is a send Orca
# refuses with agent_prompt_blocked (#720). Only the user answers such a menu.
# Sets the board to 開發中. Before the worktree is made, the codebase-memory master index
# (#704; cbm_ensure in coordinator_lib.sh): from origin/master this checkout is first
# fast-forwarded to it (on master, no uncommitted change to a tracked file), then the files
# the newest merges of its HEAD changed are verified with the same-engine CLI and a stale
# index rebuilt once; a checkout that cannot be fast-forwarded, an index still stale, or
# the CLI missing or timing out is exit 1 with nothing created or sent. From another
# --base the checkout is left as it is and the index matches master only.
#
# Usage: dispatch.sh <issue> <slug> --task-file <path> [options]
#   --model M         default claude-opus-5-5
#   --effort E        default medium
#   --base REF        origin/<branch> to start from, default origin/master; fetched first,
#                     and the new worktree's HEAD must be its tip
#   --repo-id ID      Orca repo id; default: the repo whose remote is YiCheng0608/stock-lab
#   --wait-ms N       tui-idle wait, default 60000
#   --submit-wait S   seconds to watch for turn_started after sending, default 30
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --no-board        leave the board alone (a dry run on a throwaway branch)
# Prints one JSON line (worktree, branch, head, terminal, task_file, settings: the
# --settings JSON claude got, to copy into a resume command as it is, index: the index
# steps comma-separated or "failed", sent, turn_started, board, error).
# Exit 0 when sent and started; 1 before sending (nothing was sent); 3 the text may be
# in the terminal but the turn was not seen starting, or the send itself failed or was
# not accepted ("sent": null, read the terminal, do not resend); 4 board update failed;
# 5 the terminal is at a trust or permission menu, nothing sent (the user answers it in
# that terminal, then the coordinator sends the line by hand, docs/WORKFLOW.md step 2;
# do not rerun dispatch.sh: the branch exists); 2/64 bad setup or arguments.
{
# The whole script is one brace group: bash reads all of it before running any, so a
# fast-forward of this checkout that rewrites this file mid-run (#704 review) cannot
# change what runs next.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

issue="" slug="" task_file="" model="claude-opus-5-5" effort="medium" repo_id=""
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
# --command is typed into the terminal's shell (cmd, PowerShell or bash); none of them
# expands a path free of these characters, and the settings JSON is in single quotes.
case "$task_dir" in *['"$`%!'\']*) die "任務檔目錄不能含 \" \$ \` % ! '（會進 claude 的 --settings）：$task_dir" 64 ;; esac
# The task directory as claude's settings (#835): ASCII-only JSON (\u escapes), so nothing
# but ASCII is typed into the terminal for it.
settings="$(printf '%s' "$task_dir" | "$python" -X utf8 -c 'import json,sys; sys.stdout.write(json.dumps({"permissions": {"additionalDirectories": [sys.stdin.read()]}}, separators=(",", ":")))')" \
  || die "任務檔目錄無法寫成 claude 的設定：$task_dir" 64
notice="請用 Read 工具讀取任務檔 $task_path（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。"

branch="task/$issue-$slug"
name="task-$issue-$slug"
path="" head="" base="" handle="" sent=false started=false board="" index=""

report() { # report EXIT [ERROR]
  local error=null
  [ -n "${2:-}" ] && error="$(json_str "$2")"
  printf '{"issue":%s,"worktree":%s,"branch":%s,"head":%s,"base":%s,"terminal":%s,"task_file":%s,"settings":%s,"index":%s,"sent":%s,"turn_started":%s,"board":%s,"error":%s}\n' \
    "$issue" "$(json_str "$path")" "$(json_str "$branch")" "$(json_str "$head")" "$(json_str "$base")" \
    "$(json_str "$handle")" "$(json_str "$task_path")" "$(json_str "$settings")" "$(json_str "$index")" "$sent" "$started" "$(json_str "$board")" "$error"
  [ -n "${2:-}" ] && printf 'dispatch.sh: %s\n' "$2" >&2
  exit "$1"
}

git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch" && report 1 "branch $branch 已存在，未建 worktree"
git -C "$repo_root" fetch --quiet origin "$base_branch" || report 1 "git fetch origin $base_branch 失敗"
base="$(git -C "$repo_root" rev-parse "$base_ref")" || report 1 "讀不到 $base_ref"
orca_repo_id

# The master index (#704), before anything is created. From origin/master (the default)
# the management checkout is fast-forwarded to the tip just fetched first, so the index is
# checked against what the new worktree starts from (#704 review: a merge not yet closed
# with close_task.sh); from another base it is not, and the index matches only master.
# A stale index is rebuilt once (and forced once when only the mtime rule is left); still
# stale, or no answer, stops here.
if [ "$base_ref" = origin/master ]; then
  checkout_fast_forward || { index=failed; report 1 "索引驗證：管理 checkout 更新：$cbm_error"; }
fi
index_paths="$(cbm_recent_paths)" || report 1 "索引驗證：讀不到最近 $cbm_recent_merges 次合併改到的檔案"
# A failure is "failed", then any index_waited:<seconds> (#766), so the receipt shows a wait.
cbm_ensure check "$index_paths" || {
  index=failed
  for step in "${cbm_steps[@]+"${cbm_steps[@]}"}"; do
    case "$step" in index_waited:*) index+=",$step" ;; esac
  done
  report 1 "索引驗證：$cbm_error"
}
index="$(IFS=,; printf '%s' "${cbm_steps[*]}")"

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

# The task's compose project (docs/WORKFLOW.md 本機檢查, #339): a docker compose run
# without -p uses task-<issue>, not the directory name. The prefix is POSIX shell syntax, so on
# Windows the terminal's shell is pinned to Git Bash (#339 review S3); Orca refuses the create
# on a host that cannot give it, and nothing is sent. macOS has no --shell: Orca refuses it
# there and spawns the login shell (zsh or bash), where the prefix is the same syntax.
shell_args=()
is_windows && shell_args=(--shell git-bash)
out="$(orca terminal create --worktree "id:$repo_id::$path" --title "#$issue $slug" ${shell_args[@]+"${shell_args[@]}"} \
  --command "COMPOSE_PROJECT_NAME=task-$issue CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 claude --model $model --effort $effort --settings '$settings'" --json)" \
  || report 1 "orca terminal create 失敗"
handle="$(printf '%s' "$out" | cj get result.terminal.handle)" || report 1 "orca terminal create 沒有回傳 handle"

# The flag is --timeout-ms: with a wrong flag wait returns ok:false at once and the text
# sent next is swallowed by Claude Code's start-up screen. Only satisfied:true sends.
out="$(orca terminal wait --terminal "$handle" --for tui-idle --timeout-ms "$wait_ms" --json)"
printf '%s' "$out" | cj satisfied || report 1 "terminal 未就緒（wait 沒有 satisfied:true），任務未送出"

# A menu on the screen (#835): tui-idle is satisfied while Claude Code's start-up trust
# menu is open, and its default "No, exit" takes the Enter that would send the line. The
# words that mark a trust or permission menu, all in this one list (screens seen in #835
# AC-1: "Adding a new directory … Is this a directory you created or one you trust? ❯ No,
# exit / Yes, add it / Enter to confirm · Esc to cancel", and "Do you want to proceed? …
# Esc to cancel · Tab to amend"). trust_marks name the trust menu, menu_marks any other.
trust_marks=("Adding a new directory" "Yes, add it" "one you trust" "Do you trust")
menu_marks=("Do you want to proceed?" "Enter to confirm" "Esc to cancel")
blocked() { # blocked WHAT CHOICE: exit 5, nothing sent
  report 5 "terminal $handle（標題「#$issue $slug」）$1，任務未送出、也沒送 Enter。請使用者到這個 terminal 自己選：$2。選完回到輸入框後，統籌照 docs/WORKFLOW.md 任務流程第 2 步手動送那一句；不要重跑 dispatch.sh（branch 已建）"
}
trust_choice="信任框（Adding a new directory）要讓 session 讀任務檔目錄就選「Yes, add it」（先按 ↓ 再 Enter；預設的「No, exit」會讓 claude 退出）"
menu_choice="照畫面的選項選（讀檔權限框「Do you want to proceed?」是 1 允許這一次、2 這個 session 都允許讀該目錄、3 不允許）"
# Only the rendered screen counts (#835 review 6934849677): Orca falls back to the
# accumulated output when it cannot render one (source "screen-unavailable"; an older
# host has no source), where a TUI's cursor-drawn spaces are gone and no mark matches;
# and a screen with no text on it shows nothing either. Rows the terminal wrapped
# (tailRows[i].wrapped: row i goes on row i-1) are joined back, then every run of
# blanks, line ends included, is one space, so a mark split over rows still matches.
out="$(orca terminal read --terminal "$handle" --screen --json)" \
  || report 1 "讀不到 terminal 畫面，無法確認沒有確認框，任務未送出"
screen="$(printf '%s' "$out" | "$python" -X utf8 -c '
import json, sys
t = (json.load(sys.stdin).get("result") or {}).get("terminal") or {}
tail, rows = t.get("tail"), t.get("tailRows") or []
if t.get("source") != "screen" or not isinstance(tail, list):
    sys.exit(3)
lines = []
for i, text in enumerate(str(x) for x in tail):
    row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
    if lines and row.get("wrapped") is True:
        prev = rows[i - 1] if isinstance(rows[i - 1], dict) else {}
        lines[-1] += " " * int(prev.get("trailingSpaces") or 0) + text
    else:
        lines.append(text)
text = " ".join(" ".join(lines).split())
if not text:
    sys.exit(4)
sys.stdout.write(text)
')" || report 1 "讀不到 terminal 畫面（不是算出來的畫面，或畫面上沒有字），無法確認沒有確認框，任務未送出"
for mark in "${trust_marks[@]}"; do
  case "$screen" in *"$mark"*) blocked "停在信任框（畫面有「$mark」）" "$trust_choice" ;; esac
done
for mark in "${menu_marks[@]}"; do
  case "$screen" in *"$mark"*) blocked "停在確認框（畫面有「$mark」）" "$menu_choice" ;; esac
done

out="$(orca terminal send --terminal "$handle" --text "$notice" --enter \
  --wait-submit "$submit_wait" --json)" || {
  # Orca refuses a text-plus-Enter prompt into a menu it sees (#720): nothing went in.
  [ "$(printf '%s' "$out" | cj get error.code 2>/dev/null)" = agent_prompt_blocked ] \
    && blocked "停在確認框（orca terminal send 回 agent_prompt_blocked）" "$menu_choice"
  sent=null; report 3 "orca terminal send 失敗，文字可能已送出：先 orca terminal read，不要重送"
}
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
exit 1 # not reached: report exits
}
