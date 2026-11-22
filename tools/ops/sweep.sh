#!/usr/bin/env bash
# Host sweep (Issue #941; docs/WORKFLOW.md 任務流程第 6 步, docs/RELEASE.md): what tasks,
# sessions and deploys leave on the development and production host and nothing else deletes.
# close_task.sh runs it after its cleanup (with --no-prune: it pruned already) and deploy.sh
# after a deploy that checks out; it can be run by hand too. Deletes only:
#   - $HOME/t<n> (the name exactly: t and digits) when Issue (or PR) n reads back closed, no
#     task/<n>-* worktree is left and no commitment not kept yet holds n (below); through guard_dir and remove_tree, as close_task.sh's
#     --extra-dir, so a directory holding a .git, the data directory or a link on the way is
#     refused;
#   - the Docker resources named t<n>/task-<n> (docker_cleanup in coordinator_lib.sh: stopped
#     containers, images as repository:tag, volumes, networks; none while one of them runs) for
#     the same n: Issue closed, no worktree, no commitment;
#   - Claude Code scratchpads, <claude root>/<project>/<session id> (claude_tmp_root: $TEMP/claude
#     on Windows, /private/tmp/claude-<uid> on macOS), when nothing in one changed for 7 days;
#     this session's own (CLAUDE_CODE_SESSION_ID) stays, and without that id none is deleted;
#   - $TEMP/trivy-* (docker scout's, Windows) when nothing in it changed for a day;
#   - dangling images and build cache (docker_prune: only with no container running but the
#     production project's and no Docker task in progress), unless --no-prune.
# Never touched: the volumes, images and containers of other names (stock-lab_stock-data,
# stock-lab-research, the release images: deploy.sh keeps the current and the previous one),
# the data directory, the release checkout, evidence/, open tasks. No `docker system prune`,
# `docker volume prune` or `git clean`. An Issue state or worktree list that cannot be read
# keeps everything it would decide; so does a worktree list that does not list this checkout
# (git answered nothing: PR #942 review).
# A 統籌承諾 (docs/COORDINATOR.md) not kept yet in <data>/logs/commitments.jsonl holds n when
# its Issue is n or its text or link names t<n> or task-<n> (PR #942 review: #776 kept the
# volume task-776_research for #790). A data directory without logs/, or a commitments file
# that cannot be read or has a line that cannot be read, keeps every task's things; logs/
# without the file is no commitment. Run from the release checkout it refuses (it sees no
# task worktree there), as deploy.sh does.
#
# Usage: sweep.sh [--no-prune] [--python EXE]
# Prints one JSON line, {"steps": [...], "error": null}: every outcome is a step. Exit 0 also
# when a step failed; 2/64 bad setup (error set) or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

# The long-lived integration branches (docker_task_issues): the one list is close_task.sh's.
integration_branches=()
line="$(grep -m 1 '^integration_branches=(' "$script_dir/close_task.sh" 2>/dev/null)" || line=""
[[ "$line" =~ ^integration_branches=\(([A-Za-z0-9._/\ -]*)\)$ ]] \
  && read -r -a integration_branches <<<"${BASH_REMATCH[1]}"

prune=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-prune) prune=0 ;;
    --python)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value" 64
      python="$2"
      shift
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
  shift
done
find_python

if within "$script_dir" "${STOCK_RELEASE_DIR:-$HOME/stock-lab-release}"; then
  printf '{"steps":[],"error":%s}\n' "$(json_str "這支腳本在發佈 checkout 裡；請從另一個 checkout（master 管理 checkout）執行")"
  exit 2
fi

scratch_days=7 trivy_days=1
steps=()

report() {
  local done_steps="" s
  for s in "${steps[@]+"${steps[@]}"}"; do done_steps="$done_steps${done_steps:+,}$(json_str "$s")"; done
  printf '{"steps":[%s],"error":null}\n' "$done_steps"
  exit 0
}

# recent PATH MINUTES: something in PATH (itself included; links not followed) changed within
# MINUTES, or PATH cannot be read: either way it stays.
recent() {
  local out
  out="$(find "$1" -mmin "-$2" -print -quit 2>/dev/null)" || return 0
  [ -n "$out" ]
}

# --- the tasks: closed Issue and no worktree -------------------------------------------
# wt_tasks: the n of every task/<n>-* worktree, space-separated.
wt_tasks=""
wt_ok=0
# listed PATH: PATH is this checkout (both ways, as written and as resolved).
listed() {
  local a b
  a="$(native "$1")" && b="$(native "$repo_root")" || return 1
  [ "$(cj within "$a" "$b" 2>/dev/null)" = yes ] && [ "$(cj within "$b" "$a" 2>/dev/null)" = yes ]
}
if out="$(git -C "$repo_root" worktree list --porcelain)"; then
  # git lists every worktree, this checkout among them; a list without it was not read.
  while IFS= read -r l; do
    case "$l" in "worktree "*) listed "${l#worktree }" && { wt_ok=1; break; } ;; esac
  done < <(printf '%s\n' "$out" | tr -d '\r')
  wt_tasks=" $(printf '%s\n' "$out" | tr -d '\r' | sed -n 's|^branch refs/heads/task/\([0-9][0-9]*\)-.*|\1|p' | tr '\n' ' ')"
fi
[ "$wt_ok" = 1 ] || steps+=("sweep_skipped:worktrees_unreadable")

# held: the n held by a commitment not kept yet (space-separated, spaces around); read the
# way patrol.sh lists them (commitments.py read and state).
held=" " held_ok=0
logs="$data_dir/logs"
if [ -d "$logs" ] && logs_native="$(native "$logs")" \
  && out="$("$python" -X utf8 -c '
import os, re, sys
sys.path.insert(0, sys.argv[1])
import commitments as c
path = os.path.join(sys.argv[2], c.FILE)
if os.path.exists(path) and not os.access(path, os.R_OK):
    sys.exit(3)
try:
    records, bad = c.read(sys.argv[2])
except OSError:
    sys.exit(3)
if bad:
    sys.exit(3)
added, kept = c.state(records)
name = re.compile(r"(?<![A-Za-z0-9])(?:t|task-)0*([0-9]+)(?![0-9])")
held = set()
for cid, adds in added.items():
    if cid in kept:
        continue
    for r in adds:
        if type(r.get("issue")) is int:
            held.add(r["issue"])
        for text in (r.get("text"), r.get("url")):
            if isinstance(text, str):
                held.update(int(n) for n in name.findall(text))
print(" ".join(str(n) for n in sorted(held)))
' "$(native "$script_dir")" "$logs_native")"; then
  held=" $(printf '%s' "$out" | tr -d '\r') " held_ok=1
else
  steps+=("sweep_skipped:commitments_unreadable")
fi
declare -A issue_state=()
# task_done N: Issue (or PR) N reads back closed, no task/N-* worktree is left and no
# commitment holds N; else sets why to the reason it stays (worktrees_unreadable, worktree,
# commitments_unreadable, commitment, open, issue_unreadable). Not run in $(…): the states
# read are kept for the next call.
why=""
task_done() {
  local n="$1" state
  why=""
  [ "$wt_ok" = 1 ] || { why=worktrees_unreadable; return 1; }
  [[ "$wt_tasks" == *" $n "* ]] && { why=worktree; return 1; }
  [ "$held_ok" = 1 ] || { why=commitments_unreadable; return 1; }
  [[ "$held" == *" $n "* ]] && { why=commitment; return 1; }
  if [ -z "${issue_state[$n]+x}" ]; then
    # The issues endpoint answers for a PR number as well.
    state="$(gh api "repos/$GH_REPO/issues/$n" 2>/dev/null | cj get state 2>/dev/null)" || state=""
    issue_state[$n]="$(printf '%s' "$state" | tr -d '\r')"
  fi
  case "${issue_state[$n]}" in
    closed) return 0 ;;
    open) why=open ;;
    *) why=issue_unreadable ;;
  esac
  return 1
}

shopt -s nullglob
for dir in "$HOME"/t*; do
  name="${dir##*/}"
  [[ "$name" =~ ^t([0-9]+)$ ]] || continue
  [ -d "$dir" ] || [ -L "$dir" ] || continue
  if ! task_done "${BASH_REMATCH[1]}"; then
    steps+=("sweep_kept:dir:$dir:$why")
    continue
  fi
  reason="$(guard_dir "$dir")"
  if [ -n "$reason" ]; then
    steps+=("sweep_skipped:dir:$dir:$reason")
  elif remove_tree "$dir"; then
    steps+=("sweep_removed:dir:$dir")
  else
    steps+=("sweep_skipped:dir:$dir:delete_failed")
  fi
done
shopt -u nullglob

listing=""
if ! listing="$(docker_listing)"; then
  steps+=("docker_skipped:$listing")
  listing=""
  docker_ok=0
else
  docker_ok=1
  # The n of every resource named t<n>/task-<n> (an image by its repository or its tag).
  mapfile -t numbers < <(printf '%s\n' "$listing" | awk -F '\t' '
    { n = split($1 == "image" ? $2 "\t" $3 : $2, names, "\t")
      for (i = 1; i <= n; i++)
        if (match(names[i], /^(t|task-)[0-9]+([-_.]|$)/)) {
          s = substr(names[i], 1, RLENGTH); gsub(/[^0-9]/, "", s); print s + 0 } }' | sort -un)
  for n in "${numbers[@]+"${numbers[@]}"}"; do
    if task_done "$n"; then
      docker_cleanup "$n" none
    else
      steps+=("sweep_kept:docker:$n:$why")
    fi
  done
fi

# --- Claude Code scratchpads untouched for scratch_days ---------------------------------
if ! [[ "${CLAUDE_CODE_SESSION_ID:-}" =~ $uuid_re ]]; then
  steps+=("scratchpad_skipped:no_own_session_id")
elif ! claude_tmp_root; then
  steps+=("scratchpad_skipped:no_temp")
else
  kept=0
  shopt -s nullglob
  for dir in "$claude_root"/*/*; do
    [[ "${dir##*/}" =~ $uuid_re ]] || continue
    [ -d "$dir" ] || [ -L "$dir" ] || continue
    if [ "${dir##*/}" != "$CLAUDE_CODE_SESSION_ID" ] && recent "$dir" $((scratch_days * 1440)); then
      kept=$((kept + 1))
      continue
    fi
    scratch_remove "$dir"
  done
  shopt -u nullglob
  steps+=("scratchpad_recent:$kept")
fi

# --- docker scout's trivy-* in Temp (Windows), untouched for trivy_days -----------------
if [ -z "${TEMP:-}" ]; then
  steps+=("trivy_skipped:no_temp")
elif ! temp="$(native "$TEMP")"; then
  steps+=("trivy_skipped:no_temp")
else
  shopt -s nullglob
  for x in "${temp%/}"/trivy-*; do
    recent "$x" $((trivy_days * 1440)) && { steps+=("trivy_recent:$x"); continue; }
    reason="$(guard_dir "$x")"
    if [ -n "$reason" ]; then
      steps+=("trivy_skipped:$x:$reason")
    elif remove_tree "$x"; then
      steps+=("trivy_removed:$x")
    else
      steps+=("trivy_skipped:$x:delete_failed")
    fi
  done
  shopt -u nullglob
fi

# --- dangling images and build cache ----------------------------------------------------
if [ "$prune" = 0 ]; then
  steps+=("docker_prune_skipped:not_requested")
elif [ "$wt_ok" = 0 ]; then
  # docker_prune reads the worktrees again; a list without this checkout reads as no task.
  steps+=("docker_prune_skipped:worktrees_unreadable")
elif [ "$docker_ok" = 1 ]; then
  # Listed again: the deletes above changed what runs and what is named.
  if listing="$(docker_listing)"; then
    docker_prune "$listing" ""
  else
    steps+=("docker_prune_skipped:$listing")
  fi
fi
report
