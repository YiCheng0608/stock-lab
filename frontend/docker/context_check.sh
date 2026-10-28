#!/usr/bin/env bash
# Checks frontend/.dockerignore (#334): secrets, installed dependencies and build output stay
# out of the image at any depth, and .env examples go in. CI's frontend-image job runs it;
# locally (Git Bash or Linux):
#
#   bash frontend/docker/context_check.sh
#
# Copies frontend/ (its own node_modules and dist left out) to a temporary directory, plants
# files there, builds the dev target from that copy and looks for each file in the image.
# The dev target holds the whole context (COPY . .), and the build stage starts from it.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
image=stock-lab-web-context-check:$$
work=$(mktemp -d)

cleanup() {
  docker rmi -f "$image" > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

fail() {
  printf 'context_check.sh: %s\n' "$1" >&2
  exit 1
}

tar -C "$here" --exclude=./node_modules --exclude=./dist -cf - . | tar -C "$work" -xf -

excluded=(
  .env .env.local .env.production.local src/zz/.env src/zz/.env.local docker/zz/.env.test
  node_modules/zz-planted/index.js src/zz/node_modules/x.js
  dist/planted.js src/zz/dist/y.js
  .vite/planted src/zz/.vite/z
  planted.tsbuildinfo src/zz/a.tsbuildinfo
  planted.log src/zz/b.log
)
kept=(.env.example .env.local.example src/zz/.env.example)
for file in "${excluded[@]}" "${kept[@]}"; do
  mkdir -p "$work/$(dirname "$file")"
  printf 'planted by context_check.sh\n' > "$work/$file"
done

docker build -q --target dev -t "$image" "$work" > /dev/null || fail "docker build --target dev failed"

# MSYS_NO_PATHCONV: Git Bash would rewrite the container paths.
found=$(MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh "$image" -c \
  'for f in "$@"; do if [ -e "/app/frontend/$f" ]; then echo "$f"; fi; done' sh "${excluded[@]}" "${kept[@]}")
status=0
for file in "${excluded[@]}"; do
  if grep -qxF "$file" <<< "$found"; then printf 'in the image, should be excluded: %s\n' "$file"; status=1
  else printf 'excluded: %s\n' "$file"; fi
done
for file in "${kept[@]}"; do
  if grep -qxF "$file" <<< "$found"; then printf 'kept: %s\n' "$file"
  else printf 'missing from the image, should be kept: %s\n' "$file"; status=1; fi
done
[ "$status" = 0 ] || fail "frontend/.dockerignore lets a planted file through or drops an example"
printf 'context_check.sh: all checks passed\n'
