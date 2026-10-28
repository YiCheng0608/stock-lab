#!/usr/bin/env bash
# Smoke test of docker-compose.yml and docker-compose.dev.yml (#335); CI compose job, or by hand
# from the repo root:
#
#   bash tools/compose/smoke.sh
#
# 1. The entrypoint refuses WEB_PORT 80 and 8000 and API_PORT 80 (exit 64).
# 2. Base topology (nginx web, its /api to the api): api and web turn healthy; a browser's
#    write through WEB_PORT and a script's straight to API_PORT get 2xx, a foreign Origin 403;
#    the api restarts after its process ends; the scheduler's serve starts.
# 3. Dev topology (Vite on WEB_PORT, calling API_PORT): the same writes with the pages' Origin.
# 4. The env file reaches the api and the scheduler; without one both still start.
#
# Its own project (SMOKE_PROJECT, default stock-lab-smoke) and ports (SMOKE_WEB_PORT 18080,
# SMOKE_API_PORT 18000) and a throwaway env file; it never reads .env. SMOKE_BASE_FILE replaces
# docker-compose.yml (paths still resolve from the repo root). At the end it removes the
# project's containers, network and volumes; the images stay for the next run.
set -euo pipefail

project="${SMOKE_PROJECT:-stock-lab-smoke}"
web_port="${SMOKE_WEB_PORT:-18080}"
api_port="${SMOKE_API_PORT:-18000}"
work="$(mktemp -d)"
base=(docker compose -p "$project" --project-directory . -f "${SMOKE_BASE_FILE:-docker-compose.yml}")
dev=("${base[@]}" -f docker-compose.dev.yml)
export STOCK_ENV_FILE="$work/smoke.env" WEB_PORT="$web_port" API_PORT="$api_port"
printf '# compose smoke test (tools/compose/smoke.sh): no secrets\nSMOKE_MARK=from-env-file\n' > "$STOCK_ENV_FILE"

cleanup() {
    "${dev[@]}" --profile scheduler down --volumes --remove-orphans > /dev/null 2>&1 || true
    rm -f "$STOCK_ENV_FILE"
    rmdir "$work" 2> /dev/null || true
}
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# expect <status> <curl args...>: the request's status code must be <status>.
expect() {
    local want="$1" got
    shift
    got="$(curl -sS -o "$work/body" -w '%{http_code}' "$@")"
    [ "$got" = "$want" ] || fail "$* -> $got, want $want: $(cat "$work/body")"
    echo "ok $got $*"
}

json=(-H 'Content-Type: application/json')
position='{"symbol":"9101","exchange":"TWSE","shares":1000,"average_cost":100}'

# write <origin header or ""> <site> <url base>: POST then DELETE a position, both 200.
write() {
    local origin=() site=()
    [ -z "$1" ] || origin=(-H "Origin: $1")
    [ -z "$2" ] || site=(-H "Sec-Fetch-Site: $2")
    expect 200 -X POST "${origin[@]}" "${site[@]}" "${json[@]}" -d "$position" "$3/portfolio"
    local id
    id="$(grep -o '"id":[0-9]*' "$work/body" | head -n 1 | cut -d: -f2)"
    [ -n "$id" ] || fail "no id in $(cat "$work/body")"
    expect 200 -X DELETE "${origin[@]}" "${site[@]}" "$3/portfolio/$id"
}

echo "== build"
"${base[@]}" build
"${dev[@]}" build web

echo "== 1. ports the entrypoint refuses"
for ports in "WEB_PORT=80" "WEB_PORT=8000" "API_PORT=80"; do
    set +e
    env "$ports" "${base[@]}" run --rm --no-deps api true 2> "$work/err"
    code=$?
    set -e
    [ "$code" = 64 ] || fail "$ports: exit $code, want 64: $(cat "$work/err")"
    echo "ok $ports exit 64: $(grep entrypoint: "$work/err")"
done

echo "== 2. base topology"
"${base[@]}" run --rm --no-deps -e STOCK_SEED_FIXTURE=1 api true
"${base[@]}" up -d --wait api web
"${base[@]}" ps
pages="http://localhost:$web_port"
expect 200 "$pages/"
expect 200 "$pages/stocks/TWSE/9101"
write "$pages" same-origin "$pages/api"
write "" "" "http://localhost:$api_port/api"
expect 403 -X POST -H "Origin: http://localhost:9" -H "Sec-Fetch-Site: cross-site" "${json[@]}" -d "$position" "$pages/api/portfolio"

api="$("${base[@]}" ps -q api)"
before="$(docker inspect -f '{{.RestartCount}}' "$api")"
# The api's process ends (tini, PID 1, passes the signal on); restart: unless-stopped brings
# it back, as docker stop would not.
"${base[@]}" exec -T api kill -TERM 1
# Docker itself starts it again; starting it from here too would race it for the port.
for _ in $(seq 90); do
    after="$(docker inspect -f '{{.RestartCount}} {{.State.Health.Status}}' "$api")"
    [ "${after%% *}" -gt "$before" ] && [ "${after#* }" = healthy ] && break
    sleep 1
done
[ "${after%% *}" -gt "$before" ] && [ "${after#* }" = healthy ] || fail "api restart count and health: $before -> $after"
echo "ok api restarted: restart count $before -> $after"

"${base[@]}" up -d scheduler
for _ in $(seq 60); do
    if "${base[@]}" logs scheduler 2>&1 | grep -q 'serve ready'; then break; fi
    sleep 1
done
"${base[@]}" logs scheduler 2>&1 | grep 'serve ready' || fail "scheduler: no 'serve ready' in its log"
"${base[@]}" stop scheduler
"${base[@]}" down

echo "== 3. dev topology"
"${dev[@]}" up -d --wait api web
"${dev[@]}" ps
expect 200 "$pages/"
grep -F '/@vite/client' "$work/body" > /dev/null || fail "the dev pages are not Vite's"
write "$pages" same-site "http://localhost:$api_port/api"
expect 403 -X POST -H "Origin: http://localhost:9" -H "Sec-Fetch-Site: cross-site" "${json[@]}" -d "$position" "http://localhost:$api_port/api/portfolio"
"${dev[@]}" down

echo "== 4. env file"
for service in api scheduler; do
    got="$("${base[@]}" run --rm --no-deps "$service" sh -c 'echo "${SMOKE_MARK:-unset}"')"
    [ "$got" = from-env-file ] || fail "$service: SMOKE_MARK=$got, want from-env-file"
    echo "ok $service reads the env file"
done
export STOCK_ENV_FILE="$work/missing.env"
"${base[@]}" config -q
for service in api scheduler; do
    got="$("${base[@]}" run --rm --no-deps "$service" sh -c 'echo "${SMOKE_MARK:-unset}"')"
    [ "$got" = unset ] || fail "$service without an env file: SMOKE_MARK=$got"
    echo "ok $service starts without an env file"
done

echo "compose smoke passed"
