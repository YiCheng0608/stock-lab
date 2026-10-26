#!/usr/bin/env bash
# Clean up a merged task (Issue #282; docs/GITHUB_WORKFLOW.md 任務流程第 6 步). Checks first,
# deletes nothing unless every check passes:
#   - the task's PR is merged and CI on master is green for its merge commit (and the
#     newest master run is not red);
#   - the worktree on task/<issue>-* has no uncommitted changes and its branch is in
#     origin/master; this shell does not run inside it;
#   - every terminal of the worktree is idle (agents: tui-idle; shells: no output for
#     --idle-seconds), and none is the caller's own;
#   - no --extra-dir is protected (guard_dir in coordinator_lib.sh): the repo root and
#     every worktree `git worktree list` names (the task's own worktree goes through
#     `orca worktree rm`, never --extra-dir), anything inside a git repo or holding a
#     .git, $HOME and its parents, / and drive roots, any stock-lab-data directory and
#     what is under it, and $STOCK_DATA_DIR. Paths are compared as written and as
#     resolved; one whose resolved form differs (a junction or symlink on the way, an
#     8.3 short name) is refused outright. A failed orca, gh or git read refuses too.
# Deleting checks guard_dir again (remove_tree), so one broken check is not enough to
# delete a protected path.
# Then: close the terminals, `orca worktree rm --force`, `git worktree prune`, delete the
# local branch, delete each --extra-dir (junctions and symlinks unlinked first, never
# followed), set the board to 完成, and read back that all of it is gone.
#
# Usage: close_task.sh <issue> [--extra-dir <path>]... [options]
#   --slug S          the task is task/<issue>-S (needed when an issue has several)
#   --pr N            the task's PR; default: the merged PR whose head is the branch
#   --allow-pr-head-mismatch  accept a --pr whose head is another branch (a dry run)
#   --no-board        leave the board alone (a dry run on a throwaway branch)
#   --repo-id ID      Orca repo id; default: the repo whose remote is YiCheng0608/stock-lab
#   --idle-seconds N  a shell terminal is idle after N seconds without output, default 30
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
# Prints one JSON line. Exit 0 done; 1 a check failed (nothing deleted); 3 a step failed
# after deleting started (the JSON says which steps ran); 4 only the board update
# failed; 2/64 bad setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

issue="" slug="" pr="" repo_id="" idle_seconds=30 set_board=1 allow_head_mismatch=0
extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-board) set_board=0 ;;
    --allow-pr-head-mismatch) allow_head_mismatch=1 ;;
    --extra-dir | --slug | --pr | --repo-id | --idle-seconds | --python)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value" 64
      case "$1" in
        --extra-dir) extra+=("$2") ;;
        --slug) slug="$2" ;;
        --pr) pr="$2" ;;
        --repo-id) repo_id="$2" ;;
        --idle-seconds) idle_seconds="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      continue
      ;;
    -*) die "unknown argument: $1" 64 ;;
    *) [ -z "$issue" ] && issue="$1" || die "unexpected argument: $1" 64 ;;
  esac
  shift
done
case "$issue" in '' | *[!0-9]*) die "<issue> must be a number" 64 ;; esac
case "$pr$idle_seconds" in *[!0-9]*) die "--pr/--idle-seconds must be numbers" 64 ;; esac
case "$slug" in -* | *[!a-z0-9-]*) die "--slug uses a-z, 0-9 and '-' only" 64 ;; esac
prefix="task/$issue-"
find_python

wt_path="" wt_id="" branch="" merge_sha="" board="" steps=()

report() { # report EXIT [ERROR]
  local error=null done_steps="" s
  [ -n "${2:-}" ] && error="$(json_str "$2")"
  for s in "${steps[@]+"${steps[@]}"}"; do done_steps="$done_steps${done_steps:+,}$(json_str "$s")"; done
  printf '{"issue":%s,"pr":%s,"merge_commit":%s,"worktree":%s,"branch":%s,"steps":[%s],"board":%s,"error":%s}\n' \
    "$issue" "${pr:-null}" "$(json_str "$merge_sha")" "$(json_str "$wt_path")" "$(json_str "$branch")" \
    "$done_steps" "$(json_str "$board")" "$error"
  [ -n "${2:-}" ] && printf 'close_task.sh: %s\n' "$2" >&2
  exit "$1"
}
refuse() { report 1 "$1（未刪除任何東西）"; }

# unlink_one LINK: remove a junction or symlink itself, never what it points to; the
# JSON steps list each one. Git Bash's and GNU rm -rf do not follow them either (#282),
# but with the links gone first no change to the delete command can reach a target.
unlink_one() {
  if [ -d "$1" ] && is_windows; then
    MSYS2_ARG_CONV_EXCL='*' cmd /d /c rmdir "$(cygpath -w -- "$1")" >/dev/null 2>&1
  else
    rm -f -- "$1"
  fi
  [ ! -L "$1" ] && [ ! -e "$1" ] || return 1
  steps+=("unlinked:$1")
}

# remove_tree DIR [residual]: check DIR with guard_dir once more (a second line of
# defence: the checks above are not the only thing between rm and a protected path),
# unlink every junction/symlink inside (find does not follow them), confirm none is
# left, then delete; returns 0 only when DIR is gone.
remove_tree() {
  local link
  [ -z "$(guard_dir "$1" "${2:-}")" ] || return 2
  if [ -L "$1" ]; then
    unlink_one "$1"
    return
  fi
  while IFS= read -r -d '' link; do
    unlink_one "$link" || return 1
  done < <(find "$1" -type l -print0)
  [ -z "$(find "$1" -type l -print -quit)" ] || return 1
  rm -rf -- "$1"
  [ ! -e "$1" ] && [ ! -L "$1" ]
}

# --- checks: nothing is deleted before all of them pass ---------------------------
orca_repo_id
# A failed listing is not an empty one (#283 review M3).
listing="$(orca worktree list --repo "id:$repo_id" --json)"
printf '%s' "$listing" | cj ok || refuse "orca worktree list 失敗"
mapfile -t found < <(printf '%s' "$listing" | cj worktrees "$prefix$slug" \
  | awk -F '\t' -v want="$prefix$slug" -v exact="${slug:+1}" '!exact || $2 == want')
[ ${#found[@]} -le 1 ] || refuse "有多個 $prefix* worktree（用 --slug 指定）：${found[*]}"
if [ ${#found[@]} -eq 1 ]; then
  IFS=$'\t' read -r wt_path branch wt_id <<<"${found[0]}"
else
  if [ -n "$slug" ]; then
    git -C "$repo_root" show-ref --verify --quiet "refs/heads/$prefix$slug" && branch="$prefix$slug"
  else
    branch="$(git -C "$repo_root" for-each-ref --format='%(refname:short)' "refs/heads/$prefix*" | tr -d '\r')"
  fi
  case "$branch" in *$'\n'*) refuse "有多個 $prefix* branch（用 --slug 指定）" ;; esac
fi
[ -n "$branch" ] || [ -n "$pr" ] || refuse "找不到 $prefix$slug* 的 worktree 或 branch；用 --pr 指定 PR"

if [ -n "$pr" ]; then
  out="$(gh pr view "$pr" --repo "$GH_REPO" --json number,state,mergeCommit,headRefName)" || refuse "讀不到 PR #$pr"
  out="[$out]"
else
  out="$(gh pr list --repo "$GH_REPO" --head "$branch" --state merged --limit 1 --json number,state,mergeCommit,headRefName)" \
    || refuse "gh pr list 失敗"
fi
[ "$(printf '%s' "$out" | cj get 0.state)" = MERGED ] || refuse "PR 尚未合併（${branch:-#$pr}）"
pr="$(printf '%s' "$out" | cj get 0.number)"
merge_sha="$(printf '%s' "$out" | cj get 0.mergeCommit.oid)" || refuse "PR #$pr 沒有 merge commit"
head_ref="$(printf '%s' "$out" | cj get 0.headRefName)"
# The PR's head stands in for a branch not found locally only when it is this task's:
# another task's branch is never deleted here.
ours=0
if [ -n "$slug" ]; then
  [ "$head_ref" = "$prefix$slug" ] && ours=1
else
  case "$head_ref" in "$prefix"*) ours=1 ;; esac
fi
[ -n "$branch" ] || [ "$ours" = 0 ] || branch="$head_ref"
[ "$head_ref" = "$branch" ] || [ "$allow_head_mismatch" = 1 ] \
  || refuse "PR #$pr 的 head 是 $head_ref，不是 ${branch:-$prefix$slug*}（確定要借用這個 PR 才加 --allow-pr-head-mismatch）"

out="$(gh run list --repo "$GH_REPO" --branch master --event push --workflow CI --limit 20 \
  --json headSha,status,conclusion)" || refuse "gh run list 失敗"
read -r mine newest <<<"$(printf '%s' "$out" | cj ci-state "$merge_sha")"
[ "$mine" = success ] || refuse "master 上 merge commit ${merge_sha:0:9} 的 CI 是 $mine，不是 success"
[ "$newest" != failure ] || refuse "master 最新一次 CI 是 failure，先修 master"

git -C "$repo_root" fetch --quiet origin master || refuse "git fetch origin master 失敗"
if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
  git -C "$repo_root" merge-base --is-ancestor "refs/heads/$branch" origin/master \
    || refuse "本地 branch $branch 有不在 origin/master 的 commit"
fi

terminals=()
if [ -n "$wt_path" ]; then
  within "$PWD" "$wt_path" && refuse "目前目錄在要刪的 worktree 裡"
  within "$repo_root" "$wt_path" && refuse "這支腳本來自要刪的 worktree，請從 master checkout 執行"
  if [ -d "$wt_path" ]; then
    status="$(git -C "$wt_path" status --porcelain)" || refuse "讀不到 worktree 的 git status：$wt_path"
    [ -z "$(printf '%s' "$status" | tr -d '\r')" ] || refuse "worktree 有未 commit 的改動：$wt_path"
  fi
  listing="$(orca terminal list --json)"
  printf '%s' "$listing" | cj ok || refuse "orca terminal list 失敗"
  now_ms="$(($(date +%s) * 1000))"
  while read -r handle agent last; do
    [ -n "$handle" ] || continue
    [ "$handle" != "${ORCA_TERMINAL_HANDLE:-}" ] || refuse "worktree 的 terminal $handle 是本 session"
    if [ "$agent" != - ]; then
      orca terminal wait --terminal "$handle" --for tui-idle --timeout-ms 10000 --json | cj satisfied \
        || refuse "terminal $handle（$agent）不是閒置"
    elif [ $((now_ms - last)) -lt $((idle_seconds * 1000)) ]; then
      refuse "terminal $handle 在 $idle_seconds 秒內仍有輸出"
    fi
    terminals+=("$handle")
  done < <(printf '%s' "$listing" | cj terminals "$wt_path")
fi

extra_live=()
for dir in "${extra[@]+"${extra[@]}"}"; do
  reason="$(guard_dir "$dir")"
  [ -z "$reason" ] || refuse "--extra-dir $dir $reason"
  if [ -e "$dir" ] || [ -L "$dir" ]; then extra_live+=("$dir"); else steps+=("extra_absent:$dir"); fi
done

# --- delete ------------------------------------------------------------------------
for handle in "${terminals[@]+"${terminals[@]}"}"; do
  orca terminal close --terminal "$handle" --json | cj ok || report 3 "terminal close 失敗：$handle"
  steps+=("terminal_closed:$handle")
done
if [ -n "$wt_path" ]; then
  if orca worktree rm --worktree "${wt_id:-id:$repo_id::$wt_path}" --force --json | cj ok; then
    steps+=("worktree_removed")
  else
    steps+=("worktree_rm_failed")
  fi
  git -C "$repo_root" worktree prune || report 3 "git worktree prune 失敗"
  steps+=("worktree_pruned")
  if [ -e "$wt_path" ]; then
    git -C "$repo_root" worktree list --porcelain | tr -d '\r' | grep -qixF "worktree $wt_path" \
      && report 3 "worktree 仍登錄在 git：$wt_path"
    reason="$(guard_dir "$wt_path" residual)"
    [ -z "$reason" ] || report 3 "殘留目錄 $wt_path $reason，未刪"
    remove_tree "$wt_path" residual || report 3 "殘留目錄刪不掉：$wt_path"
    steps+=("worktree_dir_removed")
  fi
fi
if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
  git -C "$repo_root" branch -D "$branch" >/dev/null || report 3 "刪本地 branch 失敗：$branch"
  steps+=("branch_deleted")
fi
for dir in "${extra_live[@]+"${extra_live[@]}"}"; do
  remove_tree "$dir" || report 3 "刪不掉 --extra-dir $dir"
  steps+=("extra_removed:$dir")
done

# --- read back ---------------------------------------------------------------------
[ -z "$wt_path" ] || [ ! -e "$wt_path" ] || report 3 "讀回：worktree 目錄仍在 $wt_path"
! git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch" || report 3 "讀回：branch $branch 仍在"
for dir in "${extra_live[@]+"${extra_live[@]}"}"; do
  [ ! -e "$dir" ] && [ ! -L "$dir" ] || report 3 "讀回：$dir 仍在"
done

if [ "$set_board" = 1 ]; then
  board="$(board_set "$issue" 完成)" || { board=failed; report 4 "看板未設成完成，請手動設定"; }
else
  board=skipped
fi
report 0
