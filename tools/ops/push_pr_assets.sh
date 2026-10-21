#!/usr/bin/env bash
# Push a directory of evidence (screenshots, text, JSON) to branch pr-assets/<issue> without
# touching the checkout (Issue #227). The files land under <prefix>/ (default: the
# directory's name). The first push is an orphan commit; later pushes add a child commit
# that keeps the earlier files, so no force push is needed and old links stay valid.
# Prints one Markdown line per file to paste into a PR or Issue comment.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash tools/ops/push_pr_assets.sh --issue <n> --dir <directory> [options]

  --issue <n>        Issue number; the branch is pr-assets/<n>
  --dir <directory>  files to push (recursive; hidden entries are skipped)
  --prefix <path>    path inside the branch; default: the directory's name
  --remote <name>    git remote to push to; default: origin
  --web <url>        repository web URL for the links; default: from the remote's
                     github.com URL
  --dry-run          build the commit and print the links without pushing
  -h, --help         show this help

Run inside the repository checkout. Prints the commit and one Markdown line per file:
images as ![name](...?raw=true), other files as [name](...).
EOF
}

die() {
  printf 'push_pr_assets: %s\n' "$1" >&2
  exit 2
}

issue="" dir="" prefix="" remote="origin" web="" dry_run=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --dry-run) dry_run=1; shift; continue ;;
    --issue | --dir | --prefix | --remote | --web)
      [ $# -ge 2 ] || die "$1 needs a value"
      case "$1" in
        --issue) issue="$2" ;;
        --dir) dir="$2" ;;
        --prefix) prefix="$2" ;;
        --remote) remote="$2" ;;
        --web) web="$2" ;;
      esac
      shift 2
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$issue" in '' | *[!0-9]*) die "--issue must be a number" ;; esac
[ -n "$dir" ] || die "--dir is required"
[ -d "$dir" ] || die "not a directory: $dir"
dir="$(cd "$dir" && pwd)"
[ -n "$prefix" ] || prefix="$(basename "$dir")"
case "$prefix" in
  /* | *..* | *[!A-Za-z0-9._/-]*) die "--prefix may only use letters, digits, '.', '_', '-' and '/', without '..'" ;;
esac
prefix="${prefix%/}"

if [ -z "$web" ]; then
  url="$(git remote get-url "$remote")" || die "no remote named $remote"
  case "$url" in
    https://github.com/*) web="${url#https://github.com/}" ;;
    git@github.com:*) web="${url#git@github.com:}" ;;
    *) die "remote $remote is not on github.com; pass --web" ;;
  esac
  web="https://github.com/${web%.git}"
fi
web="${web%/}"

branch="pr-assets/$issue"
git_dir="$(git rev-parse --absolute-git-dir)"
export GIT_INDEX_FILE="$git_dir/pr-assets-index.$$"
trap 'rm -f "$GIT_INDEX_FILE"' EXIT

parent=""
if git ls-remote --exit-code --heads "$remote" "refs/heads/$branch" >/dev/null 2>&1; then
  git fetch --quiet --no-tags "$remote" "refs/heads/$branch"
  parent="$(git rev-parse FETCH_HEAD)"
  git read-tree "$parent"
else
  git read-tree --empty
fi

files=()
while IFS= read -r -d '' file; do
  files+=("${file#./}")
done < <(cd "$dir" && find . -type f -not -path '*/.*' -print0 | sort -z)
[ ${#files[@]} -gt 0 ] || die "no files in $dir"

for rel in "${files[@]}"; do
  case "$rel" in *[!A-Za-z0-9._/-]*) die "file name needs letters, digits, '.', '_', '-' only: $rel" ;; esac
  # --no-filters: keep the evidence bytes as written (no .gitattributes eol conversion).
  blob="$(git hash-object -w --no-filters -- "$dir/$rel")"
  git update-index --add --cacheinfo "100644,$blob,$prefix/$rel"
done

tree="$(git write-tree)"
message="pr-assets for #$issue: $prefix"
if [ -n "$parent" ]; then
  commit="$(git commit-tree "$tree" -p "$parent" -m "$message")"
else
  commit="$(git commit-tree "$tree" -m "$message")"
fi

if [ "$dry_run" -eq 0 ]; then
  git push --quiet "$remote" "$commit:refs/heads/$branch"
  printf 'pushed %s to %s %s\n' "$commit" "$remote" "$branch"
else
  printf 'dry run: built %s for %s %s (not pushed)\n' "$commit" "$remote" "$branch"
fi
printf '%s\n' "$web/tree/$branch/$prefix"
for rel in "${files[@]}"; do
  link="$web/blob/$branch/$prefix/$rel"
  case "$rel" in
    *.png | *.jpg | *.jpeg | *.gif | *.webp) printf '![%s](%s?raw=true)\n' "$rel" "$link" ;;
    *) printf '[%s](%s)\n' "$rel" "$link" ;;
  esac
done
