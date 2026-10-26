"""#260 AC-6: export the 10/19-10/22 baseline from a read-only DB into a new SQLite file.

usage: python export_baseline.py <src stock.db> <out baseline.db>
"""

import sqlite3
import sys
from pathlib import Path

DATES = ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22")
TABLES = {
    "signals": "signal_date",
    "technical_features": "trading_date",
    "group_daily_scores": "trading_date",
    "group_daily_score_archive": "trading_date",
    "daily_candidates": None,  # via candidate_runs
    "candidate_runs": "trading_date",
}

src, out = sys.argv[1], Path(sys.argv[2])
if out.exists():
    sys.exit(f"{out} exists")
con = sqlite3.connect(out, uri=True)
con.execute(f"ATTACH DATABASE 'file:{src}?mode=ro' AS src")
marks = ",".join("?" * len(DATES))
for table, column in TABLES.items():
    if column:
        con.execute(
            f"CREATE TABLE main.{table} AS SELECT * FROM src.{table} WHERE {column} IN ({marks})",
            DATES,
        )
    else:
        con.execute(
            f"CREATE TABLE main.{table} AS SELECT * FROM src.{table} WHERE candidate_run_id IN "
            f"(SELECT id FROM src.candidate_runs WHERE trading_date IN ({marks}))",
            DATES,
        )
# Reference tables needed to read the rows.
con.execute("CREATE TABLE main.instruments AS SELECT * FROM src.instruments")
con.execute("CREATE TABLE main.strategy_versions AS SELECT * FROM src.strategy_versions")
con.execute("CREATE TABLE main.theme_groups AS SELECT * FROM src.theme_groups")
con.commit()
for table in (*TABLES, "instruments"):
    rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    per_day = ""
    column = TABLES.get(table)
    if column:
        per_day = dict(
            con.execute(f"SELECT {column}, count(*) FROM {table} GROUP BY {column}").fetchall()
        )
    print(table, rows, per_day)
con.close()
