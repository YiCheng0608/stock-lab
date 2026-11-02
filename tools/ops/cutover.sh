#!/usr/bin/env bash
# The one-off switch from Windows Task Scheduler to the scheduler container (Issue #342, parent
# #331; docs/OPERATIONS.md §6.9), and its rollback. Run by the coordinator from a checkout other
# than the release checkout (the master management checkout), in Git Bash, in Taipei daytime
# away from the even-hour news and 18:30-21:30 (#1 6582767651, point 7).
#
#   cutover.sh [--dry-run] --tag <tag> [options]        the switch
#   cutover.sh rollback [--dry-run] [options]           back to Task Scheduler
#
# Switch, in this order (each step's command is printed; --dry-run prints them and stops after
# the checks, changing nothing):
#   checks  refuse, changing nothing, when: the env file (STOCK_ENV_FILE, default .env in the
#           release checkout) lacks a value for a required key or has ANTHROPIC_API_KEY or
#           ANTHROPIC_AUTH_TOKEN (keys are matched by grep -q; no value is read into this
#           script or printed); the release checkout has uncommitted changes, or already holds
#           #333 (d408ae7) while a task is still enabled (its jobs end with exit 69, so the
#           schedule has stopped silently: decision 9 of #342); a task is running; the
#           project's stock-data volume exists (the volume is created here, by compose); the
#           data directory has no stock.db; the pre-docker commit holds #333, or a pre-docker
#           branch points elsewhere.
#           The release checkout's tasks pull master (-GitPull), so they are disabled before
#           feat/docker reaches master (docs/OPERATIONS.md §6.9); step 2 then only reads back.
#   1 pre-docker  the release checkout gets branch pre-docker (no checkout) at --pre-docker,
#           default its HEAD, which must not hold #333; its upstream is itself, so
#           `git pull --ff-only` there stays up to date after a rollback (decision 2, review H1).
#   2 disable   Disable-ScheduledTask for each task; then wait until none runs and no process
#           of the release checkout's .venv is left (no writer of stock.db).
#   3 snapshot  tools/ops/copy_db.py: stock.db by the SQLite backup API into <work>/db (never a
#           bare copy of a file with WAL, OPERATIONS §2.1).
#   4 volume    `compose run -d` of a helper (the api service, root, sleep) with this checkout's
#           compose file: compose creates <project>_stock-data with its labels; image
#           <project>-backend:cutover, built when missing.
#   5 copy      docker cp: the snapshot to /data/stock.db, raw/ to /data/raw (decision 1: the DB
#           keeps its Windows payload_path; app.raw_paths maps it), logs/ to /data/logs.
#   6 chown     chown -R 1000:1000 /data (docker cp writes root's files; the image runs as uid
#           1000; decision 3, review M1).
#   7 verify    as uid 1000 in the helper: integrity_check ok and every table's row count equal
#           to the snapshot's (tools/ops/cutover_db.py), the raw and logs file counts equal to
#           the host's, the owner of /data, stock.db, raw and logs is 1000:1000, a file can be
#           written; /data/logs/cutover.json records it (rollback copies back what is newer).
#   8 helper    the helper container is removed (the volume stays).
#   9 start     tools/ops/deploy.sh <tag> (checkout of the tag, build, record, up, read-back,
#           comment on #1). --no-deploy (rehearsals only) starts compose with this checkout's
#           compose file and the helper image instead (api and scheduler).
#  10 readback  compose ps, `serve ready` in the scheduler's log, one `job news --trigger manual
#           --skip-news-llm` in the scheduler (a real write), and the owner of what it wrote.
# A failure after step 1 exits 3 with the steps done; `rollback` undoes them.
#
# Rollback (decision 2): checks (the pre-docker branch, the volume and its stock.db, the tasks
# disabled), then
#   1 stop      docker stop every running container of the project (no down: the volume stays).
#   2 snapshot  a helper on the scheduler's image (uid 1000): copy_db.py of /data/stock.db into
#           the helper, docker cp to <work>/rollback/stock.db; raw files newer than
#           /data/logs/cutover.json to the host raw directory (existing files are kept), newer
#           logs to <work>/rollback/logs.
#   3 paths     the copy's /data/raw/... payload_path rows become the host raw directory's path
#           (pre-docker code reads them as stored); integrity_check ok.
#   4 install   the data directory's stock.db, -wal and -shm move to backups/pre-rollback-<UTC>/,
#           the copy becomes stock.db.
#   5 checkout  the release checkout: git checkout pre-docker; git pull --ff-only must exit 0.
#   6 enable    Enable-ScheduledTask for each task; --start-news then runs the news task once
#           and waits for its result.
#
# Options:
#   --pre-docker C     the commit of the pre-docker branch; default the checkout's HEAD
#   --checkout DIR     release checkout; default $STOCK_RELEASE_DIR, then $HOME/stock-lab-release
#   --project NAME     compose project; default $STOCK_COMPOSE_PROJECT, then stock-lab
#   --data-dir DIR     host data directory; default $STOCK_DATA_DIR, then $HOME/stock-lab-data
#   --work-dir DIR     snapshots; default <data dir>-cutover (outside the data directory)
#   --task-path PATH   Task Scheduler folder; default \stock-lab\  (rehearsals use a test one)
#   --tasks LIST       task names, comma-separated; default daily,news,watchdog
#   --env-file PATH    the env file to check and hand to compose (STOCK_ENV_FILE)
#   --require-keys L   keys that must have a value; default
#                      CLAUDE_CODE_OAUTH_TOKEN,GH_TOKEN,STOCK_WAKE_TOKEN,STOCK_MONITOR,STOCK_COORDINATION_DIR
#   --web-port N, --api-port N   for compose (deploy.sh passes them on)
#   --no-comment       deploy.sh without the #1 comment (rehearsal)
#   --no-deploy        step 9 without deploy.sh (rehearsal; image <project>-backend:cutover)
#   --no-write-check   step 10 without the news job
#   --start-news       rollback: Start-ScheduledTask news once and wait for its result
#   --wait-timeout SEC for tasks to end after disabling them, and for the news task; default 900
#   --python EXE       host Python; default $STOCK_PYTHON, then this checkout's .venv, then python3
#   --powershell EXE   default powershell.exe (tests pass a fake)
# Prints a JSON line at the end. Exit 0 done (or dry run fine); 1 refused, nothing changed;
# 3 a step failed, the steps done are listed; 2/64 bad setup or arguments.
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$script_dir/coordinator_lib.sh"

# The merge of #333 into feat/docker: from it on job.py runs on Linux only. CUTOVER_PR333 is
# for the tests (backend/tests/test_cutover.py), whose repositories cannot hold that commit.
PR333="${CUTOVER_PR333:-d408ae723978cb601493b0b065aefe81bf04f894}"
mode=switch dry=0 tag="" deploy=1 comment=1 write_check=1 start_news=0 pre_commit=""
checkout="${STOCK_RELEASE_DIR:-$HOME/stock-lab-release}" project="${STOCK_COMPOSE_PROJECT:-stock-lab}"
data_dir="${STOCK_DATA_DIR:-$HOME/stock-lab-data}" work_dir="" task_path='\stock-lab\'
tasks=daily,news,watchdog env_file="" web_port="" api_port="" wait_timeout=900
require_keys=CLAUDE_CODE_OAUTH_TOKEN,GH_TOKEN,STOCK_WAKE_TOKEN,STOCK_MONITOR,STOCK_COORDINATION_DIR
powershell="${CUTOVER_POWERSHELL:-powershell.exe}"
[ "${1:-}" = rollback ] && { mode=rollback; shift; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "${BASH_SOURCE[0]}"; exit 0 ;;
    --dry-run) dry=1 ;;
    --no-deploy) deploy=0 ;;
    --no-comment) comment=0 ;;
    --no-write-check) write_check=0 ;;
    --start-news) start_news=1 ;;
    --tag | --pre-docker | --checkout | --project | --data-dir | --work-dir | --task-path | --tasks | --env-file | \
      --require-keys | --web-port | --api-port | --wait-timeout | --python | --powershell)
      [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value" 64
      case "$1" in
        --tag) tag="$2" ;;
        --pre-docker) pre_commit="$2" ;;
        --checkout) checkout="$2" ;;
        --project) project="$2" ;;
        --data-dir) data_dir="$2" ;;
        --work-dir) work_dir="$2" ;;
        --task-path) task_path="$2" ;;
        --tasks) tasks="$2" ;;
        --env-file) env_file="$2" ;;
        --require-keys) require_keys="$2" ;;
        --web-port) web_port="$2" ;;
        --api-port) api_port="$2" ;;
        --wait-timeout) wait_timeout="$2" ;;
        --python) python="$2" ;;
        --powershell) powershell="$2" ;;
      esac
      shift 2
      continue
      ;;
    *) die "unknown argument: $1" 64 ;;
  esac
  shift
done
if [ "$mode" = switch ]; then
  [ "$deploy" = 0 ] || [ -n "$tag" ] || die "usage: cutover.sh [--dry-run] --tag <tag> [options]（演練可用 --no-deploy）" 64
  [ "$deploy" = 1 ] || [ -z "$tag" ] || die "--tag 與 --no-deploy 只能擇一" 64
fi
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "不是合法的 compose project 名稱：$project" 64
[[ "$wait_timeout" =~ ^[1-9][0-9]*$ ]] || die "--wait-timeout 要是正整數秒：$wait_timeout" 64
[[ "$tasks" =~ ^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$ ]] || die "--tasks 要是逗號分隔的工作名稱：$tasks" 64
[[ "$task_path" =~ ^\\([A-Za-z0-9_-]+\\)+$ ]] || die "--task-path 要像 \\stock-lab\\：$task_path" 64
[[ "$require_keys" =~ ^[A-Z_][A-Z0-9_]*(,[A-Z_][A-Z0-9_]*)*$ ]] || die "--require-keys 要是逗號分隔的 key：$require_keys" 64
for port in "$web_port" "$api_port"; do
  [ -z "$port" ] || [[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] || die "不是埠號：$port" 64
done
find_python

checkout="$(cd "$checkout" 2>/dev/null && pwd)" || die "發佈 checkout 不存在：$checkout" 2
git -C "$checkout" rev-parse --git-dir >/dev/null 2>&1 || die "不是 git checkout：$checkout" 2
checkout_native="$(native "$checkout")" || die "發佈 checkout 不是本機的絕對路徑：$checkout" 2
within "$script_dir" "$checkout" && die "這支腳本在發佈 checkout 裡；請從另一個 checkout（master 管理 checkout）執行" 2
data_dir="$(cd "$data_dir" 2>/dev/null && pwd)" || die "資料目錄不存在：$data_dir" 2
data_native="$(native "$data_dir")" || die "資料目錄不是本機的絕對路徑：$data_dir" 2
[ -n "$work_dir" ] || work_dir="$data_dir-cutover"
work_native="$(native "$work_dir")" || die "--work-dir 不是本機的絕對路徑：$work_dir" 2
within "$work_native" "$data_native" && die "--work-dir 不能在資料目錄裡：$work_dir" 2
# A dry run creates nothing, not even the work directory.
[ "$dry" = 1 ] || mkdir -p "$work_dir" || die "無法建立 --work-dir：$work_dir" 2
[ -n "$env_file" ] || env_file="$checkout_native/.env"
command -v docker >/dev/null 2>&1 || die "找不到 docker" 2
"$powershell" -NoProfile -NonInteractive -Command 'exit 0' >/dev/null 2>&1 || die "無法執行 PowerShell：$powershell" 2

dk() { MSYS_NO_PATHCONV=1 docker "$@"; }
ps1() { "$powershell" -NoProfile -NonInteractive -Command "$1"; }
volume="${project}_stock-data"
helper="${project}-cutover"
image="${project}-backend:cutover"
unset COMPOSE_FILE COMPOSE_PROFILES WEB_PORT API_PORT STOCK_MONITOR STOCK_COORDINATION_DIR
[ -z "$web_port" ] || export WEB_PORT="$web_port"
[ -z "$api_port" ] || export API_PORT="$api_port"
export STOCK_ENV_FILE="$env_file"
# The helper and a --no-deploy start use this checkout's compose file: the volume's name and
# labels depend on the project only.
compose_here() {
  COMPOSE_PROJECT_NAME="$project" STOCK_RELEASE_TAG=cutover \
    dk compose -p "$project" -f "$(native "$repo_root")/docker-compose.yml" "$@"
}
dk compose version >/dev/null 2>&1 || die "docker compose 無法執行（Docker Desktop 沒有開？）" 2

steps=()
note() { printf 'cutover: %s\n' "$*" >&2; }
plan() { # plan <step> <description>: what the step does, and in a dry run nothing else.
  note "[$1] $2"
  steps+=("$1")
}
finish() { # finish <status> [reason]
  local list="" s
  for s in "${steps[@]+"${steps[@]}"}"; do list="$list${list:+, }$(json_str "$s")"; done
  printf '{"mode": %s, "status": %s, "project": %s, "steps": [%s], "reason": %s}\n' \
    "$(json_str "$mode")" "$(json_str "$1")" "$(json_str "$project")" "$list" "$(json_str "${2:-}")"
}
refuse() { finish refused "$1"; die "拒絕：$1" 1; }
fail() {
  finish failed "$1"
  [ "$mode" = switch ] && note "已完成的步驟見 steps；回退：bash tools/ops/cutover.sh rollback（同一組選項）"
  die "中斷：$1" 3
}

# --- Task Scheduler -------------------------------------------------------------------------
task_list=() ps_names=""
IFS=, read -r -a task_list <<<"$tasks"
for name in "${task_list[@]}"; do ps_names="$ps_names${ps_names:+,}'$name'"; done
# One line per task: <name> <State> (Ready, Running, Disabled, ...).
task_states() {
  ps1 "\$ErrorActionPreference = 'Stop'; foreach (\$n in @($ps_names)) { \$t = Get-ScheduledTask -TaskPath '$task_path' -TaskName \$n; \$t.TaskName + ' ' + \$t.State }" \
    | tr -d '\r'
}
states="$(task_states)" || die "讀不到工作排程器的工作（$task_path：$tasks）" 2
state_of() { printf '%s\n' "$states" | awk -v n="$1" '$1 == n { print $2; exit }'; }
any_state() { printf '%s\n' "$states" | awk -v s="$1" '$2 == s { found = 1 } END { exit !found }'; }
any_enabled() { printf '%s\n' "$states" | awk '$2 != "Disabled" { found = 1 } END { exit !found }'; }
for name in "${task_list[@]}"; do
  [ -n "$(state_of "$name")" ] || die "工作排程器沒有 $task_path$name" 2
done
# Processes of the release checkout's venv: a job Task Scheduler started.
venv_win="${checkout_native//\//\\}\\.venv\\"
writers() {
  ps1 "Get-Process | Where-Object { \$_.Path -and \$_.Path.StartsWith('$venv_win', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { [string]\$_.Id + ' ' + \$_.Path }" \
    | tr -d '\r'
}
wait_quiet() { # until no task runs and no venv process is left, or wait_timeout
  local deadline=$((SECONDS + wait_timeout)) left
  while :; do
    states="$(task_states)" || return 1
    left="$(writers)" || return 1
    any_state Running || [ -n "$left" ] || return 0
    [ "$SECONDS" -lt "$deadline" ] || { note "仍在執行：$(printf '%s ' $states) ${left}"; return 1; }
    sleep 5
  done
}

# --- the checkout ---------------------------------------------------------------------------
dirty="$(git -C "$checkout" status --porcelain | tr -d '\r')" || die "讀不到發佈 checkout 的 git status" 2
head="$(git -C "$checkout" rev-parse HEAD | tr -d '\r')" || die "讀不到發佈 checkout 的 HEAD" 2
has333=0
git -C "$checkout" merge-base --is-ancestor "$PR333" HEAD >/dev/null 2>&1 && has333=1
pre_docker="$(git -C "$checkout" rev-parse --verify -q refs/heads/pre-docker | tr -d '\r')"
# Where pre-docker goes: --pre-docker, else HEAD; never a commit with #333 in it.
pre_target="$head"
if [ -n "$pre_commit" ]; then
  pre_target="$(git -C "$checkout" rev-parse --verify -q "$pre_commit^{commit}" | tr -d '\r')" \
    || die "發佈 checkout 沒有 --pre-docker 的 commit：$pre_commit" 2
fi
pre_has333=0
git -C "$checkout" merge-base --is-ancestor "$PR333" "$pre_target" >/dev/null 2>&1 && pre_has333=1

volume_exists() { [ -n "$(dk volume ls -q --filter "name=^${volume}\$" | tr -d '\r')" ]; }
project_running() { dk ps -q --filter "label=com.docker.compose.project=$project" | tr -d '\r'; }

# =============================================================================================
if [ "$mode" = switch ]; then
  # --- checks (nothing changes) ---
  missing="" forbidden=""
  if [ -f "$env_file" ]; then
    IFS=, read -r -a keys <<<"$require_keys"
    for key in "${keys[@]}"; do
      grep -Eq "^[[:space:]]*(export[[:space:]]+)?$key[[:space:]]*=[[:space:]]*[^[:space:]#]" "$env_file" \
        || missing="$missing${missing:+,}$key"
    done
    for key in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; do
      grep -Eq "^[[:space:]]*(export[[:space:]]+)?$key[[:space:]]*=[[:space:]]*[^[:space:]#]" "$env_file" \
        && forbidden="$forbidden${forbidden:+,}$key"
    done
  else
    missing="(沒有 env file：$env_file)"
  fi
  [ -z "$missing" ] || refuse "env file 缺少有值的 key：$missing"
  [ -z "$forbidden" ] || refuse "env file 不能設 $forbidden（news-llm 與 candidate-notes 會拒跑）"
  [ -z "$dirty" ] || refuse "發佈 checkout 有未 commit 的改動：$checkout"
  if [ "$has333" = 1 ] && any_enabled; then
    refuse "發佈 checkout 已含 #333（${PR333:0:7}，HEAD ${head:0:9}）而工作排程器仍啟用：Windows 的 job 會以 69 結束、排程無聲停擺；先停用工作再查原因"
  fi
  any_state Running && refuse "工作排程器有工作在執行（$(printf '%s ' $states)）；等它結束再切換"
  [ "$pre_has333" = 0 ] \
    || refuse "pre-docker 要停在 #333 之前（${pre_target:0:9} 已含 ${PR333:0:7}）；以 --pre-docker <commit> 指定，例如 0f99fea"
  [ -z "$pre_docker" ] || [ "$pre_docker" = "$pre_target" ] \
    || refuse "pre-docker branch 已存在且不在 ${pre_target:0:9}（是 ${pre_docker:0:9}）"
  volume_exists && refuse "volume $volume 已存在；切換只寫入 compose 新建的空 volume"
  [ -z "$(project_running)" ] || refuse "project $project 已有容器在跑"
  [ -f "$data_dir/stock.db" ] || refuse "資料目錄沒有 stock.db：$data_dir"
  [ -d "$data_dir/raw" ] || refuse "資料目錄沒有 raw/：$data_dir"
  [ -d "$data_dir/logs" ] || refuse "資料目錄沒有 logs/：$data_dir"
  [ "$deploy" = 0 ] || [ -f "$script_dir/deploy.sh" ] || die "找不到 deploy.sh" 2

  db_copy="$work_native/db/stock.db"
  plan pre-docker "git -C $checkout_native branch pre-docker ${pre_target:0:9}; branch.pre-docker.remote=. merge=refs/heads/pre-docker"
  plan disable "Disable-ScheduledTask -TaskPath '$task_path' -TaskName ${tasks//,/ ／ }；等到沒有工作在跑、沒有 $venv_win 的程序"
  plan snapshot "$python tools/ops/copy_db.py --src $data_native/stock.db --dest $work_native/db"
  plan volume "docker compose -p $project run -d --no-deps --name $helper --user root --entrypoint sleep api infinity（建立 $volume；image $image）"
  plan copy "docker cp $db_copy $helper:/data/stock.db；docker cp $data_native/raw/. $helper:/data/raw；docker cp $data_native/logs/. $helper:/data/logs"
  plan chown "docker exec -u root $helper chown -R 1000:1000 /data"
  plan verify "uid 1000：integrity_check、各表列數＝快照、raw／logs 檔數＝主機、/data 擁有者 1000:1000、寫入一個檔；/data/logs/cutover.json"
  plan helper "docker rm -f $helper（volume 保留）"
  if [ "$deploy" = 1 ]; then
    plan start "bash tools/ops/deploy.sh $tag --checkout $checkout_native --project $project${env_file:+ --env-file $env_file}$([ "$comment" = 0 ] && printf ' --no-comment')"
  else
    plan start "（演練）docker compose -p $project -f $(native "$repo_root")/docker-compose.yml up -d --no-build --wait api scheduler（image cutover）"
  fi
  plan readback "docker compose ps；scheduler 的 serve ready；$([ "$write_check" = 1 ] && printf 'job news --trigger manual --skip-news-llm；')新檔擁有者"
  if [ "$dry" = 1 ]; then
    note "乾跑：以上步驟都沒有執行；工作排程器：$(printf '%s ' $states)"
    finish dry-run
    exit 0
  fi
  steps=()

  # 1 pre-docker
  if [ -z "$pre_docker" ]; then
    git -C "$checkout" branch pre-docker "$pre_target" || fail "建立 pre-docker branch 失敗"
  fi
  git -C "$checkout" config branch.pre-docker.remote . \
    && git -C "$checkout" config branch.pre-docker.merge refs/heads/pre-docker \
    || fail "設定 pre-docker 的 upstream 失敗"
  steps+=(pre-docker)
  # 2 disable
  for name in "${task_list[@]}"; do
    ps1 "Disable-ScheduledTask -TaskPath '$task_path' -TaskName '$name' -ErrorAction Stop | Out-Null" \
      || fail "停用 $task_path$name 失敗"
  done
  steps+=(disable)
  wait_quiet || fail "停用後 $wait_timeout 秒內仍有工作或 venv 程序在跑"
  any_enabled && fail "停用後讀回仍有工作啟用：$(printf '%s ' $states)"
  # 3 snapshot
  out="$("$python" -X utf8 "$script_dir/copy_db.py" --src "$data_native/stock.db" --dest "$work_native/db" --force)" \
    || fail "copy_db.py 失敗"
  printf '%s\n' "$out" >&2
  "$python" -X utf8 "$script_dir/cutover_db.py" counts "$db_copy" >"$work_native/db/counts.json" \
    || fail "讀不到快照的列數"
  steps+=(snapshot)
  # 4 volume (compose creates it with the helper)
  dk image inspect "$image" >/dev/null 2>&1 || compose_here build api >&2 || fail "build $image 失敗"
  compose_here run -d --no-deps --no-build --name "$helper" --user root --entrypoint sleep api infinity >&2 \
    || fail "compose run 輔助容器失敗"
  steps+=(volume)
  # 5 copy
  dk exec "$helper" mkdir -p /data/raw /data/logs || fail "建立 /data/raw、/data/logs 失敗"
  dk cp "$db_copy" "$helper:/data/stock.db" || fail "docker cp stock.db 失敗"
  dk cp "$data_native/raw/." "$helper:/data/raw" || fail "docker cp raw/ 失敗"
  dk cp "$data_native/logs/." "$helper:/data/logs" || fail "docker cp logs/ 失敗"
  steps+=(copy)
  # 6 chown
  dk exec -u root "$helper" chown -R 1000:1000 /data || fail "chown /data 失敗"
  steps+=(chown)
  # 7 verify
  dk exec -i -u 1000 "$helper" python -X utf8 - counts /data/stock.db <"$script_dir/cutover_db.py" \
    | tr -d '\r' >"$work_native/db/counts-volume.json" || fail "讀不到 volume 裡 stock.db 的列數"
  diff_out="$("$python" -X utf8 "$script_dir/cutover_db.py" compare "$work_native/db/counts.json" "$work_native/db/counts-volume.json")" \
    || fail "volume 的 stock.db 與快照不同：$diff_out"
  for sub in raw logs; do
    host_n="$(find "$data_dir/$sub" -type f | wc -l | tr -d ' ')"
    vol_n="$(dk exec -u 1000 "$helper" sh -c "find /data/$sub -type f | wc -l" | tr -d '\r ')"
    if [ "$host_n" = "$vol_n" ]; then
      note "$sub 檔數 $vol_n（與主機相同）"
    elif [ "$sub" = logs ]; then
      # The coordinator keeps writing its heartbeat and compaction logs on the host.
      note "警告：logs 檔數不同（主機 $host_n、volume $vol_n）：統籌的檔可能剛好有新增，job 日誌不受影響"
    else
      fail "$sub 檔數不同：主機 $host_n、volume $vol_n"
    fi
  done
  owners="$(dk exec -u 1000 "$helper" stat -c '%u:%g %n' /data /data/stock.db /data/raw /data/logs | tr -d '\r')" \
    || fail "讀不到 /data 的擁有者"
  printf '%s\n' "$owners" >&2
  [ -z "$(printf '%s\n' "$owners" | awk '$1 != "1000:1000"')" ] || fail "/data 有不是 1000:1000 的項目"
  record="{\"time\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"source\": $(json_str "$data_native"), \"head\": \"$head\", \"tasks\": $(json_str "$task_path$tasks")}"
  printf '%s\n' "$record" | dk exec -i -u 1000 "$helper" sh -c 'cat > /data/logs/cutover.json' \
    || fail "uid 1000 寫不了 /data/logs/cutover.json"
  steps+=(verify)
  # 8 helper
  dk rm -f "$helper" >/dev/null || fail "移除輔助容器 $helper 失敗"
  steps+=(helper)
  # 9 start
  if [ "$deploy" = 1 ]; then
    args=("$tag" --checkout "$checkout_native" --project "$project" --env-file "$env_file")
    [ -z "$web_port" ] || args+=(--web-port "$web_port")
    [ -z "$api_port" ] || args+=(--api-port "$api_port")
    [ "$comment" = 1 ] || args+=(--no-comment)
    bash "$script_dir/deploy.sh" "${args[@]}" --python "$python" || fail "deploy.sh $tag 失敗（exit $?）"
    dk image rm "$image" >/dev/null 2>&1 || note "留下 $image（刪不掉）"
  else
    # api and scheduler: the web image is deploy.sh's to build.
    compose_here up -d --no-build --wait api scheduler >&2 || fail "compose up 失敗"
  fi
  steps+=(start)
  # 10 readback
  dk compose ls --all --filter "name=^$project\$" >&2
  dk ps --filter "label=com.docker.compose.project=$project" --format '{{.Names}} {{.Image}} {{.Status}}' >&2
  scheduler="$(dk ps -q --filter "label=com.docker.compose.project=$project" \
    --filter label=com.docker.compose.service=scheduler --filter label=com.docker.compose.oneoff=False | tr -d '\r' | head -1)"
  [ -n "$scheduler" ] || fail "沒有在跑的 scheduler"
  ready="" deadline=$((SECONDS + 120))
  until ready="$(dk logs "$scheduler" 2>&1 | grep -m1 ' serve ready ')"; do
    [ "$SECONDS" -lt "$deadline" ] || fail "scheduler 的日誌 120 秒內沒有 serve ready"
    sleep 2
  done
  printf '%s\n' "$ready" >&2
  if [ "$write_check" = 1 ]; then
    dk exec -u 1000 "$scheduler" python -m worker.cli job news --trigger manual --skip-news-llm \
      --min-free-memory-gb 1 >&2 \
      || fail "scheduler 內 job news 失敗"
    dk exec -u 1000 "$scheduler" sh -c 'stat -c "%u:%g %n" /data/stock.db $(ls -t /data/logs/news-*.log | head -1)' >&2 \
      || fail "讀不到 job news 寫的檔"
  fi
  steps+=(readback)
  finish done
  exit 0
fi

# =============================================================================================
# rollback
[ -z "$dirty" ] || refuse "發佈 checkout 有未 commit 的改動：$checkout"
[ -n "$pre_docker" ] || refuse "發佈 checkout 沒有 pre-docker branch（切換的第 1 步建立）"
[ "$(git -C "$checkout" config branch.pre-docker.remote | tr -d '\r')" = . ] \
  && [ "$(git -C "$checkout" config branch.pre-docker.merge | tr -d '\r')" = refs/heads/pre-docker ] \
  || refuse "pre-docker 的 upstream 不是它自己（branch.pre-docker.remote=. merge=refs/heads/pre-docker）"
volume_exists || refuse "沒有 volume $volume"
[ -d "$data_dir/raw" ] || refuse "資料目錄沒有 raw/：$data_dir"
source_image="$(dk ps -a --filter "label=com.docker.compose.project=$project" \
  --filter label=com.docker.compose.service=scheduler --filter label=com.docker.compose.oneoff=False \
  --format '{{.Image}}' | tr -d '\r' | head -1)"
[ -n "$source_image" ] || source_image="$image"
dk image inspect "$source_image" >/dev/null 2>&1 || refuse "沒有可用來取快照的 image（$source_image）"
copy="$work_native/rollback/stock.db"
plan stop "docker stop：project $project 在跑的容器（$(project_running | wc -l | tr -d ' ') 個）"
plan snapshot "docker run -d --name $project-rollback -v $volume:/data -u 1000 $source_image sleep；copy_db.py /data/stock.db；docker cp → $copy；比 /data/logs/cutover.json 新的 raw → $data_native/raw（不覆寫）、logs → $work_native/rollback/logs"
plan paths "cutover_db.py rewrite-paths $copy $data_native/raw；integrity_check"
plan install "$data_native/stock.db（-wal、-shm）→ $data_native/backups/pre-rollback-<UTC>/；$copy → $data_native/stock.db"
plan checkout "git -C $checkout_native checkout pre-docker（${pre_docker:0:9}）；git pull --ff-only"
plan enable "Enable-ScheduledTask -TaskPath '$task_path' -TaskName ${tasks//,/ ／ }$([ "$start_news" = 1 ] && printf '；Start-ScheduledTask news 一次')"
if [ "$dry" = 1 ]; then
  note "乾跑：以上步驟都沒有執行；工作排程器：$(printf '%s ' $states)"
  finish dry-run
  exit 0
fi
steps=()
rb="$project-rollback"
# 1 stop
running="$(project_running)"
[ -z "$running" ] || dk stop $running >/dev/null || fail "docker stop 失敗"
steps+=(stop)
# 2 snapshot
mkdir -p "$work_dir/rollback/logs" || fail "無法建立 $work_dir/rollback"
rm -f "$work_dir/rollback/stock.db" "$work_dir/rollback/stock.db.partial"
dk rm -f "$rb" >/dev/null 2>&1
dk run -d --name "$rb" -v "$volume:/data" -u 1000 --entrypoint sleep "$source_image" infinity >/dev/null \
  || fail "啟動快照用的容器失敗"
dk exec -u 1000 "$rb" python -X utf8 /app/tools/ops/copy_db.py --src /data/stock.db --dest /tmp/rollback >&2 \
  || fail "容器內 copy_db.py 失敗"
dk cp "$rb:/tmp/rollback/stock.db" "$copy" || fail "docker cp 快照回主機失敗"
marker=/data/logs/cutover.json
for sub in raw logs; do
  list="$(dk exec -u 1000 "$rb" sh -c "cd /data/$sub && if [ -f $marker ]; then find . -type f -newer $marker; else find . -type f; fi" | tr -d '\r')" \
    || fail "列不出 /data/$sub 的新檔"
  n="$(printf '%s' "$list" | grep -c . || true)"
  if [ "$n" -gt 0 ]; then
    dest="$data_dir/raw"
    [ "$sub" = raw ] || dest="$work_dir/rollback/logs"
    printf '%s\n' "$list" | dk exec -i -u 1000 "$rb" tar -C "/data/$sub" -cf - -T - \
      | tar -C "$dest" --skip-old-files -xf - || fail "取回 /data/$sub 的新檔失敗"
  fi
  note "$sub：取回 $n 個比 cutover.json 新的檔"
done
dk rm -f "$rb" >/dev/null || note "留下容器 $rb（刪不掉）"
steps+=(snapshot)
# 3 paths
changed="$("$python" -X utf8 "$script_dir/cutover_db.py" rewrite-paths "$copy" "$data_native/raw")" \
  || fail "改寫 payload_path 失敗"
note "payload_path：$changed 列從 /data/raw/ 改成 $data_native/raw"
"$python" -X utf8 "$script_dir/cutover_db.py" counts "$copy" >"$work_dir/rollback/counts.json" || fail "讀不到快照"
grep -q '"integrity_check": "ok"' "$work_dir/rollback/counts.json" || fail "快照 integrity_check 不是 ok"
steps+=(paths)
# 4 install
backup="$data_dir/backups/pre-rollback-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup" || fail "無法建立 $backup"
for suffix in "" -wal -shm; do
  [ ! -e "$data_dir/stock.db$suffix" ] || mv "$data_dir/stock.db$suffix" "$backup/" || fail "搬開 stock.db$suffix 失敗"
done
cp "$copy" "$data_dir/stock.db.partial" && mv "$data_dir/stock.db.partial" "$data_dir/stock.db" \
  || fail "放回 stock.db 失敗（原檔在 $backup）"
note "原 stock.db 在 $backup"
steps+=(install)
# 5 checkout
git -C "$checkout" checkout -q pre-docker || fail "git checkout pre-docker 失敗"
git -C "$checkout" pull --ff-only >&2
pulled=$?
[ "$pulled" = 0 ] || fail "git pull --ff-only exit $pulled"
note "git pull --ff-only exit 0；HEAD $(git -C "$checkout" rev-parse --short HEAD)"
steps+=(checkout)
# 6 enable
for name in "${task_list[@]}"; do
  ps1 "Enable-ScheduledTask -TaskPath '$task_path' -TaskName '$name' -ErrorAction Stop | Out-Null" \
    || fail "啟用 $task_path$name 失敗"
done
states="$(task_states)" || fail "讀不到工作排程器"
any_state Disabled && fail "啟用後讀回仍有停用的工作：$(printf '%s ' $states)"
note "工作排程器：$(printf '%s ' $states)"
if [ "$start_news" = 1 ]; then
  ps1 "Start-ScheduledTask -TaskPath '$task_path' -TaskName news -ErrorAction Stop" || fail "Start-ScheduledTask news 失敗"
  deadline=$((SECONDS + wait_timeout))
  sleep 5
  while states="$(task_states)" && [ "$(state_of news)" = Running ]; do
    [ "$SECONDS" -lt "$deadline" ] || fail "news 在 $wait_timeout 秒內沒有結束"
    sleep 5
  done
  result="$(ps1 "(Get-ScheduledTaskInfo -TaskPath '$task_path' -TaskName news).LastTaskResult" | tr -d '\r ')"
  [ "$result" = 0 ] || fail "news 的 LastTaskResult 是 $result"
  note "news 跑完，LastTaskResult 0"
fi
steps+=(enable)
finish done
exit 0
