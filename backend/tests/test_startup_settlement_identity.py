"""Finite startup identity policy on independently built synthetic SQLite files."""

import asyncio
import hashlib
import sqlite3

import pytest
from sqlalchemy import create_engine

from app import database_readiness as readiness, main
from app.db import Base


PAIR = "UNIQUE(signal_id, horizon)"
PAIR_INDEX = "CREATE UNIQUE INDEX canonical ON signal_settlements(signal_id, horizon)"
SETTLEMENT_DDL = """
CREATE TABLE signal_settlements (
    id INTEGER NOT NULL PRIMARY KEY,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    horizon INTEGER NOT NULL DEFAULT 20,
    settlement_date DATE NOT NULL,
    final_status VARCHAR(80), first_trigger VARCHAR(120), return_or_risk FLOAT,
    incomparable_reason TEXT, source VARCHAR(500), data_time VARCHAR(80),
    execution_date DATE, execution_price FLOAT, comparable BOOLEAN,
    data_quality VARCHAR(30) NOT NULL DEFAULT 'complete',
    {constraint}
)
"""


def fingerprint(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def build_database(path, marker="alembic", constraint=PAIR, extras=()):
    # Only the unrelated mapped prerequisites come from metadata. Settlement
    # DDL is independent of both migrations and the production validator.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE signal_settlements")
        connection.execute(SETTLEMENT_DDL.format(constraint=constraint or "CHECK(1=1)"))
        for sql in extras:
            connection.execute(sql)
        if marker in ("alembic", "both"):
            connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
            connection.execute("INSERT INTO alembic_version VALUES (?)", (readiness.REVISIONS[-1],))
        if marker in ("fallback", "both"):
            connection.execute("CREATE TABLE schema_migrations(version TEXT)")
            connection.executemany("INSERT INTO schema_migrations VALUES (?)", [(v,) for v in readiness.REVISIONS])
    return path


def shape(name, constraint, extras, accepted):
    return pytest.param(constraint, extras, accepted, id=name)


SHAPES = [
    shape("anonymous-constraint", PAIR, (), True),
    shape("named-constraint", "CONSTRAINT arbitrary_name " + PAIR, (), True),
    shape("quoted-constraint", 'CONSTRAINT "odd "" name" ' + PAIR, (), True),
    shape("explicit-index", None, (PAIR_INDEX,), True),
    shape("quoted-index", None, ('CREATE UNIQUE INDEX "odd "" name" ON signal_settlements("signal_id", "horizon")',), True),
    shape("duplicate-pair", PAIR, (PAIR_INDEX,), True),
    shape("explicit-binary-asc", None, ("CREATE UNIQUE INDEX explicit ON signal_settlements(signal_id COLLATE BINARY ASC,horizon COLLATE BINARY ASC)",), True),
    shape("no-pair", None, (), False),
    shape("signal-only", "UNIQUE(signal_id)", (), False),
    shape("mixed-constraint", PAIR + ", UNIQUE(signal_id)", (), False),
    shape("mixed-index", PAIR, ("CREATE UNIQUE INDEX legacy ON signal_settlements(signal_id)",), False),
    shape("horizon-only", PAIR, ("CREATE UNIQUE INDEX legacy ON signal_settlements(horizon)",), False),
    shape("reversed-only", "UNIQUE(horizon,signal_id)", (), False),
    shape("reversed-extra", PAIR, ("CREATE UNIQUE INDEX reversed ON signal_settlements(horizon,signal_id)",), False),
    shape("superset", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(signal_id,horizon,id)",), False),
    shape("target-and-source", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(source,signal_id)",), False),
    shape("partial-pair-only", None, (PAIR_INDEX + " WHERE horizon=20",), False),
    shape("partial-pair-extra", PAIR, (PAIR_INDEX + " WHERE horizon=20",), False),
    shape("partial-signal", PAIR, ("CREATE UNIQUE INDEX legacy ON signal_settlements(signal_id) WHERE horizon IN (5,20)",), False),
    shape("partial-false", PAIR, ("CREATE UNIQUE INDEX legacy ON signal_settlements(signal_id) WHERE 0",), False),
    shape("expression-only", None, ("CREATE UNIQUE INDEX expr ON signal_settlements(signal_id,abs(horizon))",), False),
    shape("expression-target", PAIR, ("CREATE UNIQUE INDEX expr ON signal_settlements(abs(signal_id))",), False),
    shape("expression-unrelated", PAIR, ("CREATE UNIQUE INDEX expr ON signal_settlements(lower(source))",), False),
    shape("expression-constant", PAIR, ("CREATE UNIQUE INDEX expr ON signal_settlements(1)",), False),
    shape("expression-partial", PAIR, ("CREATE UNIQUE INDEX expr ON signal_settlements(lower(source)) WHERE 0",), False),
    shape("expression-mixed", PAIR, ("CREATE UNIQUE INDEX expr ON signal_settlements(source,abs(horizon))",), False),
    shape("nocase-only", None, ("CREATE UNIQUE INDEX nc ON signal_settlements(signal_id COLLATE NOCASE,horizon)",), False),
    shape("rtrim-extra", PAIR, ("CREATE UNIQUE INDEX rt ON signal_settlements(signal_id,horizon COLLATE RTRIM)",), False),
    shape("desc-only", None, ("CREATE UNIQUE INDEX ds ON signal_settlements(signal_id DESC,horizon)",), False),
    shape("desc-extra", PAIR, ("CREATE UNIQUE INDEX ds ON signal_settlements(signal_id,horizon DESC)",), False),
    shape("unrelated-id", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(id)",), True),
    shape("unrelated-source", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(source)",), True),
    shape("unrelated-partial", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(source) WHERE horizon IN (5,20)",), True),
    shape("unrelated-collation-desc", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(source COLLATE NOCASE DESC)",), True),
    shape("unrelated-id-partial", PAIR, ("CREATE UNIQUE INDEX extra ON signal_settlements(id) WHERE signal_id>0",), True),
    shape("unrelated-without-pair", None, ("CREATE UNIQUE INDEX extra ON signal_settlements(source)",), False),
    shape("nonunique-target", PAIR, ("CREATE INDEX extra ON signal_settlements(signal_id DESC)",), True),
    shape("nonunique-expression-partial", PAIR, ("CREATE INDEX extra ON signal_settlements(abs(signal_id)) WHERE horizon=20",), True),
    shape("unrelated-check", PAIR + ", CHECK(horizon=20)", (), True),
    shape("unrelated-trigger", PAIR, ("CREATE TRIGGER extra BEFORE INSERT ON signal_settlements BEGIN SELECT RAISE(ABORT,'custom restriction'); END",), True),
]


@pytest.mark.parametrize("marker", ["alembic", "fallback", "both"])
@pytest.mark.parametrize("constraint,extras,accepted", SHAPES)
def test_startup_settlement_unique_policy(tmp_path, monkeypatch, marker, constraint, extras, accepted):
    path = build_database(tmp_path / "case.db", marker, constraint, extras)
    before = fingerprint(path)
    original_connect = sqlite3.connect
    traces, historical_reads, forbidden_operations = [], [], []

    def observe(database, **kwargs):
        assert database == path.resolve().as_uri() + "?mode=ro"
        assert kwargs == {"uri": True, "timeout": readiness.READ_TIMEOUT_SECONDS}
        connection = original_connect(database, **kwargs)
        statements = []
        traces.append(statements)
        connection.set_trace_callback(statements.append)

        def authorize(action, first, second, schema, trigger):
            if action == sqlite3.SQLITE_READ and first not in (
                "sqlite_master", "sqlite_schema", "alembic_version", "schema_migrations",
            ):
                historical_reads.append((first, second, schema, trigger))
                return sqlite3.SQLITE_DENY
            if action not in (
                sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_PRAGMA,
                sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_FUNCTION,
            ):
                forbidden_operations.append((action, first, second))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(readiness.sqlite3, "connect", observe)
    monkeypatch.setattr(readiness, "DB_PATH", path)
    entered = []

    async def enter_lifespan():
        async with main.lifespan(main.app):
            entered.append(True)

    for call in (lambda: readiness.check_database_readiness(path),
                 lambda: readiness.check_database_readiness(path),
                 lambda: asyncio.run(enter_lifespan())):
        if accepted:
            call()
        else:
            with pytest.raises(readiness.DatabaseReadinessError, match="signal_settlements") as error:
                call()
            assert "API startup does not initialize, migrate or repair" in str(error.value)
        assert fingerprint(path) == before
    assert entered == ([True] if accepted else [])
    assert not historical_reads and not forbidden_operations
    assert len(traces) == 3
    for statements in traces:
        assert statements[:2] == ["PRAGMA query_only=ON", "BEGIN"]
        assert statements.count("BEGIN") == 1
        assert all(sql.startswith(("SELECT ", "PRAGMA ", "BEGIN")) for sql in statements)
        assert 'PRAGMA main.index_list("signal_settlements")' in statements


@pytest.mark.parametrize("extra,allowed,startup_accepts", [
    pytest.param(None, True, True, id="pair-allows-two-horizons"),
    pytest.param("CREATE UNIQUE INDEX legacy ON signal_settlements(signal_id)", False, False, id="mixed-blocks-two-horizons"),
    pytest.param("CREATE UNIQUE INDEX reversed ON signal_settlements(horizon,signal_id)", True, False, id="reversed-is-policy-rejection"),
    pytest.param("CREATE UNIQUE INDEX ds ON signal_settlements(signal_id DESC,horizon)", True, False, id="desc-is-policy-rejection"),
    pytest.param("CREATE UNIQUE INDEX extra ON signal_settlements(source)", False, True, id="unrelated-unique-outside-audit"),
    pytest.param("CREATE TRIGGER extra BEFORE INSERT ON signal_settlements WHEN NEW.horizon=5 BEGIN SELECT RAISE(ABORT,'custom restriction'); END", False, True, id="trigger-outside-audit"),
])
def test_startup_policy_is_distinct_from_insert_semantics(tmp_path, extra, allowed, startup_accepts):
    path = build_database(tmp_path / "semantics.db", extras=(extra,) if extra else ())
    before = fingerprint(path)
    if startup_accepts:
        readiness.check_database_readiness(path)
    else:
        with pytest.raises(readiness.DatabaseReadinessError, match="signal_settlements"):
            readiness.check_database_readiness(path)
    # Write probes are confined to a fresh memory backup, with FK enforcement
    # intentionally off: this tests unique/trigger behavior, not valid signals.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as memory:
            source.backup(memory)
            memory.execute("INSERT INTO signal_settlements(signal_id,horizon,settlement_date,source) VALUES(1,20,'2026-09-13','same')")
            second = "INSERT INTO signal_settlements(signal_id,horizon,settlement_date,source) VALUES(1,5,'2026-09-13','same')"
            if allowed:
                memory.execute(second)
            else:
                with pytest.raises(sqlite3.IntegrityError):
                    memory.execute(second)
            with pytest.raises(sqlite3.IntegrityError):
                memory.execute("INSERT INTO signal_settlements(signal_id,horizon,settlement_date) VALUES(1,20,'2026-09-13')")
    assert fingerprint(path) == before
