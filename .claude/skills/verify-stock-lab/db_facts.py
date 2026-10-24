"""Read-only facts from the verify copy for verify-stock-lab (Issue #227).

Usage: python db_facts.py <copy stock.db> [<exchange> <symbol>]

Opens the copy with mode=ro and query_only and prints one JSON object with the
latest dates and counts the feature checks compare against. A missing table
gives null. With an instrument, also its latest market bar date and source.
Candidate facts only count runs of the current score version, as the API does
(backend/app/candidate_view.py, _run_for).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

# Same value as backend/app/domain.py; backend/tests/test_verify_tools.py keeps
# them equal. This script runs on the stdlib-only tool Python, so it cannot
# import the backend (#237).
CANDIDATE_SCORE_VERSION = "candidate_score_v1"
# Same as backend/app/domain.py PLAN_OPEN_STATUSES (kept equal by the same test).
PLAN_OPEN_STATUSES = ("pending", "triggered")
_OPEN = ", ".join(f"'{status}'" for status in PLAN_OPEN_STATUSES)

QUERIES = {
    "market_latest_trading_date": (
        "market_bars",
        "SELECT max(trading_date) FROM market_bars",
    ),
    "group_scores_latest_trading_date": (
        "group_daily_scores",
        "SELECT max(trading_date) FROM group_daily_scores WHERE rank IS NOT NULL",
    ),
    "candidate_run_latest_trading_date": (
        "candidate_runs",
        "SELECT max(trading_date) FROM candidate_runs"
        f" WHERE score_version = '{CANDIDATE_SCORE_VERSION}'",
    ),
    "candidate_count_latest": (
        "candidate_runs",
        "SELECT candidate_count FROM candidate_runs"
        f" WHERE score_version = '{CANDIDATE_SCORE_VERSION}'"
        " ORDER BY trading_date DESC, id DESC LIMIT 1",
    ),
    "news_items": ("news_items", "SELECT count(*) FROM news_items"),
    "news_latest_published_at": (
        "news_items",
        "SELECT max(published_at) FROM news_items",
    ),
    "news_llm_done": (
        "news_llm_results",
        "SELECT count(*) FROM news_llm_results WHERE llm_status = 'done'",
    ),
    "theme_suggestions": (
        "theme_suggestions",
        "SELECT count(*) FROM theme_suggestions",
    ),
    # User tracking plans: the actions page's 追蹤計畫 and 追蹤回看 (A8).
    "tracking_plans_open": (
        "tracking_plans",
        f"SELECT count(*) FROM tracking_plans WHERE status IN ({_OPEN})",
    ),
    "tracking_plans_closed": (
        "tracking_plans",
        f"SELECT count(*) FROM tracking_plans WHERE status NOT IN ({_OPEN})",
    ),
    # Private: when non-zero the today and actions pages show holdings, so the run's
    # screenshots and API JSON stay local (SKILL.md, Doctor step 4).
    "portfolio_positions": (
        "portfolio_positions",
        "SELECT count(*) FROM portfolio_positions",
    ),
    "alembic_version": ("alembic_version", "SELECT version_num FROM alembic_version"),
}

INSTRUMENT_BAR = """
SELECT b.trading_date, b.source FROM market_bars b
JOIN instruments i ON i.id = b.instrument_id
WHERE i.exchange = ? AND i.symbol = ?
ORDER BY b.trading_date DESC LIMIT 1
"""


def facts(db: Path, instrument: tuple[str, str] | None = None) -> dict[str, object]:
    uri = db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        result: dict[str, object] = {
            key: conn.execute(sql).fetchone()[0] if table in tables else None
            for key, (table, sql) in QUERIES.items()
        }
        if instrument:
            row = conn.execute(INSTRUMENT_BAR, instrument).fetchone()
            result["instrument"] = {
                "exchange": instrument[0],
                "symbol": instrument[1],
                "latest_trading_date": row[0] if row else None,
                "source": row[1] if row else None,
            }
    return result


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3):
        print(__doc__, file=sys.stderr)
        return 2
    instrument = (argv[1], argv[2]) if len(argv) == 3 else None
    print(json.dumps(facts(Path(argv[0]), instrument), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
