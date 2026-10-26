#!/usr/bin/env bash
# #260 AC-6 replay: daily --force on the copy for 10/19..10/22, release/v1 worktree code.
set -u
T=C:/Users/YiCheng/AppData/Local/Temp/t260r
export STOCK_DATA_DIR=$T/db
export STOCK_DB_PATH=$T/db/stock.db
export STOCK_RAW_DIR=$T/raw
export STOCK_CLAUDE_CLI=$T/no-claude/claude.exe
export PYTHONPATH=C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-260-g7-replay/backend
PY=C:/Users/YiCheng/stock-lab-release/.venv/Scripts/python.exe
cd C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-260-g7-replay
for D in 2026-10-19 2026-10-20 2026-10-21 2026-10-22; do
  echo "=== $D start $(powershell -NoProfile -c "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'")"
  "$PY" -X utf8 -m worker.cli daily --date $D --force --trigger simulation --catchup-sessions 0 > $T/logs/daily-$D.json 2> $T/logs/daily-$D.err
  echo "=== $D exit $? end $(powershell -NoProfile -c "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'")"
done
