#!/usr/bin/env bash
# Rehearsal of tools/ops/deploy.sh with real Docker (#340); CI compose job, or by hand from the
# repo root (Git Bash on Windows too, where deploy.sh runs in production):
#
#   bash tools/compose/deploy_smoke.sh
#
# A throwaway origin holding this checkout's files as one commit with the tags t1 and t2, a
# release checkout cloned from it, a fake gh that reports every commit's CI as success, and
# --no-comment. Its own project (DEPLOY_SMOKE_PROJECT, default stock-lab-deploy-smoke) and
# ports (DEPLOY_SMOKE_WEB_PORT 18180, DEPLOY_SMOKE_API_PORT 18100), no env file; it never
# reads .env and never touches another project.
#
# 1. Deploy t1 with no scheduler running (no locks to take): every service runs its t1 image.
# 2. A job holds the daily lock in the scheduler: deploy t2 is refused (exit 1) and the images,
#    containers, volumes and the volume's deploy.json are as before.
# 3. Deploy t2: the locks are taken and let go, every service runs its t2 image, the record
#    names t2 and the t1 image before it, and the new scheduler's watchdog check is ok.
#
# At the end it removes the project's containers, network, volume and images, and the
# throwaway directory. So the project must be a test one (tools/compose/test_project.sh):
# stock-lab or STOCK_COMPOSE_PROJECT, or a name without t<n>/task-<n>/smoke, exits 2 first.
# deploy.sh gets the ports and the missing env file as options: it drops inherited ones.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
project="${DEPLOY_SMOKE_PROJECT:-stock-lab-deploy-smoke}"
. "$repo/tools/compose/test_project.sh"
refuse_unless_test_project "$project"
export WEB_PORT="${DEPLOY_SMOKE_WEB_PORT:-18180}" API_PORT="${DEPLOY_SMOKE_API_PORT:-18100}"
work="$(mktemp -d)"
# No env file: a path that does not exist (docker-compose.yml, required: false).
export STOCK_ENV_FILE="$work/no-env-file"
# Container paths (/data, /tmp) reach docker as written; only docker's, as git in deploy.sh
# needs Git Bash's conversion.
docker() { MSYS_NO_PATHCONV=1 command docker "$@"; }
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME
python="${STOCK_PYTHON:-$(command -v python3 || command -v python)}"
release="$work/release"
native() { if command -v cygpath > /dev/null; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
compose() { docker compose -p "$project" -f "$(native "$release")/docker-compose.yml" "$@"; }

cleanup() {
    STOCK_RELEASE_TAG=t1 compose down --volumes --remove-orphans > /dev/null 2>&1 || true
    for ref in backend:seed backend:t1 backend:t2 web:t1 web:t2; do
        docker image rm "$project-$ref" > /dev/null 2>&1 || true
    done
    rm -rf -- "$work"
}
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# The origin: this checkout's tracked files as they are in the working tree (a shallow CI
# checkout cannot be pushed), committed once and tagged twice.
git_q() { git -c user.name=deploy-smoke -c user.email=deploy-smoke@example.com -c init.defaultBranch=main "$@"; }
mkdir -p "$work/src" "$work/bin"
git -C "$repo" ls-files -z | tar -C "$repo" --null -T - -cf - | tar -xf - -C "$work/src"
git_q -C "$work/src" init --quiet
git_q -C "$work/src" add -A
git_q -C "$work/src" commit --quiet -m "deploy smoke"
git_q -C "$work/src" tag t1
git_q -C "$work/src" tag -a t2 -m t2
git_q clone --quiet --bare "$work/src" "$work/origin.git"
git_q clone --quiet --no-tags "$work/origin.git" "$release"
sha="$(git -C "$work/src" rev-parse HEAD)"

cat > "$work/bin/gh" << 'EOF'
#!/usr/bin/env bash
# gh run list --commit <sha> ...: one green CI run of that commit.
while [ $# -gt 0 ]; do
  [ "$1" = --commit ] && { printf '[{"databaseId": 1, "headSha": "%s", "status": "completed", "conclusion": "success"}]\n' "$2"; exit 0; }
  shift
done
echo "deploy smoke: unexpected gh call" >&2
exit 1
EOF
chmod +x "$work/bin/gh"

# PATH takes /c/... in Git Bash, never C:/... (mktemp's form when TMPDIR is one).
bin="$work/bin"
command -v cygpath > /dev/null && bin="$(cygpath -u "$bin")"
deploy() {
    PATH="$bin:$PATH" STOCK_PYTHON="$python" bash "$repo/tools/ops/deploy.sh" "$1" \
        --checkout "$release" --project "$project" --operator deploy-smoke --no-comment \
        --web-port "$WEB_PORT" --api-port "$API_PORT" --env-file "$STOCK_ENV_FILE"
}

# images: the project's image tags; state: what a refused deploy must leave as it was.
images() { docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep "^$project-" | sort; }
state() {
    images
    docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}} {{.ID}} {{.Image}} {{.State}}' | sort
    docker volume ls -q --filter "label=com.docker.compose.project=$project" | sort
    STOCK_RELEASE_TAG=t1 compose exec -T scheduler cat /data/logs/deploy.json
}

expect_images() {
    local tag="$1" running
    running="$(STOCK_RELEASE_TAG="$tag" compose ps --format '{{.Service}} {{.Image}} {{.State}}' | sort)"
    echo "$running"
    [ "$running" = "$(printf 'api %s running\nscheduler %s running\nweb %s running' \
        "$project-backend:$tag" "$project-backend:$tag" "$project-web:$tag")" ] \
        || fail "the services do not all run their $tag images"
}

echo "== seed: the verify fixture database in the project's stock-data volume"
STOCK_RELEASE_TAG=seed compose run --rm --no-deps --build -e STOCK_SEED_FIXTURE=1 api true

echo "== 1. deploy t1, no scheduler running"
deploy t1 | tee "$work/t1.json"
grep -q '"deployed": true' "$work/t1.json" || fail "t1 not deployed"
grep -q '"locks": "none"' "$work/t1.json" || fail "t1 took locks without a scheduler"
STOCK_RELEASE_TAG=t1 compose ps
expect_images t1

echo "== 2. a job holds the daily lock: deploy t2 is refused and changes nothing"
scheduler="$(STOCK_RELEASE_TAG=t1 compose ps -q scheduler)"
docker exec -d "$scheduler" sh -c 'echo $$ > /tmp/holder.pid; exec python -m worker.job lock /data/locks/daily.lock -- sleep 600'
for _ in $(seq 30); do
    code=0
    docker exec "$scheduler" python -m worker.job lock /data/locks/daily.lock -- true 2> /dev/null || code=$?
    [ "$code" = 75 ] && break
    sleep 1
done
[ "$code" = 75 ] || fail "the test job did not take the daily lock"
before="$(state)"
set +e
deploy t2 > "$work/t2-refused.json"
code=$?
set -e
cat "$work/t2-refused.json"
[ "$code" = 1 ] || fail "deploy t2 with the daily lock held: exit $code, want 1"
grep -q '排程執行中' "$work/t2-refused.json" || fail "refused for another reason"
after="$(state)"
[ "$before" = "$after" ] || fail "a refused deploy changed something: $(diff <(echo "$before") <(echo "$after"))"
echo "ok unchanged:"
echo "$after"
docker exec "$scheduler" sh -c 'kill "$(cat /tmp/holder.pid)"'

echo "== 3. deploy t2"
deploy t2 | tee "$work/t2.json"
grep -q '"deployed": true' "$work/t2.json" || fail "t2 not deployed"
grep -q '"locks": "held"' "$work/t2.json" || fail "t2 took no locks with a scheduler running"
grep -q "\"previous_image\": \"$project-backend:t1\"" "$work/t2.json" || fail "t2 does not name t1 before it"
STOCK_RELEASE_TAG=t2 compose ps
expect_images t2
record="$(STOCK_RELEASE_TAG=t2 compose exec -T scheduler cat /data/logs/deploy.json)"
echo "$record"
"$python" -c 'import json, sys; r = json.loads(sys.argv[1]); assert (r["tag"], r["HEAD"], r["image"], r["previous_image"]) == ("t2", sys.argv[2], sys.argv[3] + "-backend:t2", sys.argv[3] + "-backend:t1"), r' \
    "$record" "$sha" "$project" || fail "the record is not t2's"
STOCK_RELEASE_TAG=t2 compose exec -T scheduler bash /app/tools/ops/watchdog.sh --dry-run --data-dir /data 2> /dev/null | grep 'invariant deploy_image' | tee "$work/watchdog.txt"
grep -q '^invariant deploy_image ok ' "$work/watchdog.txt" || fail "the scheduler's watchdog does not find its image recorded"
docker exec "$(STOCK_RELEASE_TAG=t2 compose ps -q scheduler)" python -m worker.job lock /data/locks/daily.lock -- true \
    || fail "the daily lock is still held after the deploy"
echo "ok the locks are free"

echo "deploy smoke passed"
