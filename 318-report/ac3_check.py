"""AC-3 read-only check of the production stock.db (#318): mode=ro, query_only."""

import json
import sqlite3
import sys

db = sys.argv[1]
since = sys.argv[2] if len(sys.argv) > 2 else "2026-11-04"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.execute("PRAGMA query_only=1")
q = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
out = {
    "db": db,
    "ingestion_runs_max_id": q("select max(id) from ingestion_runs"),
    "ingestion_runs_backtest": q(
        "select count(*) from ingestion_runs where run_type='backtest'"
    ),
    "strategy_versions_ablate": q(
        "select count(*) from strategy_versions where name like '%ablate%'"
    ),
    "signals_backtest_key": q(
        "select count(*) from signals where signal_key like 'backtest-%'"
    ),
    "schedule_runs_max_id": q("select max(id) from schedule_runs"),
    "schedule_runs_manual_since": q(
        "select count(*) from schedule_runs where trigger='manual' and started_at >= ?",
        since,
    ),
    "latest_trading_date": q("select max(trading_date) from market_bars"),
    "recent_ingestion_runs": con.execute(
        "select id, run_type, status, started_at from ingestion_runs "
        "order by id desc limit 8"
    ).fetchall(),
}
print(json.dumps(out, ensure_ascii=False, default=str))
