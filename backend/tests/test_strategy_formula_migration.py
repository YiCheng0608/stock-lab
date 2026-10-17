"""0009: strategy rows are identified by formula sub-version (real SQLite files, no network)."""
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import api as api_module, database_readiness as readiness, domain, migrations
from app.db import enable_sqlite_foreign_keys
from app.models import IngestionRun, Instrument, MarketBar, Signal
from worker import pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "strategy_snapshots_pre_v2.json"
V1, V2 = domain.INSTITUTIONAL_FLOW_FORMULA_V1, domain.INSTITUTIONAL_FLOW_FORMULA_V2
HEAD = "0012_news_llm"
PREVIOUS = "0008_portfolio_share_integer"
# Alembic is optional in the bundled runtime; without it the upgrade is the SQLAlchemy fallback.
try:
    from alembic import command as _alembic_command  # noqa: F401  (backend/alembic is a namespace dir)
    HAS_ALEMBIC = True
except ImportError:
    HAS_ALEMBIC = False
ENTRIES = [
    pytest.param("alembic", marks=pytest.mark.skipif(not HAS_ALEMBIC, reason="Alembic is not installed")),
    "fallback",
]
# The worker's source gate reads fallback markers, so end-to-end sources use the fallback entry.
CREATED = "2026-09-01 00:00:00.000000"
IDENTITY = "id,name,version,kind,config_json,canonical_config_snapshot,created_at"
# What the schema looked like before 0009 (SQLAlchemy output for the old model).
LEGACY_DDL = (
    "CREATE TABLE strategy_versions (id INTEGER NOT NULL, name VARCHAR(60) NOT NULL, "
    "version VARCHAR(30) NOT NULL, kind VARCHAR(30) NOT NULL, config_json JSON NOT NULL, "
    "canonical_config_snapshot JSON NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
    "PRIMARY KEY (id), CONSTRAINT uq_strategy_version UNIQUE (name, version))",
    "CREATE INDEX ix_strategy_versions_name ON strategy_versions (name)",
)
READ_ONLY_IN_NEW_PROCESS = (
    "import json, sqlite3, sys; c = sqlite3.connect(sys.argv[1]); "
    "print(json.dumps(c.execute('SELECT id, name, version, formula_version, active "
    "FROM strategy_versions ORDER BY id').fetchall()))"
)


def pre_v2():
    """The three canonical snapshots as stored before the v2 institutional-flow formula."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("_source")
    return data


def raw_row(row_id, name, version, kind, config, snapshot, active=1):
    dump = lambda value: value if isinstance(value, str) else json.dumps(value)
    return (row_id, name, version, kind, dump(config), dump(snapshot), active, CREATED)


def legacy_rows():
    old, new = pre_v2(), domain.canonical_config_snapshot()
    drifted = copy.deepcopy(old["breakout_v1"])
    drifted["volume"]["minimum_signal_to_average_ratio"] = 1.5
    future = copy.deepcopy(new["breakout_v1"])
    future["confirmations"]["institutional_flow"]["formula_version"] = "institutional-flow/v9-future"
    declared_v2 = copy.deepcopy(new["breakout_v1"])
    declared_v2["name"] = "declared_v2"
    return [
        raw_row(1, "breakout_v1", "1.0.0", "breakout", old["breakout_v1"], old["breakout_v1"]),
        raw_row(2, "pullback_v1", "1.0.0", "pullback", old["pullback_v1"], old["pullback_v1"]),
        raw_row(3, "hot_group_v1", "1.0.0", "group_ranking", old["hot_group_v1"], old["hot_group_v1"]),
        raw_row(4, "breakout_v1", "1.0", "breakout", {"legacy": True}, {}),
        raw_row(5, "custom_rule", "1.0.0", "technical", {"x": 1}, {"x": 1}),
        raw_row(6, "declared_v2", "1.0.0", "breakout", declared_v2, declared_v2),
        raw_row(7, "declared_future", "1.0.0", "breakout", future, future),
        raw_row(8, "broken_json", "1.0.0", "technical", "{bad", "{bad"),
        raw_row(9, "drifted", "1.0.0", "breakout", old["breakout_v1"], drifted),
    ]


EXPECTED_FORMULA = {
    1: V1, 2: V1, 3: V1,
    4: "unclassified/empty_snapshot",
    5: "unclassified/unrecognized_snapshot",
    6: V2,
    7: "unclassified/unknown_formula_version",
    8: "unclassified/invalid_json",
    9: "unclassified/config_snapshot_mismatch",
}
EXPECTED_ACTIVE = {row_id: int(row_id == 6) for row_id in EXPECTED_FORMULA}


def old_signal(instrument_id, key, strategy_id, entry_type, day):
    return Signal(
        signal_key=key, signal_date=day, instrument_id=instrument_id, strategy_version_id=strategy_id,
        status="conditional", entry_type=entry_type, reference_entry=100.0, pullback_low=97.0,
        pullback_high=103.0, breakout_price=101.0, invalid_price=95.0, target_1=108.0, target_2=114.0,
        confidence=0.75, rationale="v1 result", data_cutoff=f"{day.isoformat()} 13:30 Asia/Taipei",
        rule_evidence_json={"strategy": key.rsplit("-", 2)[-2], "strategy_version": "1.0.0",
                            "inputs": {"institutional_flow_to_turnover_ratio_5d": 0.002}},
    )


def to_legacy_shape(path, rows, entry):
    """Rewrite a head database into the pre-0009 shape, keeping signals and FKs."""
    with closing(sqlite3.connect(path)) as raw:  # foreign keys are off on a raw connection
        raw.execute("DROP TABLE strategy_versions")
        for ddl in LEGACY_DDL:
            raw.execute(ddl)
        raw.executemany("INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        raw.execute("DROP TABLE IF EXISTS alembic_version")
        raw.execute("DROP TABLE IF EXISTS schema_migrations")
        if entry == "alembic":
            raw.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            raw.execute("INSERT INTO alembic_version VALUES (?)", (PREVIOUS,))
        else:
            raw.execute("CREATE TABLE schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)")
            raw.executemany(
                "INSERT INTO schema_migrations VALUES (?, '2026-09-01 00:00:00')", [(v,) for v in readiness.REVISIONS[:-1]]
            )
        raw.commit()


def build_legacy_db(path, entry, rows=None, signals=True, observe=None):
    """A database exactly as the pre-0009 code left it: v1 rows, old signals, old schema.

    ``observe(path)`` runs on the head-shaped file before the rewrite, because
    the new ORM cannot read the old table.
    """
    rows = legacy_rows() if rows is None else rows
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    migrations.upgrade_database(engine)
    if rows:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO strategy_versions (id, name, version, kind, config_json, canonical_config_snapshot, "
                "active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
    if signals:
        with Session(engine) as db:
            instrument = Instrument(symbol="OLD", name="Old", exchange="TWSE")
            db.add(instrument)
            db.flush()
            day = date(2026, 9, 1)
            db.add_all([
                old_signal(instrument.id, "analysis-TWSE-OLD-2026-09-01-breakout_v1-1.0.0", 1, "breakout", day),
                old_signal(instrument.id, "analysis-TWSE-OLD-2026-09-01-pullback_v1-1.0.0", 2, "pullback", day),
            ])
            db.commit()
    engine.dispose()
    observed = observe(path) if observe else None
    to_legacy_shape(path, rows, entry)
    return observed


def upgrade(path, entry, monkeypatch):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", path.parent / "absent.ini")
    try:
        migrations.upgrade_database(engine)
    finally:
        engine.dispose()


def query(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def dump(path):
    with closing(sqlite3.connect(path)) as connection:
        return list(connection.iterdump())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema_shape(path):
    columns = [(r[1], r[2].upper(), r[3], r[5]) for r in query(path, 'PRAGMA table_xinfo("strategy_versions")')]
    uniques = sorted(
        tuple(c[2] for c in query(path, f'PRAGMA index_xinfo("{i[1]}")') if c[5])
        for i in query(path, 'PRAGMA index_list("strategy_versions")') if i[2]
    )
    return columns, uniques


@pytest.mark.parametrize("entry", ENTRIES)
def test_legacy_rows_keep_their_identity_and_get_a_formula(tmp_path, monkeypatch, entry):
    path = tmp_path / "legacy.db"
    build_legacy_db(path, entry)
    assert [r[1] for r in query(path, 'PRAGMA table_xinfo("strategy_versions")')][:4] == ["id", "name", "version", "kind"]
    before = query(path, f"SELECT {IDENTITY} FROM strategy_versions ORDER BY id")
    signals_before = query(path, "SELECT * FROM signals ORDER BY id")
    assert len(before) == 9 and len(signals_before) == 2

    upgrade(path, entry, monkeypatch)

    assert query(path, f"SELECT {IDENTITY} FROM strategy_versions ORDER BY id") == before
    assert dict(query(path, "SELECT id, formula_version FROM strategy_versions")) == EXPECTED_FORMULA
    assert dict(query(path, "SELECT id, active FROM strategy_versions")) == EXPECTED_ACTIVE
    assert query(path, "SELECT * FROM signals ORDER BY id") == signals_before
    assert query(path, "PRAGMA foreign_key_check") == []
    assert query(path, "PRAGMA integrity_check") == [("ok",)]
    assert schema_shape(path)[1] == [("name", "version", "formula_version")]
    assert query(path, "SELECT name FROM sqlite_schema WHERE name = 'ix_strategy_versions_name'")
    assert not query(path, "SELECT name FROM sqlite_schema WHERE name LIKE '%formula_rebuild%'")
    if entry == "alembic":
        assert query(path, "SELECT version_num FROM alembic_version") == [(HEAD,)]
    else:
        assert HEAD in {r[0] for r in query(path, "SELECT version FROM schema_migrations")}
    readiness.check_database_readiness(path)

    # A different process reopens the file and reads the same classification.
    result = subprocess.run(
        [sys.executable, "-B", "-c", READ_ONLY_IN_NEW_PROCESS, str(path)], capture_output=True, text=True, check=True
    )
    assert {row[0]: (row[3], row[4]) for row in json.loads(result.stdout)} == {
        i: (EXPECTED_FORMULA[i], EXPECTED_ACTIVE[i]) for i in EXPECTED_FORMULA
    }


@pytest.mark.parametrize("entry", ENTRIES)
def test_migration_is_idempotent(tmp_path, monkeypatch, entry):
    path = tmp_path / "again.db"
    build_legacy_db(path, entry)
    upgrade(path, entry, monkeypatch)
    rows = query(path, "SELECT * FROM strategy_versions ORDER BY id")
    signals = query(path, "SELECT * FROM signals ORDER BY id")
    upgrade(path, entry, monkeypatch)
    upgrade(path, entry, monkeypatch)
    assert query(path, "SELECT * FROM strategy_versions ORDER BY id") == rows
    assert query(path, "SELECT * FROM signals ORDER BY id") == signals
    assert len(rows) == 9
    with closing(sqlite3.connect(path)) as raw:
        before = list(raw.iterdump())
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as connection:
        assert migrations.ensure_strategy_formula_version(connection) is False
        connection.rollback()
    engine.dispose()
    assert dump(path) == before


@pytest.mark.parametrize("entry", ENTRIES)
def test_failed_migration_leaves_no_half_state_and_can_be_retried(tmp_path, monkeypatch, entry):
    path = tmp_path / "bomb.db"
    build_legacy_db(path, entry)
    before = dump(path)
    original = migrations._strategy_formula_state
    calls = []

    def bomb(connection):
        calls.append(1)
        if len(calls) > 1:  # the post-rebuild check: the table was already dropped and renamed
            raise RuntimeError("injected after rebuild")
        return original(connection)

    monkeypatch.setattr(migrations, "_strategy_formula_state", bomb)
    with pytest.raises(RuntimeError, match="injected after rebuild"):
        upgrade(path, entry, monkeypatch)
    assert len(calls) == 2
    assert dump(path) == before
    assert "formula_version" not in [r[1] for r in query(path, 'PRAGMA table_xinfo("strategy_versions")')]

    monkeypatch.setattr(migrations, "_strategy_formula_state", original)
    upgrade(path, entry, monkeypatch)
    assert dict(query(path, "SELECT id, formula_version FROM strategy_versions")) == EXPECTED_FORMULA


def test_new_database_matches_a_migrated_one(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{fresh.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    migrations.upgrade_database(engine)
    engine.dispose()
    assert query(fresh, "SELECT * FROM strategy_versions") == []
    if HAS_ALEMBIC:
        assert query(fresh, "SELECT version_num FROM alembic_version") == [(HEAD,)]
    else:
        assert HEAD in {r[0] for r in query(fresh, "SELECT version FROM schema_migrations")}
    readiness.check_database_readiness(fresh)

    migrated = tmp_path / "migrated.db"
    build_legacy_db(migrated, "fallback", rows=[], signals=False)
    upgrade(migrated, "fallback", monkeypatch)
    assert schema_shape(migrated) == schema_shape(fresh)
    assert schema_shape(fresh)[1] == [("name", "version", "formula_version")]


def without_clock(value):
    """Drop the only per-call field in a signal payload: when the response was generated."""
    if isinstance(value, dict):
        return {k: without_clock(v) for k, v in value.items() if k != "response_generated_at"}
    if isinstance(value, list):
        return [without_clock(v) for v in value]
    return value


@pytest.mark.parametrize("entry", ENTRIES)
def test_old_signals_read_the_same_except_strategy_active(tmp_path, monkeypatch, entry):
    def observe(path):
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        try:
            with Session(engine) as db:
                version_columns = ("id", "name", "version", "kind", "config_json", "canonical_config_snapshot", "active", "created_at")
                rows = db.execute(text(
                    "SELECT s.*, " + ", ".join(f"v.{c} AS version_{c}" for c in version_columns)
                    + " FROM signals s LEFT JOIN strategy_versions v ON v.id = s.strategy_version_id ORDER BY s.id"
                )).mappings()
                candidates = [
                    {**{k: v for k, v in row.items() if not k.startswith("version_")},
                     "strategy": {c: row["version_" + c] for c in version_columns}}
                    for row in rows
                ]
                payloads = []
                for signal in db.scalars(select(Signal).order_by(Signal.id)):
                    payloads.append(without_clock(api_module.signal_dict(db, signal)))
            return {"reads": candidates, "api": payloads}
        finally:
            engine.dispose()

    path = tmp_path / "reads.db"
    before = build_legacy_db(path, entry, observe=observe)
    upgrade(path, entry, monkeypatch)
    after = observe(path)

    assert len(before["reads"]) == len(after["reads"]) == 2
    assert [r["strategy"]["active"] for r in before["reads"]] == [True, True]
    assert [r["strategy"]["active"] for r in after["reads"]] == [False, False]
    for observation in (before, after):
        for read in observation["reads"]:
            read["strategy"].pop("active")
    assert after == before
    api = after["api"]
    assert [s["strategy"]["version"] for s in api] == ["1.0.0", "1.0.0"]
    assert all(s["strategy"]["canonical_config_snapshot"] == pre_v2()[s["strategy"]["name"]] for s in api)


def snapshot_case(name, version, config, snapshot):
    dump = lambda value: value if isinstance(value, str) else json.dumps(value)
    return name, version, dump(config), dump(snapshot)


def classification_cases():
    old, new = pre_v2(), domain.canonical_config_snapshot()
    bool_for_float = json.dumps(old["breakout_v1"]).replace('"minimum_excess_return": 0.0', '"minimum_excess_return": false')
    assert bool_for_float != json.dumps(old["breakout_v1"])
    mismatched_formulas = copy.deepcopy(new["hot_group_v1"])
    mismatched_formulas["components"]["institutional_flow"]["formula"]["formula_version"] = V1
    two_places = copy.deepcopy(new["breakout_v1"])
    two_places["components"] = {"institutional_flow": {"formula": {"formula_version": V1}}}
    return [
        (snapshot_case("breakout_v1", "1.0.0", old["breakout_v1"], old["breakout_v1"]), V1),
        (snapshot_case("pullback_v1", "1.0.0", old["pullback_v1"], old["pullback_v1"]), V1),
        (snapshot_case("hot_group_v1", "1.0.0", old["hot_group_v1"], old["hot_group_v1"]), V1),
        (snapshot_case("breakout_v1", "1.0.0", new["breakout_v1"], new["breakout_v1"]), V2),
        (snapshot_case("hot_group_v1", "1.0.0", new["hot_group_v1"], new["hot_group_v1"]), V2),
        (snapshot_case("hot_group_v1", "1.0.0", mismatched_formulas, mismatched_formulas), V1),
        # Empty, absent or malformed snapshots are named, never guessed.
        (snapshot_case("breakout_v1", "1.0.0", old["breakout_v1"], {}), "unclassified/empty_snapshot"),
        (snapshot_case("breakout_v1", "1.0.0", {}, {}), "unclassified/empty_snapshot"),
        (snapshot_case("breakout_v1", "1.0.0", old["breakout_v1"], "null"), "unclassified/empty_snapshot"),
        (snapshot_case("breakout_v1", "1.0.0", old["breakout_v1"], "[1]"), "unclassified/invalid_json"),
        (snapshot_case("breakout_v1", "1.0.0", "{bad", old["breakout_v1"]), "unclassified/invalid_json"),
        (("breakout_v1", "1.0.0", None, json.dumps(old["breakout_v1"])), "unclassified/invalid_json"),
        (snapshot_case("breakout_v1", "1.0.0", old["pullback_v1"], old["breakout_v1"]), "unclassified/config_snapshot_mismatch"),
        # A pre-v2 digest only counts under its own name and version.
        (snapshot_case("pullback_v1", "1.0.0", old["breakout_v1"], old["breakout_v1"]), "unclassified/unrecognized_snapshot"),
        (snapshot_case("breakout_v1", "1.0", old["breakout_v1"], old["breakout_v1"]), "unclassified/unrecognized_snapshot"),
        (snapshot_case("breakout_v1", "1.0.0", bool_for_float, bool_for_float), "unclassified/unrecognized_snapshot"),
        (snapshot_case("x", "1.0.0", {"anything": 1}, {"anything": 1}), "unclassified/unrecognized_snapshot"),
        # Declared but unknown, or declared inconsistently, is not the current formula either.
        (snapshot_case("breakout_v1", "1.0.0", two_places, two_places), "unclassified/unknown_formula_version"),
    ]


@pytest.mark.parametrize("case,expected", classification_cases())
def test_classify_strategy_formula(case, expected):
    assert migrations.classify_strategy_formula(*case) == expected


def test_pre_v2_digest_list_matches_the_fixture_snapshots():
    digests = {
        hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(): (
            snapshot["name"], snapshot["version"])
        for snapshot in pre_v2().values()
    }
    assert digests == migrations._PRE_V2_CANONICAL_DIGESTS
    current = domain.canonical_config_snapshot()
    assert not {name for name, _ in digests.values()} - set(current)
    assert all(
        migrations.classify_strategy_formula(c["name"], c["version"], json.dumps(c), json.dumps(c)) == V2
        for c in current.values()
    )


def raw_engine(path):
    return create_engine(f"sqlite:///{path.as_posix()}")


def test_migration_refuses_unsupported_shapes_without_changing_them(tmp_path):
    def legacy_file(name, extra_ddl=(), ddl=LEGACY_DDL):
        path = tmp_path / name
        with closing(sqlite3.connect(path)) as raw:
            for statement in ddl:
                raw.execute(statement)
            if ddl is LEGACY_DDL:
                raw.execute(
                    "INSERT INTO strategy_versions (id, name, version, kind, config_json, canonical_config_snapshot, "
                    "active, created_at) VALUES (1, 'a', '1', 'k', '{}', '{}', 1, 'x')"
                )
            for statement in extra_ddl:
                raw.execute(statement)
            raw.commit()
        return path

    def attempt(path, match, foreign_keys=False):
        before = dump(path)
        engine = raw_engine(path)
        with engine.connect() as connection:
            connection.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
            with pytest.raises(RuntimeError, match=match):
                migrations.ensure_strategy_formula_version(connection)
            connection.rollback()
        engine.dispose()
        assert dump(path) == before

    attempt(legacy_file("fk.db"), "foreign_keys=OFF", foreign_keys=True)
    attempt(legacy_file("scratch.db", ['CREATE TABLE "strategy_versions__formula_rebuild_old" (x)']), "occupied scratch")
    attempt(legacy_file("view.db", ["CREATE VIEW v AS SELECT name FROM strategy_versions"]), "dependent view")
    attempt(legacy_file("extra.db", ["ALTER TABLE strategy_versions ADD COLUMN note TEXT"]), "unsupported legacy columns")
    mixed = (
        "CREATE TABLE strategy_versions (id INTEGER NOT NULL, name VARCHAR(60) NOT NULL, version VARCHAR(30) NOT NULL, "
        "formula_version VARCHAR(80) NOT NULL, kind VARCHAR(30) NOT NULL, config_json JSON NOT NULL, "
        "canonical_config_snapshot JSON NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
        "PRIMARY KEY (id), CONSTRAINT uq_strategy_version UNIQUE (name, version))",
    )
    attempt(legacy_file("mixed.db", ddl=mixed), "unique identity is not")
    attempt(legacy_file("noid.db", ddl=("CREATE TABLE strategy_versions (id INTEGER PRIMARY KEY, name TEXT)",)), "unique identity")


def test_helper_migrates_a_bare_legacy_table_without_a_signals_table(tmp_path):
    path = tmp_path / "bare.db"
    with closing(sqlite3.connect(path)) as raw:
        for ddl in LEGACY_DDL:
            raw.execute(ddl)
        raw.executemany("INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", legacy_rows())
        raw.commit()
    engine = raw_engine(path)
    with engine.begin() as connection:
        assert migrations.ensure_strategy_formula_version(connection) is True
    with engine.begin() as connection:
        assert migrations.ensure_strategy_formula_version(connection) is False
    engine.dispose()
    assert dict(query(path, "SELECT id, formula_version FROM strategy_versions")) == EXPECTED_FORMULA


# --- worker behaviour on a migrated database -------------------------------------------------


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    path = tmp_path / "migrated.db"
    build_legacy_db(path, "fallback")
    upgrade(path, "fallback", monkeypatch)
    engine = raw_engine(path)
    enable_sqlite_foreign_keys(engine)
    yield path, engine
    engine.dispose()


def test_ensure_strategies_creates_current_rows_and_never_touches_older_ones(migrated):
    path, engine = migrated
    legacy = query(path, "SELECT * FROM strategy_versions ORDER BY id")
    with Session(engine) as db:
        first = pipeline._ensure_strategies(db)
        db.commit()
        ids = {key: row.id for key, row in first.items()}
        assert set(first) == {"breakout_v1", "pullback_v1", "hot_group_v1"}
        assert all(row.formula_version == V2 and row.active is True for row in first.values())
        assert not set(ids.values()) & {1, 2, 3, 4, 5, 6, 7, 8, 9}
        assert {key: row.id for key, row in pipeline._ensure_strategies(db).items()} == ids
    assert query(path, "SELECT * FROM strategy_versions WHERE id <= 9 ORDER BY id") == legacy
    assert len(query(path, "SELECT * FROM strategy_versions")) == 12
    # The new rows carry the current canonical snapshot.
    for key, row_id in ids.items():
        stored = query(path, f"SELECT canonical_config_snapshot, config_json FROM strategy_versions WHERE id = {row_id}")[0]
        assert json.loads(stored[0]) == json.loads(stored[1]) == domain.canonical_config_snapshot()[key]


def test_empty_snapshot_row_is_no_longer_backfilled_or_reused(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    empty = [raw_row(1, "breakout_v1", "1.0.0", "breakout", {"kept": True}, {})]
    build_legacy_db(path, "fallback", rows=empty, signals=False)
    upgrade(path, "fallback", monkeypatch)
    assert query(path, "SELECT formula_version, active FROM strategy_versions") == [("unclassified/empty_snapshot", 0)]
    engine = raw_engine(path)
    with Session(engine) as db:
        rows = pipeline._ensure_strategies(db)
        db.commit()
        assert rows["breakout_v1"].id != 1
    engine.dispose()
    assert query(path, "SELECT canonical_config_snapshot, config_json FROM strategy_versions WHERE id = 1") == [("{}", '{"kept": true}')]


@pytest.mark.parametrize("tamper", ["config_json", "canonical_config_snapshot", "bool_for_float", "kind"])
def test_ensure_strategies_refuses_a_current_row_that_differs_from_canonical(migrated, tamper):
    path, engine = migrated
    with Session(engine) as db:
        row_id = pipeline._ensure_strategies(db)["breakout_v1"].id
        db.commit()
    canonical = json.dumps(domain.canonical_config_snapshot()["breakout_v1"])
    with closing(sqlite3.connect(path)) as raw:
        if tamper == "kind":
            raw.execute("UPDATE strategy_versions SET kind = 'pullback' WHERE id = ?", (row_id,))
        elif tamper == "bool_for_float":
            changed = canonical.replace('"minimum_excess_return": 0.0', '"minimum_excess_return": false')
            assert changed != canonical
            raw.execute("UPDATE strategy_versions SET canonical_config_snapshot = ? WHERE id = ?", (changed, row_id))
        else:
            raw.execute(f"UPDATE strategy_versions SET {tamper} = '{{\"bad\": true}}' WHERE id = ?", (row_id,))
        raw.commit()
    with Session(engine) as db:
        with pytest.raises(pipeline.StrategyVersionError) as error:
            pipeline._ensure_strategies(db)
    assert error.value.code == "strategy_snapshot_mismatch"
    assert f"id {row_id}" in str(error.value)


def test_signal_formula_guard_names_the_conflict(migrated):
    _, engine = migrated
    with Session(engine) as db:
        current = pipeline._ensure_strategies(db)["breakout_v1"]
        db.flush()
        old = db.scalar(select(Signal).where(Signal.strategy_version_id == 1))
        with pytest.raises(pipeline.StrategyVersionError) as error:
            pipeline._require_same_formula(db, old, current)
        assert error.value.code == "signal_formula_conflict" and V1 in str(error.value)
        old.strategy_version_id = None
        with pytest.raises(pipeline.StrategyVersionError, match="unattributed") as error:
            pipeline._require_same_formula(db, old, current)
        assert error.value.code == "signal_formula_conflict"
        old.strategy_version_id = current.id
        pipeline._require_same_formula(db, old, current)
        db.rollback()


# --- end to end through the real analysis worker ---------------------------------------------


def e2e_source(tmp_path, old_signal_day):
    """Pre-0009 database with bars for two same-symbol instruments and v1-era signals."""
    old = pre_v2()
    rows = [
        raw_row(1, "breakout_v1", "1.0.0", "breakout", old["breakout_v1"], old["breakout_v1"]),
        raw_row(2, "pullback_v1", "1.0.0", "pullback", old["pullback_v1"], old["pullback_v1"]),
        raw_row(3, "hot_group_v1", "1.0.0", "group_ranking", old["hot_group_v1"], old["hot_group_v1"]),
    ]
    source = tmp_path / "source.db"
    build_legacy_db(source, "fallback", rows=rows, signals=False)
    engine = raw_engine(source)
    enable_sqlite_foreign_keys(engine)
    with Session(engine) as db:
        for exchange in ("TWSE", "TPEX"):
            instrument = Instrument(symbol="SAME", name="Synthetic", exchange=exchange)
            db.add(instrument)
            db.flush()
            for index in range(65):
                day = date(2026, 5, 1) + timedelta(days=index)
                close = 90 + index * .1
                db.add(MarketBar(instrument_id=instrument.id, trading_date=day, open=close, high=close + 1, low=close - 1,
                                 close=close, adj_close=close, volume=100 + index, turnover=10000))
            if exchange == "TWSE":
                twse = instrument.id
        db.add(IngestionRun(run_type="collect", source="official", run_date=day, data_as_of=day.isoformat(), status="success"))
        stamp = old_signal_day.isoformat()
        db.add_all([
            old_signal(twse, f"analysis-TWSE-SAME-{stamp}-breakout_v1-1.0.0", 1, "breakout", old_signal_day),
            old_signal(twse, f"analysis-TWSE-SAME-{stamp}-pullback_v1-1.0.0", 2, "pullback", old_signal_day),
        ])
        db.commit()
    engine.dispose()
    return source, day


def run_worker(source):
    """Run the analysis step in one transaction; commit only a successful run."""
    def run():
        engine = raw_engine(source)
        enable_sqlite_foreign_keys(engine)
        try:
            with Session(engine) as db:
                try:
                    result = pipeline._analyze_session(db)
                except Exception:
                    db.rollback()
                    raise
                db.commit()
                return result
        finally:
            engine.dispose()
    return source, run


def test_worker_runs_on_v2_rows_and_keeps_older_dates_on_their_v1_rows(tmp_path, monkeypatch):
    source, latest = e2e_source(tmp_path, date(2026, 6, 1))
    upgrade(source, "fallback", monkeypatch)
    old_signals = query(source, "SELECT * FROM signals ORDER BY id")
    legacy_rows_before = query(source, "SELECT * FROM strategy_versions ORDER BY id")
    target, run = run_worker(source)

    result = run()

    # signals_upserted counts instruments; the four signal rows are checked below.
    assert result["status"] == "success" and result["signals_upserted"] == 2
    assert query(target, "SELECT * FROM signals WHERE id <= 2 ORDER BY id") == old_signals
    assert query(target, "SELECT * FROM strategy_versions WHERE id <= 3 ORDER BY id") == legacy_rows_before
    new = query(target, "SELECT s.signal_key, v.id, v.formula_version, v.active, v.canonical_config_snapshot "
                        "FROM signals s JOIN strategy_versions v ON v.id = s.strategy_version_id WHERE s.id > 2")
    assert len(new) == 4
    canonical = domain.canonical_config_snapshot()
    for key, version_id, formula, active, snapshot in new:
        assert key.startswith("analysis-") and latest.isoformat() in key
        assert version_id > 3 and formula == V2 and active == 1
        assert json.loads(snapshot) == canonical[key.rsplit("-", 2)[-2]]
    # The old rows are still the ones the old signals point at, and still read as v1.
    assert query(target, "SELECT strategy_version_id FROM signals WHERE id <= 2 ORDER BY id") == [(1,), (2,)]
    assert {r[0] for r in query(target, "SELECT formula_version FROM strategy_versions WHERE id <= 3")} == {V1}


def test_worker_refuses_to_overwrite_a_v1_signal_of_the_same_day(tmp_path, monkeypatch):
    source, latest = e2e_source(tmp_path, date(2026, 5, 1) + timedelta(days=64))
    upgrade(source, "fallback", monkeypatch)
    old_signals = query(source, "SELECT * FROM signals ORDER BY id")
    target, run = run_worker(source)
    before = sha(target)

    with pytest.raises(pipeline.StrategyVersionError) as error:
        run()

    assert error.value.code == "signal_formula_conflict"
    assert sha(target) == before
    assert query(target, "SELECT * FROM signals ORDER BY id") == old_signals
    assert len(query(target, "SELECT * FROM strategy_versions")) == 3
