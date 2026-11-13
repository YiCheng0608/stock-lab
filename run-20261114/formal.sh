#!/bin/sh
# #673 formal run: research backtest (canonical breakout_v3, pullback_v4), then exit_research.
set -u
cd /app
echo "backtest start $(date -u +%FT%TZ)" >> /out/formal/status.txt
python tools/research/backtest_research.py --db /db/stock.db --start 2024-09-30 --end 2026-11-13 --slim --min-free-gb 0 > /out/formal/backtest.json 2> /out/formal/backtest.log
code=$?
echo "backtest exit $code $(date -u +%FT%TZ)" >> /out/formal/status.txt
[ "$code" -eq 0 ] || exit "$code"
RUN=$(python -c "import json;print(json.load(open('/out/formal/backtest.json'))['run_id'])")
python tools/research/exit_research.py --db /db/stock.db --run-id "$RUN" --out /out/formal/report --min-free-gb 0 > /out/formal/exit.json 2> /out/formal/exit.log
echo "exit_research exit $? $(date -u +%FT%TZ)" >> /out/formal/status.txt
