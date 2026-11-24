"""/api/h2 answers as before the move to the strategy list tables (#1014 AC-2).

``fixtures/h2_api/before_1014.json`` holds the responses of ``/api/h2`` on
``test_h2_list``'s fixture, written by master's code before #1014 (commit
291726db, the H2 rows in ``h2_runs`` / ``h2_items``): the latest list, a date
of it, an older date, a zero day and a missing day, with a today list mark, a
TAIEX calendar for the change and sparkline, and every run's ``computed_at``
fixed.  The same steps on the current code must give every field the same.
``STOCK_H2_API_DUMP=<path>`` writes the responses there instead of comparing
(how the file was made; this module reads no table or class by name, so it
runs on both).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from test_h2_list import (  # noqa: F401 - factory and golden_db are fixtures
    DAYS,
    T,
    _taiex,
    _today_list,
    factory,
    golden_db,
)
from worker.h2_list import run_h2_list

BEFORE = Path(__file__).parent / "fixtures" / "h2_api" / "before_1014.json"
COMPUTED_AT = "2026-11-20 10:06:00.000000"
QUERIES = (
    "",
    f"?date={T.isoformat()}",
    f"?date={DAYS[245].isoformat()}",
    f"?date={DAYS[10].isoformat()}",
    f"?date={DAYS[-2].isoformat()}",
)


def _responses(make) -> dict[str, dict]:
    for day in (DAYS[10], DAYS[245], T):
        assert run_h2_list(day)["status"] == "success"
    with make() as db:
        tables = set(
            db.scalars(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        )
        runs = "strategy_list_runs" if "strategy_list_runs" in tables else "h2_runs"
        db.execute(text(f"UPDATE {runs} SET computed_at = :at"), {"at": COMPUTED_AT})
        db.commit()
    _taiex(make, DAYS[-30:])
    client = TestClient(app)
    items = client.get("/api/h2").json()["items"]
    first, third = items[0]["instrument"]["id"], items[2]["instrument"]["id"]
    _today_list(make, T, {first: (4, "breakout"), third: (9, "pullback")})
    return {query: client.get(f"/api/h2{query}").json() for query in QUERIES}


def test_the_api_answers_every_field_as_before(factory):  # noqa: F811
    responses = _responses(factory)
    dump = os.environ.get("STOCK_H2_API_DUMP")
    if dump:
        Path(dump).write_text(
            json.dumps(responses, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    assert set(before) == set(QUERIES)
    for query in QUERIES:
        assert responses[query] == before[query], query
    # The fixture is not trivial: a list with marks, an older one, zero, missing.
    assert before[""]["status"] == "computed" and len(before[""]["items"]) == 20
    assert sum(row["today_list"] is not None for row in before[""]["items"]) == 2
    assert before[QUERIES[2]]["items"][-1]["high_gap_240"] is None
    assert before[QUERIES[3]]["status"] == "zero"
    assert before[QUERIES[4]]["status"] == "missing"
