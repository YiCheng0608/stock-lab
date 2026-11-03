#!/usr/bin/env bash
# Checks a built frontend image (#334): the pages, the single-page fallback and the /api
# reverse proxy. CI's frontend-image job runs it; locally (Git Bash or Linux):
#
#   bash frontend/docker/smoke.sh <web image> <dev image>
#
# A stub upstream from the dev image (node) answers on a user-defined network under the
# alias api, the name API_UPSTREAM defaults to, and echoes what reached it. The web
# container (nginx on 8080, no process as root) publishes SMOKE_PORT (default 18080) on
# 127.0.0.1, so curl sends the Host a browser would: localhost:<port>. The stub must see
# that Host, not api:8000.
set -euo pipefail

web=${1:?usage: smoke.sh <web image> <dev image>}
dev=${2:?usage: smoke.sh <web image> <dev image>}
port=${SMOKE_PORT:-18080}
name=stock-lab-web-smoke-$$
work=$(mktemp -d)

cleanup() {
  docker rm -f "$name-web" "$name-api" > /dev/null 2>&1 || true
  docker network rm "$name" > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

fail() {
  printf 'smoke.sh: %s\n' "$1" >&2
  docker logs "$name-web" >&2 || true
  exit 1
}

stub='
require("node:http").createServer((req, res) => {
  let body = ""
  req.on("data", (chunk) => { body += chunk })
  req.on("end", () => {
    const h = req.headers
    res.setHeader("content-type", "text/plain")
    res.end([
      "method=" + req.method, "path=" + req.url, "host=" + h.host, "origin=" + h.origin,
      "sec-fetch-site=" + h["sec-fetch-site"], "content-type=" + h["content-type"], "body=" + body,
    ].join("\n") + "\n")
  })
}).listen(8000)'

docker network create "$name" > /dev/null
docker run -d --name "$name-api" --network "$name" --network-alias api "$dev" node -e "$stub" > /dev/null
docker run -d --name "$name-web" --network "$name" -p "127.0.0.1:$port:8080" "$web" > /dev/null
curl -fsS -o /dev/null --retry 30 --retry-delay 1 --retry-connrefused --retry-all-errors "http://localhost:$port/" \
  || fail "the web container does not answer on $port"

# No process in the web container runs as root: every uid of every one, master and workers, i.e.
# the four fields of Uid: (real, effective, saved, filesystem; PR #349 review S-2).
uids=$(MSYS_NO_PATHCONV=1 docker exec "$name-web" sh -c 'for f in /proc/[0-9]*/status; do grep "^Uid:" "$f" 2>/dev/null; done; true' | awk '{print $2; print $3; print $4; print $5}' | sort -u | tr '\n' ' ')
[ -n "$uids" ] || fail "no process found in the web container"
case " $uids" in *" 0 "*) fail "a process in the web container runs as root (uids: $uids)" ;; esac
printf 'web container process uids: %s\n' "$uids"

# MSYS_NO_PATHCONV: Git Bash would rewrite the container path.
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint cat "$web" /usr/share/nginx/html/index.html > "$work/index.html"
grep -q '<div id="root">' "$work/index.html" || fail "the image holds no built index.html"

# The page and paths the app routes itself get index.html; a missing build file is a 404.
for path in / /stocks/TWSE/2330 /news/12345 /no/such/page; do
  curl -fsS "http://localhost:$port$path" > "$work/page.html" || fail "GET $path failed"
  cmp -s "$work/index.html" "$work/page.html" || fail "GET $path is not index.html"
  printf 'GET %s -> index.html\n' "$path"
done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$port/assets/no-such-file.js")
[ "$code" = 404 ] || fail "GET /assets/no-such-file.js returned $code, not 404"
printf 'GET /assets/no-such-file.js -> %s\n' "$code"
asset=$(grep -o '/assets/[^"]*\.js' "$work/index.html" | head -n 1)
curl -fsS -o /dev/null "http://localhost:$port$asset" || fail "GET $asset failed"
printf 'GET %s -> 200\n' "$asset"

# A browser write through the proxy, under both host names the gate admits (#343).
for host in localhost 127.0.0.1; do
  origin="http://$host:$port"
  curl -fsS -X POST "$origin/api/tracking-plans?from=smoke" \
    -H "Origin: $origin" -H 'Sec-Fetch-Site: same-origin' -H 'Content-Type: application/json' \
    --data '{"smoke":true}' > "$work/upstream.txt" || fail "POST through /api failed for $host"
  printf '%s\n' 'method=POST' 'path=/api/tracking-plans?from=smoke' "host=$host:$port" \
    "origin=$origin" 'sec-fetch-site=same-origin' 'content-type=application/json' \
    'body={"smoke":true}' > "$work/expected.txt"
  printf 'upstream saw (browser at %s):\n' "$origin"
  sed 's/^/  /' "$work/upstream.txt"
  diff -u "$work/expected.txt" "$work/upstream.txt" || fail "the upstream did not get the browser's request as sent"
done
printf 'smoke.sh: all checks passed\n'
