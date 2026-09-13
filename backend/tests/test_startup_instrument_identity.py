"""Finite instruments startup policy on independently built populated SQLite files."""

import asyncio
import hashlib
import sqlite3

import pytest
from sqlalchemy import create_engine

from app import database_readiness as readiness, db, main, migrations
from app import instrument_identity_migration as identity_migration
from app.db import Base


PAIR = "UNIQUE(exchange, symbol)"
PAIR_INDEX = "CREATE UNIQUE INDEX canonical ON instruments(exchange, symbol)"
INSTRUMENT_DDL = """
CREATE TABLE instruments (
    id INTEGER NOT NULL PRIMARY KEY, market VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE', symbol VARCHAR(30) NOT NULL,
    name VARCHAR(120) NOT NULL, instrument_type VARCHAR(20) NOT NULL,
    etf_category VARCHAR(30), industry VARCHAR(120), listing_date DATE,
    is_watchlisted BOOLEAN NOT NULL, status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL{extra_columns}, {constraint}
)
"""
INSERT = """INSERT INTO instruments
    (id,market,exchange,symbol,name,instrument_type,is_watchlisted,status,created_at)
    VALUES (?,?,?,?,?,'stock',0,'active','2026-09-13')"""
GENERATED_TARGETS = {
    "market": ("market VARCHAR(20) NOT NULL", "market VARCHAR(20) GENERATED ALWAYS AS (exchange)"),
    "exchange": ("exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE'", "exchange VARCHAR(20) GENERATED ALWAYS AS (market)"),
    "symbol": ("symbol VARCHAR(30) NOT NULL", "symbol VARCHAR(30) GENERATED ALWAYS AS (name)"),
}


def fingerprint(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def build_database(path, marker="alembic", constraint=PAIR, extras=(), extra_columns="", generated=None):
    # Only unrelated prerequisites use ORM metadata; instruments DDL and its
    # populated seed are independent of migrations and the production gate.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE instruments")
        ddl = INSTRUMENT_DDL.format(constraint=constraint or "CHECK(1=1)", extra_columns=extra_columns)
        seed_sql, seed = INSERT, [1, "SEED", "SEED", "999", "Seed"]
        if generated:
            target, mode = generated
            old, new = GENERATED_TARGETS[target]
            ddl = ddl.replace(old, new + " " + mode)
            names = ["id", "market", "exchange", "symbol", "name"]
            seed_sql = INSERT.replace(",".join(names), ",".join(name for name in names if name != target))
            seed_sql = seed_sql.replace("?,?,?,?,?", "?,?,?,?")
            seed.pop(names.index(target))
        connection.execute(ddl)
        connection.execute(seed_sql, seed)
        for sql in extras:
            connection.execute(sql)
        if marker in ("alembic", "both"):
            connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
            connection.execute("INSERT INTO alembic_version VALUES (?)", (readiness.REVISIONS[-1],))
        if marker in ("fallback", "both"):
            connection.execute("CREATE TABLE schema_migrations(version TEXT)")
            connection.executemany("INSERT INTO schema_migrations VALUES (?)", [(v,) for v in readiness.REVISIONS])
    return path


def shape(name, constraint=PAIR, extras=(), accepted=False, extra_columns="", generated=None):
    return pytest.param(constraint, extras, extra_columns, generated, accepted, id=name)


SHAPES = [
    shape("anonymous", accepted=True),
    shape("named", "CONSTRAINT arbitrary_name " + PAIR, accepted=True),
    shape("quoted", 'CONSTRAINT "odd "" name" UNIQUE("exchange", "symbol")', accepted=True),
    shape("explicit", None, (PAIR_INDEX,), True),
    shape("quoted-index", None, ('CREATE UNIQUE INDEX "odd "" name" ON instruments("exchange", "symbol")',), True),
    shape("duplicate", extras=(PAIR_INDEX,), accepted=True),
    shape("explicit-asc-binary", None, ("CREATE UNIQUE INDEX extra ON instruments(exchange COLLATE BINARY ASC, symbol COLLATE BINARY ASC)",), True),
    shape("missing", None),
    shape("legacy-only", "UNIQUE(market, symbol)"),
    shape("mixed-constraint", PAIR + ", UNIQUE(market, symbol)"),
    shape("reversed-only", "UNIQUE(symbol, exchange)"),
    shape("partial-only", None, (PAIR_INDEX + " WHERE market='TW'",)),
    shape("nocase-only", None, ("CREATE UNIQUE INDEX extra ON instruments(exchange, symbol COLLATE NOCASE)",)),
    shape("desc-only", None, ("CREATE UNIQUE INDEX extra ON instruments(exchange DESC, symbol)",)),
    shape("expression-only", None, ("CREATE UNIQUE INDEX extra ON instruments(exchange, lower(symbol))",)),
]

for label, keys in [
    ("legacy", "market, symbol"), ("legacy-reversed", "symbol, market"),
    ("current-reversed", "symbol, exchange"), ("market-only", "market"),
    ("exchange-only", "exchange"), ("symbol-only", "symbol"),
    ("current-superset", "exchange, symbol, id"), ("legacy-superset", "market, symbol, name"),
    ("all-identity", "market, exchange, symbol"), ("target-name", "symbol, name"),
    ("market-name", "market, name"), ("nocase", "exchange, symbol COLLATE NOCASE"),
    ("rtrim", "exchange, symbol COLLATE RTRIM"), ("desc", "exchange DESC, symbol"),
    ("legacy-desc", "market, symbol DESC"), ("expression-target", "lower(symbol)"),
    ("expression-mixed", "exchange, lower(symbol)"), ("expression-unrelated", "lower(name)"),
    ("expression-constant", "1"),
]:
    SHAPES.append(shape(label, extras=(f"CREATE UNIQUE INDEX extra ON instruments({keys})",)))

for label, keys, predicate in [
    ("partial-current", "exchange, symbol", "market='TW'"),
    ("partial-legacy", "market, symbol", "market='TW'"),
    ("partial-symbol", "symbol", "exchange IN ('TWSE','TPEx')"),
    ("partial-false", "market, symbol", "0"),
    ("expression-partial-false", "lower(symbol)", "0"),
]:
    SHAPES.append(shape(label, extras=(f"CREATE UNIQUE INDEX extra ON instruments({keys}) WHERE {predicate}",)))

for label, sql in [
    ("unrelated-id", "CREATE UNIQUE INDEX extra ON instruments(id)"),
    ("unrelated-name", "CREATE UNIQUE INDEX extra ON instruments(name)"),
    ("unrelated-collation-desc", "CREATE UNIQUE INDEX extra ON instruments(name COLLATE NOCASE DESC)"),
    ("unrelated-partial", "CREATE UNIQUE INDEX extra ON instruments(name) WHERE symbol='AbC'"),
    ("unrelated-id-partial", "CREATE UNIQUE INDEX extra ON instruments(id) WHERE market='TW'"),
    ("nonunique-target", "CREATE INDEX extra ON instruments(market, symbol DESC)"),
    ("nonunique-expression-partial", "CREATE INDEX extra ON instruments(lower(symbol)) WHERE market='TW'"),
    ("trigger-outside-audit", "CREATE TRIGGER extra BEFORE INSERT ON instruments WHEN NEW.symbol='Blocked' BEGIN SELECT RAISE(ABORT,'custom restriction'); END"),
]:
    SHAPES.append(shape(label, extras=(sql,), accepted=True))
SHAPES.append(shape("check-outside-audit", PAIR + ", CHECK(symbol != 'Blocked')", accepted=True))

for mode in ("VIRTUAL", "STORED"):
    for target in GENERATED_TARGETS:
        SHAPES.append(shape(f"generated-{target}-{mode.lower()}", generated=(target, mode)))
    for label, expression, sql in [
        ("alias-unique", "symbol", "CREATE UNIQUE INDEX extra ON instruments(generated_extra)"),
        ("unrelated-unique", "lower(name)", "CREATE UNIQUE INDEX extra ON instruments(generated_extra COLLATE NOCASE DESC) WHERE symbol='AbC'"),
        ("alias-nonunique", "symbol", "CREATE INDEX extra ON instruments(generated_extra)"),
    ]:
        SHAPES.append(shape(
            f"generated-extra-{label}-{mode.lower()}", extras=(sql,), accepted=True,
            extra_columns=f", generated_extra TEXT GENERATED ALWAYS AS ({expression}) {mode}",
        ))


@pytest.mark.parametrize("marker", ["alembic", "fallback", "both"])
@pytest.mark.parametrize("constraint,extras,extra_columns,generated,accepted", SHAPES)
def test_startup_instrument_unique_policy(tmp_path, monkeypatch, marker, constraint, extras, extra_columns, generated, accepted):
    path = build_database(tmp_path / "case.db", marker, constraint, extras, extra_columns, generated)
    before = fingerprint(path)
    original_connect = sqlite3.connect
    traces, historical_reads, forbidden_operations, bomb_hits = [], [], [], []

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

    def bomb(name):
        def fail(*args, **kwargs):
            bomb_hits.append(name)
            raise AssertionError(f"startup called forbidden {name}")
        return fail

    for owner, names in [
        (Base.metadata, ("create_all",)), (db, ("init_db",)),
        (migrations, ("upgrade_database", "_fallback_upgrade", "_fallback_upgrade_on_connection",
                      "_rebuild_instruments_if_needed", "preflight_instrument_identity", "rebuild_instrument_identity")),
        (identity_migration, ("preflight_instrument_identity", "rebuild_instrument_identity", "_identity",
                              "check_sqlite_migration_integrity")),
    ]:
        for name in names:
            monkeypatch.setattr(owner, name, bomb(f"{getattr(owner, '__name__', 'Base.metadata')}.{name}"))
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
            with pytest.raises(readiness.DatabaseReadinessError, match="instruments") as error:
                call()
            assert "API startup does not initialize, migrate or repair" in str(error.value)
        assert fingerprint(path) == before
    assert entered == ([True] if accepted else [])
    assert not historical_reads and not forbidden_operations and not bomb_hits
    assert len(traces) == 3
    for statements in traces:
        assert statements[:2] == ["PRAGMA query_only=ON", "BEGIN"]
        assert statements.count("BEGIN") == 1
        assert all(sql.startswith(("SELECT ", "PRAGMA ", "BEGIN")) for sql in statements)
        assert 'PRAGMA table_xinfo("instruments")' in statements
        if not generated:
            assert 'PRAGMA main.index_list("instruments")' in statements


@pytest.mark.parametrize("extra,extra_columns,constraint,second,allowed,startup_accepts", [
    pytest.param(None, "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), True, True, id="canonical-cross-exchange"),
    pytest.param("CREATE UNIQUE INDEX legacy ON instruments(market,symbol)", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), False, False, id="legacy-cross-exchange-conflict"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(exchange)", "", PAIR, (11, "TW", "TWSE", "DEF", "Other"), False, False, id="single-exchange-conflict"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(symbol,exchange)", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), True, False, id="reversed-policy"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(exchange DESC,symbol)", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), True, False, id="desc-policy"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(exchange,symbol,id)", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), True, False, id="superset-policy"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(market,symbol) WHERE 0", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), True, False, id="partial-false-policy"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(exchange,symbol COLLATE NOCASE)", "", PAIR, (11, "TW", "TWSE", "abc", "Other"), False, False, id="nocase-conflict"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(name)", "", PAIR, (11, "TW", "TPEx", "AbC", "Same"), False, True, id="unrelated-unique-outside-audit"),
    pytest.param("CREATE UNIQUE INDEX extra ON instruments(generated_extra)", ", generated_extra TEXT GENERATED ALWAYS AS (symbol) VIRTUAL", PAIR, (11, "TW", "TPEx", "AbC", "Same"), False, True, id="generated-alias-outside-audit"),
    pytest.param(None, "", PAIR + ", CHECK(symbol != 'Blocked')", (11, "TW", "TPEx", "Blocked", "Other"), False, True, id="check-outside-audit"),
    pytest.param("CREATE TRIGGER extra BEFORE INSERT ON instruments WHEN NEW.symbol='Blocked' BEGIN SELECT RAISE(ABORT,'custom restriction'); END", "", PAIR, (11, "TW", "TPEx", "Blocked", "Other"), False, True, id="trigger-outside-audit"),
])
def test_startup_instrument_policy_is_distinct_from_insert_semantics(tmp_path, extra, extra_columns, constraint, second, allowed, startup_accepts):
    path = build_database(tmp_path / "semantics.db", constraint=constraint, extras=(extra,) if extra else (), extra_columns=extra_columns)
    before = fingerprint(path)
    if startup_accepts:
        readiness.check_database_readiness(path)
    else:
        with pytest.raises(readiness.DatabaseReadinessError, match="instruments"):
            readiness.check_database_readiness(path)
    # All write attempts are on a new memory backup. FK enforcement is off;
    # this isolates uniqueness/custom restrictions, not valid production rows.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as memory:
            source.backup(memory)
            assert memory.execute("PRAGMA foreign_keys").fetchone() == (0,)
            memory.execute(INSERT, (10, "TW", "TWSE", "AbC", "Same"))
            if allowed:
                memory.execute(INSERT, second)
            else:
                with pytest.raises(sqlite3.IntegrityError):
                    memory.execute(INSERT, second)
            with pytest.raises(sqlite3.IntegrityError):
                memory.execute(INSERT, (12, "US", "TWSE", "AbC", "Different"))
    assert fingerprint(path) == before


@pytest.mark.parametrize("target", GENERATED_TARGETS)
@pytest.mark.parametrize("mode", ["VIRTUAL", "STORED"])
def test_generated_mapped_instrument_columns_reject_explicit_writes(tmp_path, target, mode):
    path = build_database(tmp_path / "generated.db", generated=(target, mode))
    before = fingerprint(path)
    with pytest.raises(readiness.DatabaseReadinessError, match="ordinary writable"):
        readiness.check_database_readiness(path)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as memory:
            source.backup(memory)
            columns = {row[1]: row for row in memory.execute('PRAGMA table_xinfo("instruments")')}
            assert columns[target][6] == (2 if mode == "VIRTUAL" else 3)
            with pytest.raises(sqlite3.OperationalError, match=f'cannot INSERT into generated column "{target}"'):
                memory.execute(INSERT, (10, "TW", "TWSE", "AbC", "Same"))
    assert fingerprint(path) == before
