# Shared by dispatch.sh, close_task.sh and patrol.sh (Issue #282); sourced, not run.
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

# norm PATH: absolute, '..' and '.' removed, symlinks not resolved; lower case on Windows.
norm() {
  local p="$1"
  if is_windows; then
    p="$(cygpath -u -- "$p")"
    p="$(realpath -m -s -- "$p")"
    printf '%s' "${p,,}"
  else
    realpath -m -s -- "$p"
  fi
}
within() { [ "$1" = "$2" ] || case "$1" in "$2"/*) return 0 ;; *) return 1 ;; esac; } # within A B: A is B or under B

# guard_dir PATH [residual]: why PATH must not be deleted, or nothing. "residual" is a
# worktree directory git no longer lists: its own .git file does not count.
guard_dir() {
  local p d home root
  p="$(norm "$1")"
  home="$(norm "$HOME")"
  case "/${p#/}/" in */stock-lab-data/*) echo "在 stock-lab-data 之下"; return ;; esac
  for d in "$data_dir" ${STOCK_DATA_DIR:+"$STOCK_DATA_DIR"}; do
    d="$(norm "$d")"
    if within "$p" "$d" || within "$d" "$p"; then echo "是資料目錄或包含資料目錄（$d）"; return; fi
  done
  [ "$p" = / ] && { echo "是根目錄"; return; }
  is_windows && case "$p" in /[a-z] | /[a-z]/) echo "是磁碟根目錄"; return ;; esac
  within "$home" "$p" && { echo "是 \$HOME 或它的上層"; return; }
  while IFS= read -r root; do
    root="$(norm "$root")"
    if within "$p" "$root" || within "$root" "$p"; then echo "是 git checkout 或與它重疊（$root）"; return; fi
  done < <(git -C "$repo_root" worktree list --porcelain | tr -d '\r' | sed -n 's/^worktree //p'; printf '%s\n' "$repo_root")
  [ "${2:-}" = residual ] && return
  d="$p"
  while [ -n "$d" ] && [ "$d" != / ]; do
    { [ -e "$d/.git" ] || [ -L "$d/.git" ]; } && { echo "位於 git repo 之內（$d）"; return; }
    d="${d%/*}"
  done
  if [ -d "$p" ] && [ ! -L "$p" ] && [ -n "$(find "$p" -name .git -print -quit 2>/dev/null)" ]; then
    echo "裡面有 .git"
  fi
  return 0
}
