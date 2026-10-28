#!/usr/bin/env bash
# Deploy a tag to the release checkout (Issue #314; docs/RELEASE.md). The scheduled jobs
# run whatever the release checkout has checked out and never pull, so this is the one
# way a new version reaches them. Run it from another checkout (the master management
# checkout): checking out the tag rewrites the files of the checkout it deploys to.
#
# Refuses, changing nothing in the checkout, when:
#   - the checkout has uncommitted changes (untracked files count) or a git operation
#     in progress (index.lock, MERGE_HEAD);
#   - origin has no such tag;
#   - the newest CI run of the tag's own commit is not success (`gh run list --commit`;
#     the commit need not be on master: a release/v1 commit has its own CI);
#   - a scheduled job is running: the daily, news and watchdog locks of the data
#     directory (backend/worker/job.py) are taken for the whole checkout, so no job
#     starts until it is done, and a held one refuses the deploy;
#   - the tag predates #314 (no tools/ops/deploy.sh in it): its job pulls before every
#     run and would record git_pull_failed on the detached HEAD.
# Then: fetch the tag, `git checkout` it (detached HEAD), reinstall the venv when
# backend/requirements.txt or backend/validation-requirements.lock.txt changed (or
# with --reinstall), read HEAD back, write <data>/logs/deploy.json (tag, HEAD, previous
# HEAD, time, operator; the watchdog compares the checkout's HEAD with it) and comment
# the tag and HEAD on #1. Whether a deploy is authorised is not checked here: deploying
# is the user's decision (docs/GITHUB_WORKFLOW.md 無人值守運作).
#
# Usage: deploy.sh <tag> [options]
#   --checkout DIR    the release checkout; default $STOCK_RELEASE_DIR, then $HOME/stock-lab-release
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --operator NAME   who deploys, for deploy.json and #1; default git config user.name
#   --reinstall       reinstall the venv even when the lock files did not change
#   --no-comment      no comment on #1 (a rehearsal on a throwaway checkout)
#   --python EXE      Python for the locks; default $STOCK_PYTHON, then this checkout's .venv, then python3
# Prints one JSON line. Exit 0 deployed; 1 refused (the checkout is unchanged); 3 a step
# failed after the checkout started (no deploy.json is written, so the watchdog reports
# the mismatch; fix the cause and run again, with --reinstall after a failed venv
# install); 4 deployed but the #1 comment failed; 2/64 bad setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

arguments=("$@")
tag="" checkout="${STOCK_RELEASE_DIR:-$HOME/stock-lab-release}" operator="" reinstall=0 comment=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --reinstall) reinstall=1 ;;
    --no-comment) comment=0 ;;
    --checkout | --data-dir | --operator | --python)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value" 64
      case "$1" in
        --checkout) checkout="$2" ;;
        --data-dir) data_dir="$2" ;;
        --operator) operator="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      continue
      ;;
    -*) die "unknown argument: $1" 64 ;;
    *) [ -z "$tag" ] && tag="$1" || die "unexpected argument: $1" 64 ;;
  esac
  shift
done
[ -n "$tag" ] || die "usage: deploy.sh <tag> [options]" 64
git check-ref-format "refs/tags/$tag" || die "不是合法的 tag 名稱：$tag" 64
find_python

refuse() {
  printf '{"deployed": false, "tag": %s, "reason": %s}\n' "$(json_str "$tag")" "$(json_str "$1")"
  die "拒絕部署：$1" 1
}
fail() {
  printf '{"deployed": false, "tag": %s, "failed": %s}\n' "$(json_str "$tag")" "$(json_str "$1")"
  die "部署中斷：$1" 3
}

checkout="$(cd "$checkout" 2>/dev/null && pwd)" || die "發佈 checkout 不存在：$checkout" 2
git -C "$checkout" rev-parse --git-dir >/dev/null 2>&1 || die "不是 git checkout：$checkout" 2
mkdir -p "$data_dir/logs" || die "無法建立 $data_dir/logs" 2
data_dir="$(cd "$data_dir" && pwd)"
record="$data_dir/logs/deploy.json"

# clean: no uncommitted change and no git operation in progress in the checkout.
clean() {
  local status marker
  for marker in index.lock MERGE_HEAD; do
    [ -e "$(git -C "$checkout" rev-parse --path-format=absolute --git-path "$marker")" ] \
      && refuse "發佈 checkout 有進行中的 git 操作（$marker）"
  done
  status="$(git -C "$checkout" status --porcelain)" || refuse "讀不到發佈 checkout 的 git status"
  [ -z "$(printf '%s' "$status" | tr -d '\r')" ] || refuse "發佈 checkout 有未 commit 的改動：$checkout"
}

if [ -z "${DEPLOY_LOCKS_HELD:-}" ]; then
  within "$script_dir" "$checkout" && refuse "這支腳本在發佈 checkout 裡；請從另一個 checkout（master 管理 checkout）執行"
  clean
  refs="$(git -C "$checkout" ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")" \
    || refuse "git ls-remote origin 失敗"
  refs="$(printf '%s\n' "$refs" | tr -d '\r')"
  # An annotated tag's commit is on its peeled ^{} line; a lightweight tag has only one.
  sha="$(printf '%s\n' "$refs" | awk -v r="refs/tags/$tag^{}" '$2 == r { print $1 }')"
  [ -n "$sha" ] || sha="$(printf '%s\n' "$refs" | awk -v r="refs/tags/$tag" '$2 == r { print $1 }')"
  [ -n "$sha" ] || refuse "origin 沒有 tag $tag"
  out="$(gh run list --repo "$GH_REPO" --commit "$sha" --workflow CI --limit 20 \
    --json headSha,status,conclusion)" || refuse "gh run list 失敗"
  read -r ci _ <<<"$(printf '%s' "$out" | cj ci-state "$sha")"
  [ "$ci" = success ] || refuse "tag $tag 的 commit ${sha:0:9} 最新一次 CI 是 $ci，不是 success"

  # The job locks, held for the rest of the deploy: Python takes each and runs the
  # next as its child, the innermost runs this script again (DEPLOY_LOCKS_HELD).
  locks="$data_dir/locks"
  (cd "$repo_root/backend" && DEPLOY_LOCKS_HELD=1 DEPLOY_SHA="$sha" exec \
    "$python" -X utf8 -m worker.job lock "$locks/daily.lock" -- \
    "$python" -X utf8 -m worker.job lock "$locks/news.lock" -- \
    "$python" -X utf8 -m worker.job lock "$locks/watchdog.lock" -- \
    "$BASH" "$script_dir/deploy.sh" "${arguments[@]}")
  status=$?
  [ "$status" = 75 ] && refuse "排程執行中（$locks 的 daily、news 或 watchdog 鎖被持有）"
  [ "$status" = 0 ] || exit "$status"

  head="$(cj get HEAD <"$record")" && previous="$(cj get previous_HEAD <"$record")" \
    && who="$(cj get operator <"$record")" && when="$(cj get deployed_at <"$record")" \
    && venv="$(cj get venv_reinstalled <"$record")" || fail "讀不到剛寫入的 $record"
  commented=false
  if [ "$comment" = 1 ]; then
    body="$(mktemp)"
    trap 'rm -f "$body"' EXIT
    cat >"$body" <<EOF
部署：發佈 checkout 切到 tag \`$tag\`

- HEAD：\`$head\`（前一版 \`$previous\`）
- 操作者：$who；時間：$when（UTC）
- venv 重裝：$venv

（\`tools/ops/deploy.sh\` 自動留言；部署記錄 \`$record\`，看門狗以它核對發佈 checkout 的 HEAD。）
EOF
    if ! gh issue comment 1 --repo "$GH_REPO" --body-file "$body" >/dev/null; then
      printf '{"deployed": true, "tag": %s, "HEAD": "%s", "commented": false}\n' "$(json_str "$tag")" "$head"
      die "已部署 $tag（$head），但 #1 留言失敗；請手動補記" 4
    fi
    commented=true
  fi
  printf '{"deployed": true, "tag": %s, "HEAD": "%s", "previous_HEAD": "%s", "venv_reinstalled": %s, "commented": %s, "record": %s}\n' \
    "$(json_str "$tag")" "$head" "$previous" "$venv" "$commented" "$(json_str "$record")"
  exit 0
fi

# --- holding the locks: the checkout itself ------------------------------------------
sha="${DEPLOY_SHA:?}"
clean
previous="$(git -C "$checkout" rev-parse --verify HEAD)" || refuse "讀不到發佈 checkout 的 HEAD"
git -C "$checkout" fetch --quiet --no-tags origin "refs/tags/$tag:refs/tags/$tag" \
  || refuse "git fetch 不到 tag $tag（本機已有同名但指向別處的 tag 時也會失敗）"
[ "$(git -C "$checkout" rev-parse --verify --quiet "refs/tags/$tag^{commit}")" = "$sha" ] \
  || refuse "fetch 到的 tag $tag 不是 CI 核對過的 ${sha:0:9}"
git -C "$checkout" cat-file -e "$sha:tools/ops/deploy.sh" 2>/dev/null \
  || refuse "tag $tag 早於 #314：它的 job 起跑前會 git pull，在 detached HEAD 上會記 git_pull_failed"
venv_reinstalled=false
lock_files=(backend/requirements.txt backend/validation-requirements.lock.txt)
git -C "$checkout" diff --quiet "$previous" "$sha" -- "${lock_files[@]}" || reinstall=1

git -C "$checkout" -c advice.detachedHead=false checkout --quiet "refs/tags/$tag" \
  || fail "git checkout $tag 失敗"
[ "$(git -C "$checkout" rev-parse --verify HEAD)" = "$sha" ] || fail "checkout 後 HEAD 不是 ${sha:0:9}"
if [ "$reinstall" = 1 ]; then
  venv_python=""
  for c in "$checkout/.venv/Scripts/python.exe" "$checkout/.venv/bin/python"; do
    [ -f "$c" ] && venv_python="$c" && break
  done
  [ -n "$venv_python" ] || fail "依賴有變但找不到 $checkout/.venv；建好 venv 後以 --reinstall 再跑"
  "$venv_python" -m pip install --disable-pip-version-check -r "$checkout/${lock_files[0]}" \
    -c "$checkout/${lock_files[1]}" >&2 || fail "venv 重裝失敗；修好後以 --reinstall 再跑"
  venv_reinstalled=true
fi

[ -n "$operator" ] || operator="$(git -C "$repo_root" config user.name)" || operator="${USERNAME:-${USER:-unknown}}"
"$python" -X utf8 - "$record" "$tag" "$sha" "$previous" "$operator" "$checkout" "$venv_reinstalled" <<'PY' \
  || fail "寫不了 $record"
import json, os, sys
from datetime import datetime, timezone

path, tag, head, previous, operator, checkout, venv = sys.argv[1:]
record = {
    "tag": tag,
    "HEAD": head,
    "previous_HEAD": previous,
    "deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "operator": operator,
    "checkout": checkout,
    "venv_reinstalled": venv == "true",
}
with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as handle:
    json.dump(record, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.replace(path + ".tmp", path)
PY
