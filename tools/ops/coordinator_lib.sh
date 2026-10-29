# Shared by dispatch.sh, close_task.sh, patrol.sh (Issue #282) and deploy.sh (#314); sourced, not run.
# Callers set script_dir before sourcing. orca, gh and git are looked up on PATH so the
# tests can put recording fakes in front of them (backend/tests/test_coordinator_scripts.py).
export LANG=C.UTF-8 LC_ALL=C.UTF-8

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
