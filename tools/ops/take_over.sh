#!/usr/bin/env bash
# A new coordinator's mechanical take-over steps in one run (Issue #534; docs/COORDINATOR.md
# 統籌 session): the handover text (docs/ops/COORDINATOR_REFERENCE.md 開啟命令, #850) names
# this script instead of listing the steps, so none
# is left to the model's memory. The handbook's account of the steps is in
# docs/ops/COORDINATOR_REFERENCE.md 接手腳本的步驟 (#828). In order, each read back before
# the next:
#   heartbeat   patrol.sh --heartbeat-only --take-over: the heartbeat names this session
#               and terminal, so the monitor and the wake listener wake this one
#   listener    wake_listener_start.sh (kept when one runs)
#   comment     on #1 through comment.sh: "回報：統籌 session 更換：<handle>／<session>",
#               with the commitments not kept yet
#   row         the one list line under "## 現任統籌" of #1's body replaced (every other
#               byte as it was), then the body read back and compared
#   close       the old coordinator terminal: orca terminal read prints its last screen and
#               draft (a line more when the draft has text); orca terminal wait --for
#               tui-idle starts in the background, then one short fixed text is sent so
#               a turn ends (#806), and only satisfied:true runs orca terminal close; a
#               read, send or wait that fails closes nothing
#               (skipped with --no-old-terminal)
#   relisten    wake_listener_start.sh again, then --status: a listener that ran before the
#               take-over (the old terminal's, which ends with it, docs/ops/MONITOR.md)
#               must stop answering within TAKE_OVER_LISTENER_WAIT seconds first, else the
#               step fails; one this run started is kept (skipped with --no-old-terminal)
#   commitments the commitments not kept yet (commit.sh list)
#   closed      the Issues and PRs closed in the last 48 hours (#713): every merged PR's
#               merge commit has green CI (the CI workflow's push run) and no worktree or
#               local branch is left (an Issue's task/<n>-* too, and a worktree directory
#               task-<n>-*, detached or not); one line per Issue or PR with something
#               wrong or not read, one for the rest (closed_check in
#               coordinator_json.py). One gh call per page of 100, at most 3 (#787):
#               one report for all; more than 300, a page that cannot be read, or
#               anything else not read prints as "未查完", never as fine. It never
#               fails the run: the coordinator acts on what it prints
#   memory      memory_check.py on the Claude Code memory directory (read only, #705;
#               $STOCK_MEMORY_DIR or the one Claude Code keeps for this repo): a failure
#               names the memory and the check; the coordinator fixes it and goes on
#               --from memory (docs/COORDINATOR.md 記憶)
# A step that fails stops the run: nothing after it is done, and the steps already done are
# printed with the command that goes on from the failed one (--from). The last line is
# JSON: {"ok", "done": [steps], "failed": step or null, "reason", "comment_url"}.
#
# OLD_HANDLE must be the terminal the heartbeat names (another session's), so no other
# terminal is closed. The first step overwrites the heartbeat, so the run keeps what it
# named, and whether a listener ran before it, in <data>/logs/take-over-<session id>.json;
# a run with --from reads that instead and is refused without it. The file goes when every
# step is done.
#
# Usage: take_over.sh OLD_HANDLE|--no-old-terminal [options]
#   OLD_HANDLE         the old coordinator terminal, as the heartbeat names it
#   --no-old-terminal  it no longer exists: the close step is skipped
#   --from STEP        start at STEP (heartbeat, listener, comment, row, close, relisten,
#                      commitments, closed, memory)
#                      after a run stopped there; from row on, --comment-url is needed
#   --comment-url URL  the #1 comment an earlier run posted (it printed it)
#   --session-id ID    default $CLAUDE_CODE_SESSION_ID
#   --terminal H       this session's terminal, default $ORCA_TERMINAL_HANDLE
#   --data-dir DIR     default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE       default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --closed-only      run the closed step alone and nothing else: no handle, no session,
#                      nothing written; only --python goes with it (exit 0, or 2
#                      without Python)
# Exit: 0 every step done; 1 a step failed (see the output); 64 bad arguments, or an
#   OLD_HANDLE the heartbeat (or the record) does not name (nothing done); 2 no Python.
# Test hooks: PATROL_NOW (epoch seconds), TAKE_OVER_LISTENER_WAIT (seconds the old
#   terminal's listener gets to stop after the close, default 10), TAKE_OVER_CLOSED_HOURS
#   (the closed step's window, default 48), TAKE_OVER_CLOSE_WAIT (seconds the close step
#   waits for the old terminal to turn idle after its text, default 600: the old session
#   may compact first), TAKE_OVER_CLOSE_SETTLE (seconds between starting that wait and
#   sending the text, default 2).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

steps_all=(heartbeat listener comment row close relisten commitments closed memory)
session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" old="" from=heartbeat comment_url=""
old_given=0 closed_only=0 take_over_args=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --closed-only) closed_only=1; shift ;;
    --no-old-terminal) [ "$old_given" = 0 ] || die "舊 handle 只能給一個" 64; old_given=1; old=""; shift ;;
    --from | --comment-url | --session-id | --terminal | --data-dir | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      [ "$1" = --python ] || take_over_args=1
      case "$1" in
        --from) from="$2" ;;
        --comment-url) comment_url="$2" ;;
        --session-id) session_id="$2" ;;
        --terminal) handle="$2" ;;
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
      esac
      shift 2
      ;;
    -*) die "unknown argument: $1" 64 ;;
    *)
      [ "$old_given" = 0 ] || die "舊 handle 只能給一個：$1" 64
      # An empty handle would read as --no-old-terminal (PR #535 review 1).
      [ -n "$1" ] || die "舊 handle 是空字串；舊 terminal 已不存在時明寫 --no-old-terminal" 64
      old_given=1
      old="$1"
      shift
      ;;
  esac
done

# closed_check: the closed step's report (see the header). Prints; always returns 0.
closed_check() {
  local hours="${TAKE_OVER_CLOSED_HOURS:-48}" since dir query wt="" br="" rc=0
  local page=0 cursor="" where="" failed="" n search
  local -a after=()
  since="$(date -u -d "@$((${PATROL_NOW:-$(date -u +%s)} - hours * 3600))" +%Y-%m-%dT%H:%M:%SZ)"
  dir="$(mktemp -d)" || { echo "關閉單核對：未查完（建不了暫存目錄）"; return 0; }
  git -C "$repo_root" worktree list --porcelain >"$dir/worktrees" && wt="$dir/worktrees"
  git -C "$repo_root" for-each-ref --format='%(refname:short)' refs/heads/ >"$dir/branches" \
    && br="$dir/branches"
  query="$(cj closed-query)"
  # Sorted by creation time, which never changes: without a sort the search is by best
  # match, ties fall in any order from one call to the next and a page repeats one the
  # page before had (PR #788 review). One closed while the pages are read still moves
  # the others along: closed-check's count then says 未查完.
  search="repo:$GH_REPO is:closed closed:>=$since sort:created-asc"
  # Page after page by the search cursor (#787): closed-next prints none after the last
  # page there is or the last one read (CLOSED_PAGES), and closed-check says 未查完 when
  # the search goes on. A page that cannot be read leaves the whole report unread: the
  # pages before it are not taken as complete.
  while :; do
    page=$((page + 1))
    # The first page keeps its words of before paging; later ones name the page.
    [ "$page" -gt 1 ] && where="第 $page 頁 "
    # ${after[@]+...}: an empty array is unbound under set -u before bash 4.4.
    if ! gh api graphql -f q="$search" -f query="$query" ${after[@]+"${after[@]}"} \
      >"$dir/page.$page"; then
      failed="${where}gh api graphql 失敗"
      break
    fi
    rc=0
    cursor="$(cj closed-next "$page" <"$dir/page.$page")" || rc=$?
    case "$rc" in
      0) ;;
      3) failed="${where}GraphQL 的回答沒有 data.search"; break ;;
      4) failed="${where}說有下一頁卻沒有游標"; break ;;
      # A Python error: its traceback is on stderr.
      *) failed="${where}closed-next 失敗，exit $rc"; break ;;
    esac
    [ -n "$cursor" ] || break
    after=(-f after="$cursor")
  done
  if [ -n "$failed" ]; then
    echo "關閉單核對：未查完（${failed}；gh 呼叫 $page 次）"
  else
    rc=0
    # Page by page in order, not by file name (page.10 sorts before page.2).
    for ((n = 1; n <= page; n++)); do cat "$dir/page.$n"; done \
      | cj closed-check "$since" "$wt" "$br" || rc=$?
    case "$rc" in
      0) ;;
      3) echo "關閉單核對：未查完（GraphQL 的回答沒有 data.search；gh 呼叫 $page 次）" ;;
      # A Python error: its traceback is on stderr.
      *) echo "關閉單核對：未查完（closed-check 失敗，exit $rc；gh 呼叫 $page 次）" ;;
    esac
  fi
  rm -rf -- "$dir"
  return 0
}
if [ "$closed_only" = 1 ]; then
  [ "$old_given" = 0 ] && [ "$take_over_args" = 0 ] \
    || die "--closed-only 只能和 --python 一起用（不要舊 handle、--from、--comment-url、--session-id、--terminal、--data-dir）" 64
  find_python
  closed_check
  exit 0
fi
[ "$old_given" = 1 ] || die "要給舊統籌的 terminal handle，或 --no-old-terminal" 64
case "$session_id" in '' | *[!A-Za-z0-9_-]*) die "--session-id（或 CLAUDE_CODE_SESSION_ID）必填，只能有英數、_、-" 64 ;; esac
case "$handle" in '' | -* | *[!A-Za-z0-9_-]*) die "--terminal（或 ORCA_TERMINAL_HANDLE）必填，只能有英數、_、-，不能以 - 開頭" 64 ;; esac
if [ -n "$old" ]; then
  case "$old" in -* | *[!A-Za-z0-9_-]*) die "舊 handle 只能有英數、_、-，不能以 - 開頭：$old" 64 ;; esac
  [ "$old" != "$handle" ] || die "舊 handle 是這個 session 自己的 terminal：$old" 64
fi
start=-1
for i in "${!steps_all[@]}"; do [ "${steps_all[$i]}" = "$from" ] && start=$i; done
[ "$start" -ge 0 ] || die "--from 要是 ${steps_all[*]} 其中之一：$from" 64
url_re='^https://github\.com/YiCheng0608/stock-lab/issues/1#issuecomment-([0-9]+)$'
if [ "$start" -gt 2 ]; then
  [[ "$comment_url" =~ $url_re ]] || die "--from $from 要給前一次貼的 #1 留言連結 --comment-url（…/issues/1#issuecomment-<id>）" 64
elif [ -n "$comment_url" ]; then
  die "--comment-url 只在 --from row 之後用；comment 步驟會貼新的留言" 64
fi
find_python
logs="$data_dir/logs"
now="${PATROL_NOW:-$(date -u +%s)}"
heartbeat="$logs/coordinator-heartbeat.json"
handle_re='^[A-Za-z0-9_][A-Za-z0-9_-]*$'

# The old handle must be the terminal the heartbeat names, so no other terminal (an
# engineer's waiting for a review) is closed (PR #535 review 2). The heartbeat is
# overwritten by the first step, so what it named is kept in the run's record, which a
# run going on with --from reads instead; the record goes when every step is done.
record="$logs/take-over-$session_id.json"
rec_old="" rec_listener=""
if [ -f "$record" ]; then
  rec_old="$(cj get old_handle <"$record" 2>/dev/null)" || rec_old=""
  rec_listener="$(cj get listener <"$record" 2>/dev/null)" || rec_listener=""
elif [ "$start" = 0 ]; then
  if [ -f "$heartbeat" ] && [ "$(cj get session_id <"$heartbeat" 2>/dev/null)" != "$session_id" ]; then
    rec_old="$(cj get terminal_handle <"$heartbeat" 2>/dev/null)" || rec_old=""
  fi
elif [ -n "$old" ]; then
  die "續跑（--from $from）要有前一次記下的舊 handle，找不到 $record；未做任何步驟" 64
fi
[[ "$rec_old" =~ $handle_re ]] || rec_old=""
case "$rec_listener" in running | started) ;; *) rec_listener="" ;; esac
if [ -n "$old" ] && [ "$old" != "$rec_old" ]; then
  die "給的舊 handle $old 不是心跳記的舊統籌 terminal（${rec_old:-心跳沒有記別的 session 的 terminal}），未做任何步驟；照心跳給，舊 terminal 已不存在時用 --no-old-terminal" 64
fi
write_record() {
  local tmp="$record.tmp.$$"
  printf '{"session_id":"%s","old_handle":"%s","listener":"%s","written_at":"%s"}\n' \
    "$session_id" "$rec_old" "$rec_listener" "$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)" >"$tmp" \
    && mv -f "$tmp" "$record" && [ "$(cj get old_handle <"$record" 2>/dev/null)" = "$rec_old" ] \
    || { rm -f "$tmp"; return 1; }
}

work="$(mktemp -d)" || die "建不了暫存目錄" 2
trap 'rm -rf -- "$work"' EXIT

done_steps=() reason=""
report() {
  local ok="$1" failed="$2" list="" s
  for s in "${done_steps[@]+"${done_steps[@]}"}"; do list+="${list:+,}$(json_str "$s")"; done
  if [ "$ok" = true ]; then
    echo "take_over：全部完成：${done_steps[*]}"
  else
    echo "take_over：已完成：${done_steps[*]:-（無）}；失敗：$failed（$reason）" >&2
    local again="bash tools/ops/take_over.sh ${old:---no-old-terminal} --from $failed"
    [ -n "$comment_url" ] && again+=" --comment-url $comment_url"
    echo "take_over：修好原因後續跑：$again" >&2
  fi
  printf '{"ok":%s,"done":[%s],"failed":%s,"reason":%s,"comment_url":%s}\n' "$ok" "$list" \
    "$([ -n "$failed" ] && json_str "$failed" || echo null)" \
    "$([ -n "$reason" ] && json_str "$reason" || echo null)" \
    "$([ -n "$comment_url" ] && json_str "$comment_url" || echo null)"
}
fail() {
  reason="$2"
  report false "$1"
  exit 1
}

listener_up() { bash "$script_dir/wake_listener_start.sh" --status >/dev/null 2>&1; }
listener_wait="${TAKE_OVER_LISTENER_WAIT:-10}"
close_wait="${TAKE_OVER_CLOSE_WAIT:-600}" close_settle="${TAKE_OVER_CLOSE_SETTLE:-2}"
for n in "$close_wait" "$close_settle"; do
  case "$n" in '' | *[!0-9]*) die "TAKE_OVER_CLOSE_WAIT、TAKE_OVER_CLOSE_SETTLE 要是秒數（整數）：$n" 64 ;; esac
done
[ "$close_wait" -gt 0 ] || die "TAKE_OVER_CLOSE_WAIT 要大於 0" 64
# listener_gone: the listener that ran before the take-over (the old terminal's) stops with
# that terminal; wait for it before starting a new one, else the start finds the dying one
# answering and starts nothing. Fails when it still answers after the wait: then it may be
# no listener of the old terminal, or one that ends later and leaves none (PR #535 review 3).
listener_gone() {
  local waited=0
  while listener_up; do
    [ "$waited" -lt "$listener_wait" ] || return 1
    sleep 1
    waited=$((waited + 1))
  done
}

for step in "${steps_all[@]:$start}"; do
  case "$step" in
    heartbeat)
      write_record || fail heartbeat "寫不了接手記錄 $record"
      bash "$script_dir/patrol.sh" --heartbeat-only --take-over --session-id "$session_id" \
        --terminal "$handle" --data-dir "$data_dir" --python "$python" \
        || fail heartbeat "patrol.sh --heartbeat-only 失敗"
      [ "$(cj get session_id <"$logs/coordinator-heartbeat.json" 2>/dev/null)" = "$session_id" ] \
        && [ "$(cj get terminal_handle <"$logs/coordinator-heartbeat.json" 2>/dev/null)" = "$handle" ] \
        || fail heartbeat "心跳檔讀回不是這個 session"
      ;;
    listener)
      # Whether a listener ran before this run (the old terminal's, most likely) or this
      # run starts one in this session's terminal decides what relisten waits for.
      if listener_up; then rec_listener=running; else rec_listener=started; fi
      write_record || fail listener "寫不了接手記錄 $record"
      bash "$script_dir/wake_listener_start.sh" || fail listener "wake_listener_start.sh 失敗"
      listener_up || fail listener "wake_listener_start.sh 之後 --status 仍說 listener 沒在跑"
      ;;
    comment)
      list="$("$python" -X utf8 "$script_dir/commitments.py" list "$logs" "$now")" \
        || fail comment "讀不了承諾檔"
      {
        printf '回報：統籌 session 更換：%s／%s\n\n' "$handle" "$session_id"
        printf -- '- %s（台北）接手；' "$(TZ=UTC date -u -d "@$((now + 8 * 3600))" '+%Y-%m-%d %H:%M')"
        if [ -n "$old" ]; then printf '前任 terminal `%s`。\n' "$old"; else printf '前任 terminal 已不存在。\n'; fi
        printf -- '- 由 `tools/ops/take_over.sh` 執行：心跳、wake listener、本留言、本文的現任統籌、關前任 terminal。\n'
        printf -- '- %s\n' "$(printf '%s\n' "$list" | head -n 1)"
        printf '%s\n' "$list" | tail -n +2
      } >"$work/comment.md" || fail comment "寫不了留言本文"
      posted="$(bash "$script_dir/comment.sh" 1 --body-file "$work/comment.md" --python "$python")" \
        || fail comment "comment.sh 失敗：#1 可能已有留言，續跑前先到 GitHub 確認"
      posted="$(printf '%s' "$posted" | tr -d '\r' | tail -n 1)"
      [[ "$posted" =~ $url_re ]] || fail comment "comment.sh 沒有回 #1 的留言連結：$posted"
      comment_url="$posted"
      echo "#1 留言：$comment_url"
      ;;
    row)
      [[ "$comment_url" =~ $url_re ]] || fail row "沒有 #1 留言連結"
      cid="${BASH_REMATCH[1]}"
      checkout="$(native "$repo_root")" || checkout="$repo_root"
      at="$(date -u -d "@$now" +%Y-%m-%dT%H:%MZ)"
      row="- terminal \`$handle\`（管理 checkout \`$checkout\`），session \`$session_id\`；$at 接手（[$cid]($comment_url)）。"
      gh api "repos/$GH_REPO/issues/1" >"$work/issue.json" || fail row "讀不了 #1 本文"
      cj coordinator-row "$row" <"$work/issue.json" >"$work/body.json" 2>"$work/row.err" \
        || fail row "$(tr -d '\r' <"$work/row.err" | head -n 1)；#1 本文未修改"
      gh api "repos/$GH_REPO/issues/1" --method PATCH --input "$work/body.json" >/dev/null \
        || fail row "改 #1 本文失敗（可能已改，續跑前先到 GitHub 確認）"
      gh api "repos/$GH_REPO/issues/1" >"$work/readback.json" || fail row "讀回 #1 本文失敗"
      cj same-body "$work/body.json" <"$work/readback.json" || fail row "#1 本文讀回與送出的不同"
      echo "#1 本文現任統籌：$row"
      ;;
    close)
      if [ -z "$old" ]; then
        done_steps+=("close:skipped")
        continue
      fi
      # What the user may have left in the old terminal goes to this one's screen first
      # (docs/COORDINATOR.md 自動換手機制 4): its last screen and the draft, the unsent text
      # in Orca's input box, which the send below takes away (#806).
      orca terminal read --terminal "$old" --screen --limit 20 --json >"$work/old.json" 2>/dev/null \
        && cj ok <"$work/old.json" >/dev/null 2>&1 \
        || fail close "讀不了舊 terminal $old（orca terminal read 失敗，可能已不存在），未送短訊、未關；orca terminal list --json 確認它已不存在時，改跑 bash tools/ops/take_over.sh --no-old-terminal --from close --comment-url $comment_url"
      echo "舊 terminal $old 的最後畫面："
      cj get result.terminal.tail <"$work/old.json" 2>/dev/null | "$python" -X utf8 -c '
import json, sys
sys.stdout.reconfigure(newline="\n")
for line in json.load(sys.stdin): print("  |", line)' 2>/dev/null || echo "  （讀不到畫面）"
      draft="$(cj get result.terminal.draft <"$work/old.json" 2>/dev/null | tr -d '\r')" || draft=""
      if [ -z "$draft" ]; then
        echo "舊 terminal $old 的 draft：（空）"
      else
        echo "舊 terminal $old 的 draft："
        printf '%s\n' "$draft" | sed 's/^/  | /'
        echo "提示：舊 terminal 的輸入框有還沒送出的字（上面的 draft），可能是使用者留給舊統籌的話；關掉後讀不到，照 docs/COORDINATOR.md「自動換手機制」第 4 點處理"
      fi
      # A terminal already at its prompt before the take-over turns idle no more, and the
      # wait timed out (2026-11-14, 2026-11-16): one short turn ends in an idle (#806).
      # tui-idle sees only a change to idle, so the wait starts first, in the background,
      # and the text goes after close_settle seconds: a reply that ends before a wait
      # started after the send would leave nothing to see (PR #831 review 1). The wait
      # gets close_wait seconds: the old session may compact or think long first (review
      # 2). The old handle is the one the heartbeat named, never this session's terminal
      # (checked before any step).
      orca terminal wait --terminal "$old" --for tui-idle --timeout-ms "$((close_wait * 1000))" \
        --json >"$work/wait.json" 2>/dev/null &
      wait_pid=$!
      sleep "$close_settle"
      out="$(orca terminal send --terminal "$old" --text "新統籌 $handle 已接手，要關閉這個 terminal。只回覆收到，不要呼叫工具。" \
        --enter --json 2>/dev/null)" && [ "$(printf '%s' "$out" | cj get result.send.accepted 2>/dev/null)" = true ] \
        || {
          kill "$wait_pid" 2>/dev/null
          wait "$wait_pid" 2>/dev/null
          fail close "對舊 terminal $old 送短訊失敗（orca terminal send 沒有 accepted:true），未關"
        }
      wait "$wait_pid"
      cj satisfied <"$work/wait.json" >/dev/null 2>&1 \
        || fail close "送短訊後 $close_wait 秒內舊 terminal $old 未回到閒置（orca terminal wait 沒有 satisfied:true），未關"
      orca terminal close --terminal "$old" --json 2>/dev/null | cj ok >/dev/null 2>&1 \
        || fail close "orca terminal close $old 失敗"
      echo "已關舊 terminal：$old"
      ;;
    relisten)
      if [ -z "$old" ]; then
        done_steps+=("relisten:skipped")
        continue
      fi
      # A listener this run started lives in this terminal and is kept. One that ran before
      # must stop with the old terminal first; a run going on --from relisten does not wait
      # again: whoever runs it checked the listener that still answers.
      if [ "$rec_listener" != started ] && [ "$from" != relisten ]; then
        listener_gone || fail relisten "關掉舊 terminal $listener_wait 秒後，接手前就在跑的 wake listener 仍在回應：它可能不是舊 terminal 啟動的，或還沒結束，結束後就沒有 listener。查埠的占用者（docs/ops/MONITOR.md），確認後續跑（不再等待）"
      fi
      bash "$script_dir/wake_listener_start.sh" || fail relisten "wake_listener_start.sh 失敗"
      listener_up || fail relisten "wake_listener_start.sh 之後 --status 仍說 listener 沒在跑"
      ;;
    commitments)
      "$python" -X utf8 "$script_dir/commitments.py" list "$logs" "$now" \
        || fail commitments "讀不了承諾檔"
      ;;
    closed) closed_check ;;
    memory)
      if ! memory_check; then
        printf '%s\n' "$memory_out" >&2
        fail memory "記憶檢查失敗：${memory_failures:-$memory_out}；改好記憶再續跑"
      fi
      printf '%s\n' "$memory_out"
      ;;
  esac
  done_steps+=("$step")
done
rm -f -- "$record"
report true ""
