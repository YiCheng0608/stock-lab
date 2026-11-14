# Shared by dispatch.sh, close_task.sh, patrol.sh (Issue #282) and deploy.sh (#314); sourced, not run.
# Callers set script_dir before sourcing. orca, gh and git are looked up on PATH so the
# tests can put recording fakes in front of them (backend/tests/test_coordinator_scripts.py).
export LANG=C.UTF-8 LC_ALL=C.UTF-8
# Git Bash turns /c/... arguments of native programs (python.exe, orca.exe) into C:/...; a
# shell that exported MSYS_NO_PATHCONV=1 for `docker -v` (WORKFLOW.md 本機檢查)
# turns that off, and python then reads /c/Users as C:\c\Users: patrol.sh misread the
# heartbeat and no wake listener started (#338). No script here passes docker a path
# (deploy.sh sets it on each docker call). Whoever sources this lib into their own shell
# must put MSYS_NO_PATHCONV=1 back on each later `docker -v` themselves.
unset MSYS_NO_PATHCONV

GH_REPO='YiCheng0608/stock-lab'
ORCA_REPO_KEY='github.com/YiCheng0608/stock-lab'
repo_root="$(cd "$script_dir/../.." && pwd)"
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}"
python="${STOCK_PYTHON:-}"

die() {
  printf '%s: %s\n' "$(basename "$0")" "$1" >&2
  exit "${2:-1}"
}

# find_python: an explicit --python/STOCK_PYTHON must work; otherwise the first that does.
find_python() {
  local c
  if [ -n "$python" ]; then
    "$python" -c 'import sys' >/dev/null 2>&1 || die "Python 無法執行：$python" 2
    return 0
  fi
  for c in "$repo_root/.venv/Scripts/python.exe" "$repo_root/.venv/bin/python" python3 python \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"; do
    if "$c" -c 'import sys' >/dev/null 2>&1; then
      python="$c"
      return 0
    fi
  done
  die "找不到可用的 Python（用 --python 或 STOCK_PYTHON 指定）" 2
}

cj() { "$python" -X utf8 "$script_dir/coordinator_json.py" "$@"; }

# json_str VALUE: VALUE as a JSON string literal.
json_str() { printf '%s' "$1" | "$python" -X utf8 -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read(), ensure_ascii=False))'; }

# listener_post PATH: POST to the host's wake listener (wake_listener.py, #338) with the
# token STOCK_WAKE_TOKEN; prints the answer. Returns 1 without a token, when the listener
# cannot be reached, or when it answers other than 200. STOCK_WAKE_URL is its /wake URL.
listener_post() {
  local base="${STOCK_WAKE_URL:-http://host.docker.internal:47338/wake}" out
  [ -n "${STOCK_WAKE_TOKEN:-}" ] || { echo "STOCK_WAKE_TOKEN is empty" >&2; return 1; }
  # The header on stdin, so the token is in no command line.
  out="$(printf 'Authorization: Bearer %s\n' "$STOCK_WAKE_TOKEN" \
    | curl -sS -m 60 -X POST -H @- --data '' -w '\n%{http_code}' "${base%/wake}$1")" || return 1
  printf '%s\n' "${out%$'\n'*}"
  [ "${out##*$'\n'}" = 200 ]
}

orca_repo_id() {
  [ -n "${repo_id:-}" ] && return 0
  repo_id="$(orca repo list --json 2>/dev/null | cj repo-id "$ORCA_REPO_KEY")" \
    || die "orca repo list 找不到 $ORCA_REPO_KEY（用 --repo-id 指定）" 2
}

# board_set ISSUE STATUS: set the issue's Status on project 1, adding the issue first when
# it is not on the board. The item id comes from the issue's own projectItems, never
# from a board listing. Prints the status that was set; returns 1 on failure.
board_set() {
  local issue="$1" status="$2" out item project field options node option entry entries
  out="$(gh api graphql -F n="$issue" -f query='query($n:Int!){
    repository(owner:"YiCheng0608",name:"stock-lab"){issue(number:$n){id
      projectItems(first:10){nodes{id project{id number
        field(name:"Status"){... on ProjectV2SingleSelectField{id options{id name}}}}}}}}
    user(login:"YiCheng0608"){projectV2(number:1){id
      field(name:"Status"){... on ProjectV2SingleSelectField{id options{id name}}}}}}')" || return 1
  read -r item project field options node <<<"$(printf '%s' "$out" | cj board)"
  [ -n "$project" ] && [ -n "$field" ] || return 1
  option=""
  IFS=, read -r -a entries <<<"$options"
  for entry in "${entries[@]}"; do
    [ "${entry#*=}" = "$status" ] && option="${entry%%=*}"
  done
  [ -n "$option" ] || return 1
  if [ "$item" = - ]; then
    [ -n "$node" ] || return 1
    item="$(gh api graphql -f p="$project" -f c="$node" --jq .data.addProjectV2ItemById.item.id \
      -f query='mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}')" \
      || return 1
    item="$(printf '%s' "$item" | tr -d '\r')"
  fi
  out="$(gh api graphql -f p="$project" -f i="$item" -f f="$field" -f o="$option" \
    --jq .data.updateProjectV2ItemFieldValue.projectV2Item.id \
    -f query='mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(
      input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}')" \
    || return 1
  [ "$(printf '%s' "$out" | tr -d '\r')" = "$item" ] || return 1
  printf '%s\n' "$status"
}

# --- paths close_task.sh must never delete (tested on their own: guard_dir deletes nothing)
is_windows() { case "$(uname -s)" in MINGW* | MSYS* | CYGWIN*) return 0 ;; esac; return 1; }

# native PATH: the one spelling Python compares on Windows, C:/…, for C:\…, /c/… and
# mounts such as /tmp/… alike (cygpath -u turned C:/…/AppData/Local/Temp into /tmp but
# left /c/… as it was: #283 review M4). Only the spelling changes: cygpath resolves
# junctions, so it is used for nothing but a mount's own top directory, and a link in
# the path stays visible to `guard` in coordinator_json.py.
# Prints nothing and fails for a path that is not local and absolute: UNC and device
# paths (\\server\share, //server/share, \\?\…, \\.\…), drive-relative ones (C:x, \x)
# and relative ones (#283 review M1). Callers treat that as protected.
native() {
  local p="$1" top
  case "$p" in '\'* | //*) return 1 ;; esac
  if ! is_windows; then
    case "$p" in /*) printf '%s' "$p"; return 0 ;; *) return 1 ;; esac
  fi
  case "$p" in
    [A-Za-z]:[\\/]*) printf '%s' "${p//\\//}"; return 0 ;;
    /*) ;;
    *) return 1 ;;
  esac
  if [[ "$p" =~ ^/([A-Za-z])(/.*)?$ ]]; then
    printf '%s:%s' "${BASH_REMATCH[1]^^}" "${BASH_REMATCH[2]:-/}"
    return
  fi
  top="/${p#/}"
  top="/$(printf '%s' "${top#/}" | cut -d/ -f1)"
  printf '%s%s' "$(cygpath -m -- "$top")" "${p#"$top"}"
}

# within A B: A is B or under B, as written and as resolved. Anything but a clear "no"
# (Python failed) counts as inside, so a check built on it refuses.
within() {
  local a b
  a="$(native "$1")" && b="$(native "$2")" || return 0
  [ "$(cj within "$a" "$b" 2>/dev/null)" != no ]
}

# guard_dir PATH [residual]: why PATH must not be deleted, or nothing; the comparison is
# `guard` in coordinator_json.py. "residual" is a worktree directory git no longer lists:
# its own .git file does not count. Fails closed: an error is a reason.
guard_dir() {
  local p roots root x out args=()
  p="$(native "$1")" || { echo "不是本機的絕對路徑（UNC、裝置路徑或相對路徑），請改用 C:/… 或 /… 的實際路徑"; return 0; }
  roots="$(git -C "$repo_root" worktree list --porcelain)" || { echo "讀不到 git worktree list"; return 0; }
  for x in "$HOME" "$data_dir" ${STOCK_DATA_DIR:+"$STOCK_DATA_DIR"}; do
    native "$x" >/dev/null || { echo "\$HOME 或資料目錄不是本機的絕對路徑：$x"; return 0; }
  done
  args+=(--home "$(native "$HOME")" --data "$(native "$data_dir")")
  [ -n "${STOCK_DATA_DIR:-}" ] && args+=(--data "$(native "$STOCK_DATA_DIR")")
  # On Windows "/" is the Git for Windows directory (cygpath -m / → C:/Program Files/Git).
  is_windows && args+=(--root "$(cygpath -m /)")
  while IFS= read -r root; do
    [ -n "$root" ] || continue
    x="$(native "$root")" || { echo "git checkout 的路徑不是本機的絕對路徑：$root"; return 0; }
    args+=(--root "$x")
  done < <(printf '%s\n' "$roots" | tr -d '\r' | sed -n 's/^worktree //p'; printf '%s\n' "$repo_root")
  [ "${2:-}" = residual ] && args+=(--residual)
  out="$(cj guard "$p" "${args[@]}")" || out="路徑檢查失敗"
  printf '%s' "$out"
}

# --- Docker resources of a closed task (#360; close_task.sh, docs/WORKFLOW.md 任務流程第 6 步)
# Every docker call has a time limit; timeout answers 124 (137 after -k) when it ran out and
# 127 when there is no docker command.
docker_timeout="${CLOSE_TASK_DOCKER_TIMEOUT:-30}"
docker_call() { timeout -k 5 "$docker_timeout" docker "$@"; }

# owned_name ISSUE NAME: NAME is t<issue> or task-<issue>, alone or followed by - _ or . (so
# t36 never takes t360's resources).
owned_name() { [[ "$2" =~ ^(t|task-)$1([-_.]|$) ]]; }

# docker_listing: the containers, images, volumes and networks, one tab-separated line each
# ("container NAME STATE IMAGE MOUNTS NETWORKS", "image REPO TAG", "volume NAME", "network
# NAME"); prints the reason (no_docker, timeout, daemon_unreachable) and fails when one
# listing does not answer.
docker_listing() {
  local rc=0 out tab=$'\t'
  out="$(docker_call ps -a --no-trunc --format "container$tab{{.Names}}$tab{{.State}}$tab{{.Image}}$tab{{.Mounts}}$tab{{.Networks}}" \
    && docker_call images --format "image$tab{{.Repository}}$tab{{.Tag}}" \
    && docker_call volume ls --format "volume$tab{{.Name}}" \
    && docker_call network ls --format "network$tab{{.Name}}")" || rc=$?
  case "$rc" in
    0) printf '%s\n' "$out" | tr -d '\r' ;;
    127) echo no_docker; return 1 ;;
    124 | 137) echo timeout; return 1 ;;
    *) echo daemon_unreachable; return 1 ;;
  esac
}

# docker_task_issues LISTING ISSUE: the Issues other than ISSUE with Docker work in progress,
# comma-separated: a task/<n>-* worktree whose resources (named t<n>/task-<n>) are in LISTING,
# or whose HEAD holds a commit of a long-lived integration branch (integration_branches in
# close_task.sh) that is not in origin/master: a Docker subtask (#331). Prints "?" when git
# cannot answer.
docker_task_issues() {
  local listing="$1" issue="$2" wt_list line head="" n b first rc kind name tag
  local firsts=() out=()
  wt_list="$(git -C "$repo_root" worktree list --porcelain)" || { echo "?"; return; }
  for b in "${integration_branches[@]+"${integration_branches[@]}"}"; do
    git -C "$repo_root" rev-parse --verify --quiet "refs/remotes/origin/$b" >/dev/null || continue
    # The first commit of the branch's own line: every branch cut from it since holds it.
    first="$(git -C "$repo_root" rev-list --first-parent --reverse "origin/master..origin/$b")" || { echo "?"; return; }
    first="$(printf '%s\n' "$first" | tr -d '\r' | head -n 1)"
    [ -z "$first" ] || firsts+=("$first")
  done
  while IFS= read -r line; do
    case "$line" in
      "HEAD "*) head="${line#HEAD }" ;;
      "branch refs/heads/task/"*)
        n="${line#branch refs/heads/task/}"
        n="${n%%-*}"
        case "$n" in '' | *[!0-9]* | "$issue") continue ;; esac
        # An image line is "image REPO TAG": its name is the repository, the tag comes next.
        while IFS=$'\t' read -r kind name tag _; do
          if owned_name "$n" "$name" || { [ "$kind" = image ] && owned_name "$n" "$tag"; }; then
            out+=("$n")
            continue 2
          fi
        done <<<"$listing"
        for first in "${firsts[@]+"${firsts[@]}"}"; do
          rc=0
          git -C "$repo_root" merge-base --is-ancestor "$first" "$head" || rc=$?
          [ "$rc" = 1 ] && continue
          # 0: a Docker subtask; anything else: git could not tell, so it counts as one.
          out+=("$n")
          continue 2
        done
        ;;
    esac
  done < <(printf '%s\n' "$wt_list" | tr -d '\r')
  [ ${#out[@]} -eq 0 ] || printf '%s\n' "${out[@]}" | sort -un | paste -sd, -
}

# docker_cleanup ISSUE PRUNE: delete the Docker resources named for ISSUE, adding a step for
# each one to the caller's `steps`. Never fails: without docker, or with a daemon that does not
# answer in time, it adds docker_skipped:<reason> and deletes nothing.
#   - images tagged t<issue>/t<issue>-* or whose repository is t<issue>-*/task-<issue>-*
#     (compose's <project>-<service>), removed as repository:tag, never by id and never with
#     -f, so an image that carries another tag as well keeps it;
#   - stopped containers named t<issue>/task-<issue>, or made from one of those images; volumes
#     and networks named t<issue>/task-<issue>;
#   - a container that runs (or is paused, restarting) and is named so or uses one of them:
#     nothing of ISSUE is deleted; docker_running:<container> and docker_kept:<kind>:<name>.
# Other images (base images such as python, node, nginx and alpine, other projects') are left
# alone, and so are dangling ones: those go with `docker image prune -f` and
# `docker builder prune -f` (build cache), which run only when PRUNE allows it (never; if-found:
# ISSUE had resources; docker-task: ISSUE is a Docker subtask), no container runs and no other
# Docker task is in progress (docker_task_issues); else docker_prune_skipped:<reason>.
docker_cleanup() {
  local issue="$1" prune="$2" listing kind name state image mounts networks ref x mine found others
  local running=0 busy=() containers=() images=() volumes=() nets=() owned_images=" " used=()
  if ! listing="$(docker_listing)"; then
    steps+=("docker_skipped:$listing")
    return 0
  fi
  while IFS=$'\t' read -r kind name state image mounts networks; do
    case "$kind" in
      image)
        # name and state are the repository and the tag here.
        [ "$name" != '<none>' ] && [ "$state" != '<none>' ] || continue
        if owned_name "$issue" "$state" || owned_name "$issue" "$name"; then
          images+=("$name:$state")
          owned_images+="$name:$state "
        fi
        ;;
      volume) owned_name "$issue" "$name" && volumes+=("$name") ;;
      network) owned_name "$issue" "$name" && nets+=("$name") ;;
    esac
  done <<<"$listing"
  while IFS=$'\t' read -r kind name state image mounts networks; do
    [ "$kind" = container ] || continue
    ref="$image"
    case "${ref##*/}" in *:*) ;; *) ref="$ref:latest" ;; esac
    mine=0
    if owned_name "$issue" "$name" || [[ "$owned_images" == *" $ref "* ]]; then mine=1; fi
    case "$state" in
      exited | created | dead) [ "$mine" = 0 ] || containers+=("$name") ;;
      *)
        running=$((running + 1))
        IFS=, read -r -a used <<<"$mounts,$networks"
        for x in "${used[@]+"${used[@]}"}"; do owned_name "$issue" "$x" && mine=1; done
        [ "$mine" = 0 ] || busy+=("$name")
        ;;
    esac
  done <<<"$listing"
  if [ ${#busy[@]} -gt 0 ]; then
    for x in "${busy[@]}"; do steps+=("docker_running:$x"); done
    for x in "${containers[@]+"${containers[@]}"}"; do steps+=("docker_kept:container:$x"); done
    for x in "${images[@]+"${images[@]}"}"; do steps+=("docker_kept:image:$x"); done
    for x in "${volumes[@]+"${volumes[@]}"}"; do steps+=("docker_kept:volume:$x"); done
    for x in "${nets[@]+"${nets[@]}"}"; do steps+=("docker_kept:network:$x"); done
    steps+=("docker_prune_skipped:running_containers")
    return 0
  fi
  found=$((${#containers[@]} + ${#images[@]} + ${#volumes[@]} + ${#nets[@]}))
  [ "$found" -gt 0 ] || steps+=("docker_none")
  # Containers first: an image, volume or network still used by one cannot go.
  for x in "${containers[@]+"${containers[@]}"}"; do
    if docker_call rm "$x" >/dev/null; then steps+=("docker_removed:container:$x"); else steps+=("docker_failed:container:$x"); fi
  done
  for x in "${images[@]+"${images[@]}"}"; do
    if docker_call rmi "$x" >/dev/null; then steps+=("docker_removed:image:$x"); else steps+=("docker_failed:image:$x"); fi
  done
  for x in "${volumes[@]+"${volumes[@]}"}"; do
    if docker_call volume rm "$x" >/dev/null; then steps+=("docker_removed:volume:$x"); else steps+=("docker_failed:volume:$x"); fi
  done
  for x in "${nets[@]+"${nets[@]}"}"; do
    if docker_call network rm "$x" >/dev/null; then steps+=("docker_removed:network:$x"); else steps+=("docker_failed:network:$x"); fi
  done
  case "$prune" in
    docker-task) ;;
    if-found) [ "$found" -gt 0 ] || { steps+=("docker_prune_skipped:no_task_resources"); return 0; } ;;
    *) steps+=("docker_prune_skipped:not_requested"); return 0 ;;
  esac
  [ "$running" = 0 ] || { steps+=("docker_prune_skipped:running_containers"); return 0; }
  others="$(docker_task_issues "$listing" "$issue")"
  [ "$others" != "?" ] || { steps+=("docker_prune_skipped:worktrees_unreadable"); return 0; }
  # Left to the last Docker task to close.
  [ -z "$others" ] || { steps+=("docker_prune_skipped:other_docker_tasks:$others"); return 0; }
  if docker_call image prune -f >/dev/null; then steps+=("docker_pruned:images"); else steps+=("docker_prune_failed:images"); fi
  if docker_call builder prune -f >/dev/null; then steps+=("docker_pruned:build_cache"); else steps+=("docker_prune_failed:build_cache"); fi
}

# --- the codebase-memory master index (#704; docs/WORKFLOW.md 程式索引) ---------------
# One index, of the master management checkout (this repo_root), kept by close_task.sh
# (rebuilt and verified after each merge) and checked by dispatch.sh before a dispatch.
# Only the same-engine CLI is used: a script may run in a shell with no MCP connection.
# STOCK_CBM_* override the defaults (the tests point STOCK_CBM_CLI at a fake).
cbm_cli="${STOCK_CBM_CLI:-C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd}"
cbm_project="${STOCK_CBM_PROJECT:-C-Users-YiCheng-Desktop-taiwan-stock-research}"
# Seconds per CLI call; a full build of the repo takes about 11.
cbm_timeout="${STOCK_CBM_TIMEOUT:-300}"
# dispatch.sh checks the files the newest N merges of the checkout's HEAD changed.
cbm_recent_merges="${STOCK_CBM_RECENT_MERGES:-5}"
cbm_out="" cbm_error="" cbm_report="" cbm_steps=()

# cbm_call TOOL ARGS_JSON: run `<cli> cli --json TOOL` with ARGS_JSON on stdin; cbm_out is the
# structured result (cj cbm-result: the daemon's level=/hint: lines dropped). Fails with the
# reason in cbm_error: no CLI, a time-out, an exit code other than 0, output with no JSON, or
# an answer with isError. Nothing is ever taken as "not stale".
cbm_call() {
  local tool="$1" raw rc=0
  cbm_out="" cbm_error=""
  if [ ! -f "$cbm_cli" ] && ! command -v -- "$cbm_cli" >/dev/null 2>&1; then
    cbm_error="找不到 codebase-memory CLI：$cbm_cli（STOCK_CBM_CLI）"
    return 1
  fi
  raw="$(printf '%s' "$2" | timeout -k 5 "$cbm_timeout" "$cbm_cli" cli --json "$tool" 2>&1)" || rc=$?
  case "$rc" in
    0) ;;
    124 | 137) cbm_error="codebase-memory CLI $tool 逾時（${cbm_timeout} 秒，STOCK_CBM_TIMEOUT）"; return 1 ;;
    126 | 127) cbm_error="codebase-memory CLI 無法執行（結束碼 $rc）：$cbm_cli"; return 1 ;;
    *) cbm_error="codebase-memory CLI $tool 結束碼 $rc：$(printf '%s\n' "$raw" | grep -v '^level=' | tail -n 2 | tr '\r\n' '  ')"; return 1 ;;
  esac
  cbm_out="$(printf '%s' "$raw" | cj cbm-result 2>&1)" || {
    cbm_error="codebase-memory CLI $tool 的輸出不能用：$cbm_out"
    cbm_out=""
    return 1
  }
}

# cbm_root_check: the project, when the engine has it, is this checkout; so a run from
# another checkout never rebuilds the master project from its files. A project the engine
# does not have passes (the first build creates it).
cbm_root_check() {
  local want root
  want="$(native "$repo_root")" || { cbm_error="repo_root 不是本機的絕對路徑：$repo_root"; return 1; }
  if ! cbm_call index_status "{\"project\":$(json_str "$cbm_project")}"; then
    case "$cbm_error" in *"project not found"*) cbm_error=""; return 0 ;; esac
    return 1
  fi
  root="$(printf '%s' "$cbm_out" | cj get root_path)" || { cbm_error="index_status 沒有 root_path"; return 1; }
  [ "$(cj within "$root" "$want")" = yes ] && [ "$(cj within "$want" "$root")" = yes ] \
    || { cbm_error="project $cbm_project 的 root 是 $root，不是這個 checkout（$want）；請從 master 管理 checkout 執行"; return 1; }
}

# cbm_rebuild [force]: index_repository of this checkout under the project's name; force
# deletes the project first (delete_project), the one way to make the engine record a file
# whose mtime alone changed (engine 0.10.8 keeps the old mtime and indexed_at otherwise).
cbm_rebuild() {
  local status project
  cbm_root_check || return 1
  if [ "${1:-}" = force ]; then
    cbm_call delete_project "{\"project\":$(json_str "$cbm_project")}" || return 1
  fi
  cbm_call index_repository "{\"repo_path\":$(json_str "$(native "$repo_root")"),\"name\":$(json_str "$cbm_project")}" \
    || return 1
  status="$(printf '%s' "$cbm_out" | cj get status)"
  project="$(printf '%s' "$cbm_out" | cj get project)"
  [ "$status" = indexed ] && [ "$project" = "$cbm_project" ] \
    || { cbm_error="index_repository 回 status=${status:-無}、project=${project:-無}，不是 indexed／$cbm_project"; return 1; }
}

# checkout_fast_forward: bring this checkout (repo_root, the management checkout) to
# origin/master, already fetched, by fast-forward only: it must be on master with no
# uncommitted change to a tracked file. Fails with the reason in cbm_error, nothing changed.
# The caller's own script file may be rewritten by it: close_task.sh and dispatch.sh are one
# brace group each, read whole before they run (#704 review).
checkout_fast_forward() {
  local cur dirty
  cur="$(git -C "$repo_root" symbolic-ref --quiet --short HEAD | tr -d '\r')"
  [ "$cur" = master ] || { cbm_error="$repo_root 不在 master（${cur:-detached}），未更新、未動索引"; return 1; }
  dirty="$(git -C "$repo_root" status --porcelain --untracked-files=no)" \
    || { cbm_error="讀不到 $repo_root 的 git status"; return 1; }
  [ -z "$(printf '%s' "$dirty" | tr -d '\r')" ] \
    || { cbm_error="$repo_root 有未 commit 的改動，未更新、未動索引"; return 1; }
  git -C "$repo_root" merge --ff-only --quiet origin/master \
    || { cbm_error="$repo_root 無法快轉到 origin/master"; return 1; }
}

# cbm_merge_paths SHA...: the files each merge commit changed against its first parent,
# deleted ones left out, once each.
cbm_merge_paths() {
  local sha
  for sha in "$@"; do
    git -C "$repo_root" -c core.quotepath=false diff --name-only --diff-filter=d "$sha^1" "$sha" || return 1
  done | tr -d '\r' | sort -u
}

# cbm_recent_paths: the files the newest cbm_recent_merges merges of HEAD changed.
cbm_recent_paths() {
  local shas
  shas="$(git -C "$repo_root" rev-list --first-parent --merges -n "$cbm_recent_merges" HEAD)" || return 1
  mapfile -t shas < <(printf '%s\n' "$shas" | tr -d '\r' | grep -E '^[0-9a-f]{7,64}$')
  [ ${#shas[@]} -gt 0 ] || return 1
  cbm_merge_paths "${shas[@]}"
}

# cbm_verify PATHS: ask the engine about PATHS (newline-separated, relative to repo_root):
# check_index_coverage (128 paths a call) and query_graph's File list, judged by cj
# cbm-verdict (index_verdict in coordinator_json.py; the rules are in its docstring and in
# docs/WORKFLOW.md 程式索引). cbm_report is one line per path ("stale|ok|skip<TAB>reason<TAB>
# freshness<TAB>path"). Returns 0 fresh, 1 stale (cbm_error names the paths), 2 the answer
# could not be had or read (cbm_error says why).
cbm_verify() {
  local paths="$1" args files rc=0 parts=()
  cbm_report=""
  [ -n "$paths" ] || { cbm_error="沒有要驗證的路徑"; return 2; }
  cbm_call query_graph "{\"project\":$(json_str "$cbm_project"),\"query\":\"MATCH (f:File) RETURN f.file_path\"}" \
    || return 2
  files="$cbm_out"
  while IFS= read -r args; do
    [ -n "$args" ] || continue
    cbm_call check_index_coverage "$args" || return 2
    parts+=("$cbm_out")
  done < <(printf '%s\n' "$paths" | cj cbm-chunks "$cbm_project")
  [ ${#parts[@]} -gt 0 ] || { cbm_error="cj cbm-chunks 沒有產生 check_index_coverage 參數"; return 2; }
  cbm_report="$(printf '%s\0' "$paths" "$files" "${parts[@]}" | cj cbm-verdict "$(native "$repo_root")" "$cbm_project" 2>&1)" || rc=$?
  case "$rc" in
    0) return 0 ;;
    1)
      cbm_error="索引過期：$(printf '%s\n' "$cbm_report" | awk -F '\t' '$1 == "stale" { printf "%s%s（%s）", n++ ? "、" : "", $4, $2 }')"
      return 1
      ;;
    *) cbm_error="判定失敗：$(printf '%s' "$cbm_report" | tail -n 3 | tr '\r\n' '  ')"; return 2 ;;
  esac
}

# cbm_only_mtime: every stale line of cbm_report is the mtime rule, the one a forced
# rebuild can clear.
cbm_only_mtime() {
  printf '%s\n' "$cbm_report" | awk -F '\t' '$1 == "stale" { n++; if ($2 != "mtime") bad = 1 } END { exit !(n && !bad) }'
}

# cbm_ensure WHEN PATHS: WHEN is "rebuilt" (close_task.sh: rebuild first) or "check"
# (dispatch.sh: verify, rebuild once when stale). After a rebuild that leaves only the mtime
# rule stale, one forced rebuild (cbm_rebuild force) and a last verify. cbm_steps lists what
# ran (index_rebuilt, index_forced, index_fresh:<n> paths); fails with cbm_error.
cbm_ensure() {
  local when="$1" paths="$2" rc n
  cbm_steps=()
  n="$(printf '%s\n' "$paths" | grep -c .)"
  if [ "$when" = check ]; then
    rc=0
    cbm_verify "$paths" || rc=$?
    [ "$rc" = 0 ] && { cbm_steps+=("index_fresh:$n"); return 0; }
    [ "$rc" = 1 ] || return 1
    cbm_steps+=("index_stale")
  fi
  cbm_rebuild || return 1
  cbm_steps+=("index_rebuilt")
  rc=0
  cbm_verify "$paths" || rc=$?
  [ "$rc" = 0 ] && { cbm_steps+=("index_fresh:$n"); return 0; }
  [ "$rc" = 1 ] && cbm_only_mtime || return 1
  cbm_rebuild force || return 1
  cbm_steps+=("index_forced")
  cbm_verify "$paths" || return 1
  cbm_steps+=("index_fresh:$n")
}

# --- the Claude Code memory directory (#705; docs/COORDINATOR.md 記憶) ------------------
# memory_check: tools/ops/memory_check.py, read only, on the memory directory every session
# loads ($STOCK_MEMORY_DIR, else the one Claude Code keeps for this repo under
# $CLAUDE_CONFIG_DIR or ~/.claude), repo paths checked on origin/master of this checkout.
# Returns its exit code (0 passed, 1 a check failed, 2 no directory or git failed);
# memory_out is its output, memory_failures the failures alone joined by "；".
memory_out="" memory_failures=""
memory_check() {
  local rc=0
  memory_out="$("$python" -X utf8 "$script_dir/memory_check.py" --repo "$repo_root" 2>&1)" || rc=$?
  memory_out="$(printf '%s' "$memory_out" | tr -d '\r')"
  memory_failures="$(printf '%s\n' "$memory_out" | awk '
    /^memory_check: (失敗 [0-9]+ 項|通過)（/ { next }
    { sub(/^memory_check: /, ""); printf "%s%s", n++ ? "；" : "", $0 }')"
  return "$rc"
}
