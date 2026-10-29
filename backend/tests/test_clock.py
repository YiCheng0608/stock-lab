"""app.clock.utcnow: what datetime.utcnow() returned, without its deprecation (#374).

The DateTime columns store naive UTC. Before #374 their defaults and the worker's
timestamps came from ``datetime.utcnow()``, which warned on every call; utcnow() must
write the same value in the same SQLite text form, and nothing may call the deprecated
method again.
"""

from __future__ import annotations

import ast
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.orm import Session

from app import clock
from app.clock import utcnow
from app.db import Base
from app.models import IngestionRun

BACKEND = Path(__file__).resolve().parents[1]
# The instants the frozen clock answers: a write, then an update.
WRITTEN = datetime(2026, 10, 29, 16, 12, 50, 123456, tzinfo=timezone.utc)
UPDATED = datetime(2026, 10, 30, 1, 2, 3, 4, tzinfo=timezone.utc)


@pytest.fixture
def frozen(monkeypatch):
    """app.clock's datetime.now(timezone.utc) answers instant[0]."""
    instant = [WRITTEN]

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return instant[0]

    monkeypatch.setattr(clock, "datetime", Frozen)
    return instant


def test_utcnow_is_the_current_naive_utc_time() -> None:
    before = datetime.fromtimestamp(time.time(), timezone.utc).replace(tzinfo=None)
    value = utcnow()
    after = datetime.fromtimestamp(time.time(), timezone.utc).replace(tzinfo=None)
    assert type(value) is datetime
    assert value.tzinfo is None
    # time.time() is a float: allow a millisecond for its rounding.
    slack = timedelta(milliseconds=1)
    assert before - slack <= value <= after + slack


def test_utcnow_isoformat_has_no_offset(frozen) -> None:
    assert utcnow().isoformat() == "2026-10-29T16:12:50.123456"


def test_a_default_stores_the_text_a_naive_utc_value_stores(frozen) -> None:
    """A row written by the column defaults and one given the naive UTC value
    datetime.utcnow() returned at the same instant store the same SQLite text;
    onupdate likewise."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[IngestionRun.__table__])
    naive = WRITTEN.replace(tzinfo=None)
    row = dict(run_type="daily", source="test", run_date=date(2026, 10, 29))
    with Session(engine) as session:
        session.add(IngestionRun(**row))
        session.add(IngestionRun(**row, started_at=naive, updated_at=naive))
        session.commit()
        stored = session.execute(
            text("SELECT started_at, updated_at FROM ingestion_runs ORDER BY id")
        ).all()
        assert [tuple(r) for r in stored] == [
            ("2026-10-29 16:12:50.123456", "2026-10-29 16:12:50.123456"),
            ("2026-10-29 16:12:50.123456", "2026-10-29 16:12:50.123456"),
        ]
        first = session.get(IngestionRun, 1)
        assert first.started_at == naive and first.started_at.tzinfo is None

        frozen[0] = UPDATED
        first.status = "success"
        session.commit()
        assert session.execute(
            text("SELECT started_at, updated_at FROM ingestion_runs WHERE id = 1")
        ).one() == ("2026-10-29 16:12:50.123456", "2026-10-30 01:02:03.000004")
    engine.dispose()


def test_every_datetime_column_default_calls_utcnow_at_write_time() -> None:
    """A DateTime default or onupdate is app.clock.utcnow itself: `default=utcnow()`
    would store the import time in every row and still pass the IngestionRun test
    above (#374 review)."""
    seen = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, DateTime):
                continue
            for kind in ("default", "onupdate"):
                default = getattr(column, kind)
                if default is None:
                    continue
                name = f"{table.name}.{column.name} {kind}"
                assert default.is_callable, name
                assert getattr(default.arg, "__wrapped__", None) is utcnow, name
                seen.append(name)
    # models.py: 27 column defaults and ingestion_runs.updated_at's onupdate.
    assert len(seen) == 28


def _clock_modules(tree: ast.AST) -> set[str]:
    """Names this file binds to the app.clock module (`from app import clock`)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("app", None):
            names |= {a.asname or a.name for a in node.names if a.name == "clock"}
        if isinstance(node, ast.Import):
            names |= {
                a.asname for a in node.names if a.name == "app.clock" and a.asname
            }
    return names


def _deprecated_utcnow(tree: ast.AST) -> list[int]:
    """Lines reading any `.utcnow` attribute (datetime.utcnow, dt.utcnow after
    `from datetime import datetime as dt`, datetime.datetime.utcnow, X.datetime.utcnow)
    other than app.clock's, and any `from datetime import utcnow`."""
    clock_names = _clock_modules(tree)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "utcnow":
            owner = node.value
            if not (isinstance(owner, ast.Name) and owner.id in clock_names):
                lines.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "datetime"
        ):
            lines += [node.lineno for a in node.names if a.name == "utcnow"]
    return lines


def test_the_utcnow_scan_catches_every_spelling() -> None:
    caught = (
        "datetime.utcnow()",
        "x = datetime.utcnow",
        "import datetime\ndatetime.datetime.utcnow()",
        "import datetime as d\nd.datetime.utcnow()",
        "from datetime import datetime as dt\ndt.utcnow()",
        "from datetime import utcnow",
        "from app import models\nmodels.datetime.utcnow()",
    )
    for source in caught:
        assert _deprecated_utcnow(ast.parse(source)), source
    allowed = (
        "from app.clock import utcnow\nutcnow()",
        "from app import clock\nclock.utcnow()",
        "from . import clock as c\nc.utcnow()",
        "import app.clock as c\nc.utcnow()",
        'monkeypatch.setattr(sources, "utcnow", fake)',
    )
    for source in allowed:
        assert _deprecated_utcnow(ast.parse(source)) == [], source


def test_nothing_calls_datetime_utcnow() -> None:
    """#374: datetime.utcnow() is deprecated and warned about 170,000 times per run;
    use app.clock.utcnow(). Every .py file under backend/, alembic included."""
    found = []
    paths = [p for p in BACKEND.rglob("*.py") if "__pycache__" not in p.parts]
    assert {p.relative_to(BACKEND).parts[0] for p in paths} >= {
        "alembic",
        "app",
        "tests",
        "worker",
    }
    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(BACKEND).as_posix()
        found += [f"{rel}:{line}" for line in _deprecated_utcnow(tree)]
    assert found == []
