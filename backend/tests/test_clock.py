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
from sqlalchemy import create_engine, text
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


def _datetime_utcnow(node: ast.AST) -> bool:
    """datetime.utcnow or <module>.datetime.utcnow, called or passed as a default."""
    if not (isinstance(node, ast.Attribute) and node.attr == "utcnow"):
        return False
    owner = node.value
    return (isinstance(owner, ast.Name) and owner.id == "datetime") or (
        isinstance(owner, ast.Attribute) and owner.attr == "datetime"
    )


def test_nothing_calls_datetime_utcnow() -> None:
    """#374: datetime.utcnow() is deprecated and warned about 170,000 times per run;
    use app.clock.utcnow()."""
    found = []
    for top in ("app", "worker", "tests"):
        for path in sorted((BACKEND / top).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found += [
                f"{path.relative_to(BACKEND).as_posix()}:{node.lineno}"
                for node in ast.walk(tree)
                if _datetime_utcnow(node)
            ]
    assert found == []
