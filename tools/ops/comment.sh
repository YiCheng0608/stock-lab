#!/usr/bin/env bash
# The coordinator's comment tool (Issue #440; docs/COORDINATOR.md 無人值守運作): posts one
# comment on an Issue or PR with the coordinator mark as its last line, an HTML comment
# GitHub does not show (coordinator_json.py COORDINATOR_MARK). The event monitor queues a
# marked comment without waking the coordinator (tools/ops/event_queue.py, quiet
# coordinator_comment); every session uses the same GitHub account, so the author cannot
# tell. Engineers and the user comment as before, and those comments wake.
#
# One gh call: POST repos/<repo>/issues/<number>/comments (a PR is an issue there), the body
# as a JSON request on stdin. Prints the comment URL. Exit 64 on bad arguments or an empty
# body (gh is not called), 1 when gh fails or answers without the URL (the comment may then
# be posted: look on GitHub before posting it again), 2 without a Python.
#
# Usage: comment.sh NUMBER --body-file FILE [--python EXE]
#   NUMBER            the Issue or PR number
#   --body-file FILE  the comment, UTF-8; its first line is the comment type (決定：, ...)
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

number="" body_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --body-file | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --body-file) body_file="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      continue
      ;;
    -*) die "unknown argument: $1" 64 ;;
    *)
      [ -z "$number" ] || die "只能給一個 Issue／PR 編號：$1" 64
      number="$1"
      shift
      ;;
  esac
done
case "$number" in '' | *[!0-9]* | 0*) die "要給 Issue 或 PR 編號（正整數）" 64 ;; esac
[ -n "$body_file" ] || die "--body-file 必填" 64
[ -f "$body_file" ] || die "找不到本文檔：$body_file" 64
find_python
cj utf8 "$body_file" || die "本文檔是空的或不是 UTF-8：$body_file" 64

payload="$(cj comment-body "$body_file")" || die "讀不了本文檔：$body_file" 64
# The pipeline's status is gh's: a gh that answered without reading all of stdin succeeded.
out="$(printf '%s\n' "$payload" 2>/dev/null \
  | gh api "repos/$GH_REPO/issues/$number/comments" --method POST --input -)" \
  || die "gh 留言失敗（#$number），沒有回留言 URL" 1
url="$(printf '%s' "$out" | cj get html_url)" \
  || die "gh 的回答沒有 html_url（#$number），留言可能已送出，重送前先到 GitHub 確認" 1
printf '%s\n' "$url"
