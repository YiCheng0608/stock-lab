#!/usr/bin/env bash
# Coordinator patrol (Issue #282, #316, #401; docs/COORDINATOR.md 無人值守運作; its output in
# docs/ops/COORDINATOR_REFERENCE.md patrol 的輸出), in
# the handbook's order: write the heartbeat, read this session's compaction count and
# handoff marker, then the event queue the monitor (tools/ops/monitor.sh) keeps: its
# heartbeat, its last open PR snapshot, the schedule jobs' latest log lines as it read them,
# then the unanswered questions (a 提問 comment no 決定 comment links to, #401) and the
# events not handled yet. Prints a short summary. PRs, CI and new comments come from the
# queue: GitHub is polled by the monitor only (#316 AC-4). The one gh call is the questions'
# GraphQL query, as whether a question is answered needs every open thread's comments as
# they are now (closed Issues, which 決定 links which), which the queue's events do not hold.
#
# Then the commitments not kept yet (commit.sh, #534), past-due ones marked. When this
# session reached the handoff condition (2 compactions, or the context of its last model
# call above STOCK_CONTEXT_LIMIT, #710), the last line says so again and the exit code is
# 10, so neither a grep of the event lines nor `| tail -1` misses it (#534: the header
# line was filtered out and a coordinator went on for 6 compactions).
#
# The context comes from this session's transcript (session_cost.py context): found by
# session id under $CLAUDE_CONFIG_DIR/projects, then $HOME/.claude/projects, or named by
# --transcript / STOCK_TRANSCRIPT. A transcript not found or not understood is a warning
# only (#710 決定 6877357244); from the 3rd patrol in a row without it the line before the
# last says so.
#
# Files written: <data>/logs/coordinator-heartbeat.json (through a temporary file in the
# same directory and mv), <data>/logs/compactions/<session>.context-misses (the patrols in
# a row the context could not be read; removed once it is), and with --done one line in
# <data>/logs/events-done.jsonl.
#
# The slots (#727): after the questions, slots.py prints 名額：已用 N／3 with each task
# counted or not and the comment it was decided on, read from the same GraphQL answer
# (so still one gh call) and the local `git worktree list` with `git status` of each task
# worktree. With a slot free and a 待辦 task to dispatch, the last line is
# 名額空缺 M 個，請派工：#n and the exit 11; in the daily window (台北 21:30～23:30) or
# with this session's handoff marker it is printed only (in the daily window the exit is
# then 0, or 12 when a #1 comment is missing, below), and when the handoff condition holds
# it goes before the handoff line (exit 10). GitHub not read (gh failed,
# --max-gh 0): every task is counted as 判定不了 and no vacancy is claimed. A task whose
# engineer terminal the monitor last saw at a permission or trust menu (monitor-state.json
# engineer_menus, #873) is tagged 工程師停在確認框 on both lines.
#
# #1's body (#807, docs/ops/COORDINATOR_REFERENCE.md 決策落地的比對), from the same answer (its body is the
# one extra field, its latest 100 comments are already there): above
# STOCK_GOVERNANCE_BODY_LIMIT bytes the header says "#1 本文 N 位元組（K KB），超過上限 M"
# (a hint only). The 決定 and 統籌承諾 comments and the ones without the coordinator mark
# whose id is neither in the body nor up to its archive line (歸檔：) and that no covered
# comment names (本文：不同步, PR #810 review 6912088904) are listed before the last lines
# (coordinator_json.governance_check), with the header line "#1 漏同步：N 則", and the last
# line says so with exit 12, after the handoff's 10 and the slots' 11 (the lines of each
# printed all the same); with this session's handoff marker printed only (exit 0).
# GitHub not read: "#1 漏同步：未查完", never 0.
#
# Exit: 0; 10 the handoff condition holds (whether or not every part of the listing could
#   be read, such as the questions 未查完); 2 a file could not be written or read back, a
#   --done failed; 3 another session's heartbeat was kept; 11 a slot is free and a 待辦
#   task can be dispatched (not in the daily window, no handoff marker); 12 a comment of
#   #1 is missing from its body (no handoff marker); 64 bad arguments.
#
# Usage: patrol.sh [options]
#   --session-id ID   default $CLAUDE_CODE_SESSION_ID
#   --terminal H      default $ORCA_TERMINAL_HANDLE
#   --done X          mark events handled before listing the rest: X is an event id, or
#                     a seq for every event not done up to it (pending or quiet, #440);
#                     repeatable
#   --max-gh N        at most N gh calls, default 1 (the questions and slots), 2 with
#                     --overview; 0 prints the questions as not read (未查完)
#   --overview [N...] also print the overview page (overview.py, #804) before the last
#                     lines: the index (what a new coordinator reads), or with Issue or
#                     PR numbers after it the full sections of those (read before acting
#                     on one; decision 6914347432). Built from the same GraphQL answer,
#                     plus one more call only when a thread has more comments than it
#                     read (the oldest ones, decision 6913246451); what is still not
#                     read is printed as 未查完
#   --take-over       overwrite another session's heartbeat younger than an hour (a new
#                     coordinator taking over without the old one's handoff marker)
#   --heartbeat-only  write the heartbeat and stop (take_over.sh's first step)
#   --transcript PATH this session's transcript, default $STOCK_TRANSCRIPT, then found
#                     by session id
#   --data-dir DIR    default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --python EXE      default $STOCK_PYTHON, then this checkout's .venv, then python3
# Environment: STOCK_CONTEXT_LIMIT, the context in tokens above which the handoff
#   condition holds, default 450000 (docs/ops/COORDINATOR_REFERENCE.md 換手偵測);
#   STOCK_GOVERNANCE_BODY_LIMIT, #1's body in UTF-8 bytes above which the header says so,
#   default 14336 (14 KB).
# Test hook: PATROL_NOW (epoch seconds).
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

session_id="${CLAUDE_CODE_SESSION_ID:-}" handle="${ORCA_TERMINAL_HANDLE:-}" max_gh=default take_over=0 done_args=()
heartbeat_only=0 transcript="${STOCK_TRANSCRIPT:-}" overview=0 overview_numbers=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --take-over) take_over=1; shift; continue ;;
    --overview)
      overview=1
      shift
      while [ $# -gt 0 ] && [[ "$1" =~ ^#?[0-9]+$ ]]; do overview_numbers+=("${1#\#}"); shift; done
      continue ;;
    --heartbeat-only) heartbeat_only=1; shift; continue ;;
    --session-id | --terminal | --done | --max-gh | --data-dir | --python | --transcript)
      [ $# -ge 2 ] || die "$1 needs a value" 64
      case "$1" in
        --session-id) session_id="$2" ;;
        --terminal) handle="$2" ;;
        --done) done_args+=("$2") ;;
        --max-gh) max_gh="$2" ;;
        --data-dir) data_dir="$2" ;;
        --python) python="$2" ;;
        --transcript) transcript="$2" ;;
      esac
      shift 2
      continue
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
done
[ "$max_gh" != default ] || max_gh=$((1 + overview))
case "$max_gh" in '' | *[!0-9]*) die "--max-gh must be a number" 64 ;; esac
context_limit="${STOCK_CONTEXT_LIMIT:-450000}"
case "$context_limit" in '' | *[!0-9]* | 0*) die "STOCK_CONTEXT_LIMIT 要是正整數（token 數）：$context_limit" 64 ;; esac
gov_limit="${STOCK_GOVERNANCE_BODY_LIMIT:-14336}"
case "$gov_limit" in '' | *[!0-9]* | 0*) die "STOCK_GOVERNANCE_BODY_LIMIT 要是正整數（位元組數）：$gov_limit" 64 ;; esac
case "$session_id" in '' | *[!A-Za-z0-9_-]*) die "--session-id（或 CLAUDE_CODE_SESSION_ID）必填，只能有英數、_、-" 64 ;; esac
case "$handle" in '' | -* | *[!A-Za-z0-9_-]*) die "--terminal（或 ORCA_TERMINAL_HANDLE）必填，只能有英數、_、-，不能以 - 開頭" 64 ;; esac
iso_re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
find_python

now="${PATROL_NOW:-$(date -u +%s)}"
iso() { epoch_fmt "$1"; }
logs="$data_dir/logs"
heartbeat="$logs/coordinator-heartbeat.json"
[ -d "$logs" ] || die "資料目錄沒有 logs/：$logs" 2

# 1. heartbeat. Another session's heartbeat younger than an hour (the handbook's liveness
# window) is kept unless that session left a handoff marker or --take-over is given
# (#283 review L7). A heartbeat that cannot be read (not JSON, no session id, a bad
# written_at) is treated the same: kept unless --take-over (#283 review L3).
prev_session="" prev_at=""
if [ -e "$heartbeat" ]; then
  prev_session="$(cj get session_id <"$heartbeat" 2>/dev/null)" || prev_session=""
  prev_at="$(cj get written_at <"$heartbeat" 2>/dev/null)" || prev_at=""
  prev_epoch=""
  [[ "$prev_at" =~ $iso_re ]] && prev_epoch="$(iso_epoch "$prev_at")"
  case "$prev_session" in '' | *[!A-Za-z0-9_-]*) prev_epoch="" ;; esac
  if [ "$take_over" = 0 ]; then
    [ -n "$prev_epoch" ] || die "心跳檔讀不懂（session_id 或 written_at 缺少或格式不對），視同另一個 session 的心跳，未覆寫；確定接手才加 --take-over：$heartbeat" 3
    if [ "$prev_session" != "$session_id" ] && [ ! -f "$logs/handoff-$prev_session.json" ] \
      && [ $((now - prev_epoch)) -lt 3600 ]; then
      die "心跳檔屬於另一個統籌 session $prev_session（${prev_at}，$(((now - prev_epoch) / 60)) 分鐘前），它沒有換手標記，未覆寫；確定接手才加 --take-over" 3
    fi
  fi
fi
written_at="$(iso "$now")"
tmp="$logs/.coordinator-heartbeat.json.tmp.$$"
if ! printf '{"session_id":"%s","terminal_handle":"%s","written_at":"%s"}' "$session_id" "$handle" "$written_at" >"$tmp" \
  || ! mv -f "$tmp" "$heartbeat"; then
  rm -f "$tmp"
  die "寫不進心跳檔：$heartbeat" 2
fi
[ "$(cj get written_at <"$heartbeat")" = "$written_at" ] || die "心跳檔讀回不符：$heartbeat" 2
echo "心跳 $written_at session=$session_id terminal=$handle（$heartbeat）"
[ "$heartbeat_only" = 0 ] || exit 0

# 2. compaction count and handoff marker
# The count is the main conversation's compactions in this session's transcript (#811,
# session_cost.py compactions): the PreCompact hook gets the parent's session id for a
# subagent's compaction too, so its .count has those. The hook's count only when the
# transcript cannot be read, said so on the line.
count_file="$logs/compactions/$session_id.count"
hook_count=0
[ -f "$count_file" ] && hook_count="$(tr -dc '0-9' <"$count_file")"
hook_count="${hook_count:-0}"
# Strip leading zeros so 08 is not read as octal.
hook_count="$((10#$hook_count))"
if [ -n "$transcript" ]; then
  compact_out="$("$python" -X utf8 "$script_dir/session_cost.py" compactions --transcript "$transcript" 2>&1)"
else
  compact_out="$("$python" -X utf8 "$script_dir/session_cost.py" compactions --session-id "$session_id" 2>&1)"
fi
compact_rc=$?
if [ "$compact_rc" = 0 ] && [[ "$compact_out" =~ ^([0-9]+)\ (.*)$ ]]; then
  count="$((10#${BASH_REMATCH[1]}))"
  count_note=""
  if [ "$hook_count" -gt "$count" ]; then
    count_note="（hook 記 $hook_count 次，含子代理）"
  elif [ "$hook_count" != "$count" ]; then
    count_note="（hook 記 $hook_count 次）"
  fi
else
  count="$hook_count"
  count_note="（hook 計數，可能含子代理；紀錄檔未讀到：${compact_out:-session_cost.py exit $compact_rc}）"
fi
handoff_due=0
if [ "$count" -ge 2 ]; then
  handoff_due=1
  echo "壓縮 $count 次$count_note：已達換手條件（手冊「統籌 session」自動換手機制）"
else
  echo "壓縮 $count 次$count_note"
fi
# The context of this session's last model call (#710).
misses_file="$logs/compactions/$session_id.context-misses"
context_due=0 context="" misses=0
if [ -n "$transcript" ]; then
  context_out="$("$python" -X utf8 "$script_dir/session_cost.py" context --transcript "$transcript" 2>&1)"
else
  context_out="$("$python" -X utf8 "$script_dir/session_cost.py" context --session-id "$session_id" 2>&1)"
fi
context_rc=$?
if [ "$context_rc" = 0 ] && [[ "$context_out" =~ ^([0-9]+)\ (.*)$ ]]; then
  context="${BASH_REMATCH[1]}" context_path="${BASH_REMATCH[2]}"
  rm -f "$misses_file"
  pct="$(awk -v a="$context" -v b="$context_limit" 'BEGIN { printf "%.0f%%", 100 * a / b }')"
  if [ "$context" -gt "$context_limit" ]; then
    context_due=1
    echo "context：$context（門檻 $context_limit，$pct）：已達換手條件（$context_path）"
  else
    echo "context：$context（門檻 $context_limit，$pct）（$context_path）"
  fi
else
  [ -f "$misses_file" ] && misses="$(tr -dc '0-9' <"$misses_file")"
  misses="$((10#${misses:-0} + 1))"
  mkdir -p "$logs/compactions" 2>/dev/null
  printf '%s\n' "$misses" >"$misses_file" 2>/dev/null || true
  echo "context：未讀到（${context_out:-session_cost.py exit $context_rc}；連續 $misses 次）"
fi
marker="$logs/handoff-$session_id.json"
if [ -f "$marker" ]; then echo "換手標記存在：$marker（換手中，不合併、不派工、不留言）"; else echo "換手標記：無"; fi

# 3. the event queue: mark what was handled, then the monitor and what is left
eq() { "$python" -X utf8 "$script_dir/event_queue.py" "$@"; }
if [ ${#done_args[@]} -gt 0 ]; then
  eq done "$logs" "$now" "$session_id" "${done_args[@]}" || die "--done 失敗（見上一行）" 2
fi
# The monitor's heartbeat, open PRs and job log lines from its last poll: in the
# scheduler container the job logs are in the volume, out of this shell's reach (#338).
eq status "$logs" "$now"
# The wake listener the scheduler container's monitor wakes this session through (#338).
bash "$script_dir/wake_listener_start.sh" --status 2>&1
# Questions nobody answered (#401): one GraphQL call reads the open Issues and PRs with
# their comments; coordinator_json.py decides which 提問 has no 決定 linking to it.
# The same call reads what the slots need (#727): open PRs' heads, commits and CI, the
# board's 待辦 with blocked-by and body; slots.py decides.
# The questions come first (PR #737 review 6882741345): when slots.py cannot give its
# query, the questions' own query is sent instead and the slots are not judged. gh exits 1
# on a partial answer (data and errors, such as a project it may not read) with the data
# on stdout: the questions are read from it and slots.py claims no dispatchable task.
gh_calls=0 out="" slots_query=1
if ! query="$("$python" -X utf8 "$script_dir/slots.py" query 2>/dev/null)" || [ -z "$query" ]; then
  slots_query=0
  query="$(cj questions-query)"
fi
if [ "$gh_calls" -lt "$max_gh" ]; then
  gh_calls=$((gh_calls + 1))
  out="$(gh api graphql -f owner="${GH_REPO%%/*}" -f name="${GH_REPO#*/}" -f query="$query")"
  gh_rc=$?
  partial=""
  if [ "$gh_rc" != 0 ]; then
    if printf '%s' "$out" | cj get data.repository >/dev/null 2>&1; then
      partial="（gh exit $gh_rc，GitHub 回部分錯誤，提問照讀到的判定）"
    else
      out=""
    fi
  fi
  if [ -n "$out" ] && lines="$(printf '%s' "$out" | cj questions "$now")"; then
    n="$(printf '%s\n' "$lines" | grep -c '^#')"
    echo "未回覆的提問：$n 則$(printf '%s\n' "$lines" | grep -q '^未查完' && echo '（未查完）')$partial"
    [ -n "$lines" ] && printf '%s\n' "$lines" | sed 's/^/  /'
  else
    out=""
    echo "未回覆的提問：未查完（gh api graphql 失敗）"
  fi
else
  echo "未回覆的提問：未查完（gh 呼叫已達上限 $max_gh）"
fi
# The overview's backfill (#804 decision 6913246451): one more call, only when a thread has
# more comments than the answer above holds; for the overview only (the questions and
# the slots read the answer above). Not made or failed: the page says 未查完.
overview_dir="" backfill_file="" backfill_note=""
if [ "$overview" = 1 ]; then
  overview_dir="$(mktemp -d 2>/dev/null)" || overview_dir=""
  trap '[ -n "$overview_dir" ] && rm -f -- "$overview_dir"/* && rmdir -- "$overview_dir"' EXIT
  backfill_query=""
  [ -n "$out" ] && backfill_query="$(printf '%s' "$out" | "$python" -X utf8 "$script_dir/overview.py" backfill-query ${overview_numbers[@]+"${overview_numbers[@]}"})"
  if [ -n "$backfill_query" ]; then
    if [ -z "$overview_dir" ]; then
      backfill_note="建不了暫存目錄"
    elif [ "$gh_calls" -ge "$max_gh" ]; then
      backfill_note="gh 呼叫已達上限 $max_gh，沒有補查"
    else
      gh_calls=$((gh_calls + 1))
      backfill_file="$overview_dir/backfill.json"
      if ! gh api graphql -f owner="${GH_REPO%%/*}" -f name="${GH_REPO#*/}" -f query="$backfill_query" >"$backfill_file"; then
        backfill_note="補查的 gh api graphql 失敗"
        printf '%s' "$(cat "$backfill_file" 2>/dev/null)" | cj get data.repository >/dev/null 2>&1 \
          && backfill_note="補查的 gh api graphql 回部分錯誤"
      fi
    fi
  fi
fi
echo "gh 呼叫：$gh_calls／上限 $max_gh"
# #1's body against its comments (#807), from the same answer: the header says the body's
# size above the limit (a hint only) and how many comments are missing from it; those are
# held for the end, with exit 12 after the handoff's 10 and the slots' 11.
gov_missing=""
if [ -n "$out" ]; then
  gov_lines="$(printf '%s' "$out" | cj governance "$gov_limit")"
  gov_rc=$?
  case "$gov_rc" in
    0 | 12)
      printf '%s\n' "$gov_lines" | grep -v '^  '
      gov_missing="$(printf '%s\n' "$gov_lines" | grep '^  ')" ;;
    *) echo "#1 漏同步：未查完（coordinator_json.py governance exit $gov_rc）" ;;
  esac
else
  echo "#1 漏同步：未查完（GitHub 沒讀到）"
fi
# The slots (#727): the local task worktrees and whether each is clean, with the answer
# above (none when gh was not called or failed: every task is 判定不了 and counted). The
# vacancy line is held for the end, so `| tail -1` sees it (exit 11, after the handoff's 10).
vacancy="" vacancy_rc=0
slot_dir="$(mktemp -d 2>/dev/null)" || slot_dir=""
if [ "$slots_query" = 0 ]; then
  echo "名額：判定不了（slots.py query 失敗，提問改用 questions-query 讀；名額沒判定）"
  [ -n "$slot_dir" ] && rmdir "$slot_dir" 2>/dev/null
elif [ -z "$slot_dir" ]; then
  echo "名額：判定不了（建不了暫存目錄）"
else
  wt=""
  : >"$slot_dir/status"
  if git -C "$repo_root" worktree list --porcelain >"$slot_dir/worktrees" 2>/dev/null; then
    wt="$slot_dir/worktrees"
    while IFS= read -r line; do
      case "$line" in "worktree "*) path="${line#worktree }" ;; esac
      case "$line" in "branch refs/heads/task/"*)
        if st="$(git -C "$path" status --porcelain 2>/dev/null)"; then
          [ -z "$st" ] && state=clean || state=dirty
        else
          state=unknown
        fi
        printf '%s\t%s\n' "$state" "$path" >>"$slot_dir/status" ;;
      esac
    done < <(tr -d '\r' <"$wt")
  fi
  slot_lines="$(printf '%s' "$out" | "$python" -X utf8 "$script_dir/slots.py" report "$now" "$wt" "$slot_dir/status" "$logs/monitor-state.json")"
  slot_rc=$?
  if [ -n "$overview_dir" ]; then
    # The overview reads the same listing (#804); the EXIT trap removes it.
    [ -n "$wt" ] && mv -f "$wt" "$overview_dir/worktrees" && wt="$overview_dir/worktrees"
    mv -f "$slot_dir/status" "$overview_dir/status" 2>/dev/null
  fi
  rm -f "$slot_dir/worktrees" "$slot_dir/status"; rmdir "$slot_dir" 2>/dev/null
  case "$slot_rc" in
    0 | 11)
      last="$(printf '%s\n' "$slot_lines" | tail -n 1)"
      case "$last" in
        名額空缺*請派工*)
          vacancy="$last" vacancy_rc="$slot_rc"
          printf '%s\n' "$slot_lines" | sed '$d' ;;
        *) printf '%s\n' "$slot_lines" ;;
      esac ;;
    *) echo "名額：判定不了（slots.py exit $slot_rc）" ;;
  esac
fi
eq pending "$logs"
# Commitments kept across sessions (#534): what the coordinators promised and did not do yet.
"$python" -X utf8 "$script_dir/commitments.py" list "$logs" "$now" \
  || echo "未兌現的承諾：讀不了承諾檔（$logs/commitments.jsonl）"
# The overview page (#804), before the last lines so `| tail -1` still sees them.
if [ "$overview" = 1 ]; then
  ov_wt="" ov_status=""
  if [ "$slots_query" = 1 ] && [ -n "$overview_dir" ] && [ -f "$overview_dir/worktrees" ]; then
    ov_wt="$overview_dir/worktrees" ov_status="$overview_dir/status"
  fi
  printf '%s' "$out" | "$python" -X utf8 "$script_dir/overview.py" page "$now" "$ov_wt" "$ov_status" \
    "$logs" "$backfill_file" "$backfill_note" ${overview_numbers[@]+"${overview_numbers[@]}"} \
    || echo "現況頁：印不出來（overview.py 失敗，見上一行）"
fi
echo "其餘依手冊：處理上面的未處理事件（PR 的 CI 與合併、未回覆的提問、名額空缺就派工）與到期的承諾，處理完以 --done <seq>、commit.sh done <id> 標記；monitor 停擺時看 logs/monitor.log"
if [ "$misses" -ge 3 ]; then
  echo "context 已連續 $misses 次讀不到：換手只剩壓縮次數一個條件，請查紀錄檔位置（見上方 context 行）"
fi
# The comments missing from #1's body (#807): before the last lines, whichever ends it.
gov_n=0
if [ -n "$gov_missing" ]; then
  gov_n="$(printf '%s\n' "$gov_missing" | grep -c .)"
  echo "#1 本文沒有的留言 $gov_n 則（時間、id、第一行）："
  printf '%s\n' "$gov_missing"
fi
# Last, so no filter of the lines above hides it (#534).
if [ "$handoff_due" = 1 ] || [ "$context_due" = 1 ]; then
  [ -n "$vacancy" ] && echo "$vacancy（換手條件成立，不派工，交給新統籌）"
  why=""
  [ "$handoff_due" = 1 ] && why="已壓縮 $count 次（門檻 2 次）"
  [ "$context_due" = 1 ] && why="${why:+$why、}context $context 超過門檻 $context_limit"
  if [ -f "$marker" ]; then
    echo "已達換手條件：本 session $why，換手標記已寫，換手中：不合併、不派工、不留言，等新統籌在 #1 留言（patrol exit 10）"
  else
    echo "已達換手條件：本 session $why，現在照 docs/COORDINATOR.md「統籌 session」自動換手機制換手（patrol exit 10）"
  fi
  exit 10
fi
# A free slot with a task to dispatch (#727): after the handoff, since a coordinator
# handing off dispatches nothing; a handoff marker or the daily window prints it only.
if [ -n "$vacancy" ]; then
  if [ -f "$marker" ]; then
    echo "$vacancy（換手中，不派工，只印出）"
    exit 0
  fi
  if [ "$vacancy_rc" = 11 ]; then
    echo "$vacancy（patrol exit 11）"
    exit 11
  fi
  echo "$vacancy"
fi
# A decision not in #1's body (#807): after the handoff and the slots; a handoff marker
# prints it only (a coordinator handing off does not edit #1).
if [ "$gov_n" -gt 0 ]; then
  if [ -f "$marker" ]; then
    echo "#1 漏同步 $gov_n 則（換手中，只印出）"
    exit 0
  fi
  echo "#1 漏同步 $gov_n 則：照 docs/COORDINATOR.md「決策落地」補進 #1 本文的決策索引（patrol exit 12）"
  exit 12
fi
