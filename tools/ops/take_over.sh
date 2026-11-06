#!/usr/bin/env bash
# A new coordinator's mechanical take-over steps in one run (Issue #534; docs/COORDINATOR.md
# 統籌 session): the handover text names this script instead of listing the steps, so none
# is left to the model's memory. In order, each read back before the next:
#   heartbeat   patrol.sh --heartbeat-only --take-over: the heartbeat names this session
#               and terminal, so the monitor and the wake listener wake this one
#   listener    wake_listener_start.sh (kept when one runs)
#   comment     on #1 through comment.sh: "回報：統籌 session 更換：<handle>／<session>",
#               with the commitments not kept yet
#   row         the one list line under "## 現任統籌" of #1's body replaced (every other
#               byte as it was), then the body read back and compared
#   close       the old coordinator terminal: orca terminal wait --for tui-idle, then
#               orca terminal close (skipped with --no-old-terminal)
#   relisten    wake_listener_start.sh again, then --status: a listener that ran before the
#               take-over (the old terminal's, which ends with it, docs/ops/MONITOR.md)
#               must stop answering within TAKE_OVER_LISTENER_WAIT seconds first, else the
#               step fails; one this run started is kept (skipped with --no-old-terminal)
#   commitments the commitments not kept yet (commit.sh list)
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
#                      commitments)
#                      after a run stopped there; from row on, --comment-url is needed
#   --comment-url URL  the #1 comment an earlier run posted (it printed it)
#   --session-id ID    default $CLAUDE_CODE_SESSION_ID
#   --terminal H       this session's terminal, default $ORCA_TERMINAL_HANDLE
#   --data-dir DIR     default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE       default $STOCK_PYTHON, then this checkout's .venv, then python3
# Exit: 0 every step done; 1 a step failed (see the output); 64 bad arguments, or an
#   OLD_HANDLE the heartbeat (or the record) does not name (nothing done); 2 no Python.
# Test hooks: PATROL_NOW (epoch seconds), TAKE_OVER_LISTENER_WAIT (seconds the old
#   terminal's listener gets to stop after the close, default 10).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

steps_all=(heartbeat listener comment row close relisten commitments)
session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" old="" from=heartbeat comment_url=""
old_given=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --no-old-terminal) [ "$old_given" = 0 ] || die "舊 handle 只能給一個" 64; old_given=1; old=""; shift ;;
    --from | --comment-url | --session-id | --terminal | --data-dir | --python)
      [ $# -ge 2 ] || die "$1 needs a value" 64
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
      out="$(bash "$script_dir/comment.sh" 1 --body-file "$work/comment.md" --python "$python")" \
        || fail comment "comment.sh 失敗：#1 可能已有留言，續跑前先到 GitHub 確認"
      out="$(printf '%s' "$out" | tr -d '\r' | tail -n 1)"
      [[ "$out" =~ $url_re ]] || fail comment "comment.sh 沒有回 #1 的留言連結：$out"
      comment_url="$out"
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
      orca terminal wait --terminal "$old" --for tui-idle --timeout-ms 60000 --json 2>/dev/null \
        | cj satisfied >/dev/null 2>&1 \
        || fail close "舊 terminal $old 未閒置或不存在（orca terminal wait 沒有 satisfied:true），未關"
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
  esac
  done_steps+=("$step")
done
rm -f -- "$record"
report true ""
