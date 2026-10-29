#!/usr/bin/env bash
# Deploy a tag as images (Issue #340, after #314; docs/RELEASE.md): build the backend and web
# images of the tag, tag them with its name, `docker compose up -d` them, record what runs and
# comment on #1. The scheduled jobs run in the scheduler container on the image, so this is the
# one way a new version reaches them. The release checkout is the compose project directory:
# the tag is checked out there (the build context and the compose file are the tag's) and the
# env file (.env, never in Git) stays there. Run it from another checkout (the master
# management checkout): checking out the tag rewrites the files of the release checkout.
#
# Refuses, leaving the checkout, the images, the containers and the volumes as they were, when:
#   - the checkout has uncommitted changes (untracked files count, ignored ones do not) or a
#     git operation in progress (index.lock, MERGE_HEAD);
#   - origin has no such tag;
#   - the latest CI run of the tag's own commit (`gh run list --commit`, highest run id)
#     is not success; the commit need not be on master (a release/v1 commit has its own CI);
#   - a scheduled job is running: the daily, news and watchdog locks of the data volume
#     (backend/worker/job.py) are taken inside the running scheduler container
#     (`worker.job lock --keep-stdin`, held until this script closes its stdin or dies) and
#     kept until the new containers are up, so no job starts meanwhile; a held one refuses
#     the deploy. With no scheduler running no scheduled job can run, and none is taken;
#   - the tag predates #340: its docker-compose.yml does not tag the images with
#     STOCK_RELEASE_TAG, so what runs could not be told from the image.
# Then: fetch the tag, `git checkout` it (detached HEAD), `docker compose build` with
# STOCK_RELEASE_TAG=<tag> and STOCK_GIT_HEAD=<its commit> (images <project>-backend:<tag> and
# <project>-web:<tag>), write /data/logs/deploy.json in the volume (tag, HEAD, images, the
# image the scheduler ran before, time, operator; the watchdog compares the scheduler's image
# with it), `docker compose up -d --no-build --wait`, read back that each service runs its
# tagged image and that the new scheduler's own check (watchdog_helper.py deploy-image) is
# ok, release the locks and comment on #1. Whether a deploy is authorised is not checked
# here: deploying is the user's decision (docs/GITHUB_WORKFLOW.md 無人值守運作).
#
# Usage: deploy.sh <tag> [options]
#   --checkout DIR      the release checkout; default $STOCK_RELEASE_DIR, then $HOME/stock-lab-release
#   --project NAME      the compose project; default $STOCK_COMPOSE_PROJECT, then stock-lab
#                       (COMPOSE_PROJECT_NAME is ignored: a task session sets it to task-<issue>)
#   --operator NAME     who deploys, for the record and #1; default git config user.name
#   --wait-timeout SEC  for `compose up --wait`; default 300
#   --no-comment        no comment on #1 (a rehearsal on a throwaway checkout and project)
#   --python EXE        Python for the JSON; default $STOCK_PYTHON, then this checkout's .venv, then python3
# Prints one JSON line. Exit 0 deployed; 1 refused (nothing changed); 3 a step failed after the
# checkout started: before the record (build) the containers still run the previous images and
# the record is the previous one; after it (up, read-back) the watchdog reports the mismatch;
# fix the cause and run again with the same tag; 4 deployed but the #1 comment failed; 2/64 bad
# setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

tag="" checkout="${STOCK_RELEASE_DIR:-$HOME/stock-lab-release}" project="${STOCK_COMPOSE_PROJECT:-stock-lab}"
operator="" wait_timeout=300 comment=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-comment) comment=0 ;;
    --checkout | --project | --operator | --wait-timeout | --python)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value" 64
      case "$1" in
        --checkout) checkout="$2" ;;
        --project) project="$2" ;;
        --operator) operator="$2" ;;
        --wait-timeout) wait_timeout="$2" ;;
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
# The tag is also the images' tag: [A-Za-z0-9_][A-Za-z0-9_.-]{0,127}.
[[ "$tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die "tag $tag 不能當 image tag" 64
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "不是合法的 compose project 名稱：$project" 64
[[ "$wait_timeout" =~ ^[1-9][0-9]*$ ]] || die "--wait-timeout 要是正整數秒：$wait_timeout" 64
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
checkout_native="$(native "$checkout")" || die "發佈 checkout 不是本機的絕對路徑：$checkout" 2
command -v docker >/dev/null 2>&1 || die "找不到 docker" 2

# docker gets its own paths (/data/...) as written: Git Bash would turn them into C:/...
dk() { MSYS_NO_PATHCONV=1 docker "$@"; }
# Only this script's settings reach compose: the project and the file by name, the tag and its
# commit for the image names and STOCK_GIT_HEAD (docker-compose.yml). sha is set below.
unset COMPOSE_FILE COMPOSE_PROFILES
compose() {
  COMPOSE_PROJECT_NAME="$project" STOCK_RELEASE_TAG="$tag" STOCK_GIT_HEAD="$sha" \
    dk compose -p "$project" -f "$checkout_native/docker-compose.yml" "$@"
}
dk compose version >/dev/null 2>&1 || die "docker compose 無法執行（Docker Desktop 沒有開？）" 2

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
  --json databaseId,headSha,status,conclusion)" || refuse "gh run list 失敗"
ci="$(printf '%s' "$out" | cj commit-ci "$sha")"
[ "$ci" = success ] || refuse "tag $tag 的 commit ${sha:0:9} 最新一次 CI 是 $ci，不是 success"

# --- the job locks, in the running scheduler ----------------------------------------
scheduler="$(dk ps -q --filter "label=com.docker.compose.project=$project" \
  --filter label=com.docker.compose.service=scheduler --filter status=running)" \
  || die "docker ps 失敗" 2
scheduler="$(printf '%s\n' "$scheduler" | tr -d '\r' | head -n 1)"
locks=none previous=""
if [ -n "$scheduler" ]; then
  # Each lock runs the next as its child; the innermost says so and reads stdin until this
  # script closes it, or dies, which releases all three.
  hold=()
  for name in daily news watchdog; do
    hold+=(python -X utf8 -m worker.job lock --keep-stdin "/data/locks/$name.lock" --)
  done
  hold+=(sh -c 'echo held; exec cat >/dev/null')
  coproc LOCKS { dk exec -i "$scheduler" "${hold[@]}"; }
  lock_pid=$LOCKS_PID
  # Copies, as bash drops LOCKS when the coprocess ends; the originals closed, so closing
  # lock_in is the end of its stdin.
  exec {lock_out}<&"${LOCKS[0]}" {lock_in}>&"${LOCKS[1]}"
  eval "exec ${LOCKS[0]}<&- ${LOCKS[1]}>&-"
  line=""
  IFS= read -r -t 120 line <&"$lock_out" || true
  if [ "${line%$'\r'}" != held ]; then
    exec {lock_in}>&-
    wait "$lock_pid"
    code=$?
    [ "$code" = 75 ] && refuse "排程執行中（scheduler 容器的 daily、news 或 watchdog 鎖被持有）"
    die "在 scheduler 容器 ${scheduler:0:12} 拿不到排程鎖（exit $code）" 2
  fi
  locks=held
  previous="$(dk inspect -f '{{.Config.Image}}' "$scheduler")" \
    || die "讀不到 scheduler 容器 ${scheduler:0:12} 的 image" 2
  previous="${previous//$'\r'/}"
fi

# --- holding the locks: the checkout and the images -----------------------------------
clean
# A refusal after the fetch deletes the tag ref the fetch created, so a refused deploy
# leaves the checkout's tags as they were; a tag that was already there stays.
had_tag=0
git -C "$checkout" rev-parse --verify --quiet "refs/tags/$tag" >/dev/null && had_tag=1
refuse_fetched() {
  [ "$had_tag" = 1 ] || git -C "$checkout" update-ref -d "refs/tags/$tag" \
    || printf '%s: 刪不掉剛 fetch 的 tag %s\n' "$(basename "$0")" "$tag" >&2
  refuse "$1"
}
git -C "$checkout" fetch --quiet --no-tags origin "refs/tags/$tag:refs/tags/$tag" \
  || refuse "git fetch 不到 tag $tag（本機已有同名但指向別處的 tag 時也會失敗）"
[ "$(git -C "$checkout" rev-parse --verify --quiet "refs/tags/$tag^{commit}")" = "$sha" ] \
  || refuse_fetched "fetch 到的 tag $tag 不是 CI 核對過的 ${sha:0:9}"
git -C "$checkout" show "$sha:docker-compose.yml" 2>/dev/null | grep -q 'STOCK_RELEASE_TAG' \
  || refuse_fetched "tag $tag 早於 #340：它的 docker-compose.yml 不以 STOCK_RELEASE_TAG 為 image 打 tag，部署後無法核對跑的版本"

git -C "$checkout" -c advice.detachedHead=false checkout --quiet "refs/tags/$tag" \
  || fail "git checkout $tag 失敗"
[ "$(git -C "$checkout" rev-parse --verify HEAD)" = "$sha" ] || fail "checkout 後 HEAD 不是 ${sha:0:9}"
backend="$project-backend:$tag" web="$project-web:$tag"
compose build >&2 || fail "docker compose build 失敗；容器仍跑前一版，修好後以同一個 tag 再跑"
dk image inspect "$backend" "$web" >/dev/null || fail "build 後找不到 $backend 或 $web"

[ -n "$operator" ] || operator="$(git -C "$repo_root" config user.name)" || operator="${USERNAME:-${USER:-unknown}}"
deployed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
record="$("$python" -X utf8 - "$tag" "$sha" "$backend" "$web" "$previous" "$deployed_at" \
  "$operator" "$project" "$checkout_native" <<'PY'
import json, sys

tag, head, image, web, previous, deployed_at, operator, project, checkout = sys.argv[1:]
sys.stdout.reconfigure(newline="\n")
record = {
    "tag": tag,
    "HEAD": head,
    "image": image,
    "web_image": web,
    "previous_image": previous or None,
    "deployed_at": deployed_at,
    "operator": operator,
    "project": project,
    "checkout": checkout,
}
print(json.dumps(record, ensure_ascii=False, indent=2))
PY
)" || fail "組不出部署記錄"
# In a container of the new image: the volume is not on the host. The old watchdog cannot read
# it halfway (its lock is held); moved in whole.
printf '%s\n' "$record" | compose run --rm --no-deps -T --entrypoint sh scheduler -c \
  'mkdir -p /data/logs && cat >/data/logs/deploy.json.tmp && mv /data/logs/deploy.json.tmp /data/logs/deploy.json' >&2 \
  || fail "寫不了 volume 裡的 /data/logs/deploy.json；容器仍跑前一版"

compose up -d --no-build --wait --wait-timeout "$wait_timeout" >&2 \
  || fail "docker compose up 失敗；部署記錄已是 $tag，看門狗會回報 scheduler 的 image 不符；修好後以同一個 tag 再跑"
running="$(compose ps --format '{{.Service}} {{.Image}}')" || fail "docker compose ps 失敗"
running="${running//$'\r'/}"
for expected in "api $backend" "scheduler $backend" "web $web"; do
  printf '%s\n' "$running" | grep -qxF "$expected" \
    || fail "${expected%% *} 跑的不是 ${expected#* }：$(printf '%s' "$running" | tr '\n' ';')"
done
check="$(compose exec -T scheduler python -X utf8 /app/tools/ops/watchdog_helper.py deploy-image \
  /data/logs/deploy.json </dev/null)" || fail "讀不回新 scheduler 的版本核對"
check="${check//$'\r'/}"
case "$check" in
  "deploy_image ok "*) ;;
  *) fail "新 scheduler 的版本核對不是 ok：$check" ;;
esac
if [ "$locks" = held ]; then
  # The old scheduler took its exec along when up replaced it; a scheduler up kept as it was
  # (the same image) still holds them until now.
  exec {lock_in}>&-
  wait "$lock_pid" 2>/dev/null
fi

commented=false
if [ "$comment" = 1 ]; then
  body="$(mktemp)"
  trap 'rm -f "$body"' EXIT
  before="無（scheduler 沒有在執行）"
  [ -n "$previous" ] && before="\`$previous\`"
  cat >"$body" <<EOF
部署：tag \`$tag\` 的 image 已以 \`docker compose up -d\` 啟動

- HEAD：\`$sha\`
- image：\`$backend\`（api、scheduler）、\`$web\`（web）；前一版 $before
- compose project：\`$project\`；發佈 checkout：\`$checkout_native\`
- 操作者：$operator；時間：$deployed_at（UTC）

（\`tools/ops/deploy.sh\` 自動留言；部署記錄在 volume 的 \`/data/logs/deploy.json\`，看門狗以它核對 scheduler 跑的 image。）
EOF
  if ! gh issue comment 1 --repo "$GH_REPO" --body-file "$body" >/dev/null; then
    printf '{"deployed": true, "tag": %s, "HEAD": "%s", "image": %s, "commented": false}\n' \
      "$(json_str "$tag")" "$sha" "$(json_str "$backend")"
    die "已部署 $tag（$sha），但 #1 留言失敗；請手動補記" 4
  fi
  commented=true
fi
printf '{"deployed": true, "tag": %s, "HEAD": "%s", "image": %s, "web_image": %s, "previous_image": %s, "locks": "%s", "commented": %s}\n' \
  "$(json_str "$tag")" "$sha" "$(json_str "$backend")" "$(json_str "$web")" \
  "$([ -n "$previous" ] && json_str "$previous" || echo null)" "$locks" "$commented"
exit 0
