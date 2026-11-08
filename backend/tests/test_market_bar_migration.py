"""0029 (Issue #552): market_bars keeps every row while open/high/low/volume become nullable."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app.market_bar_migration import NEW_COLUMNS, needs_upgrade, upgrade_market_bars

# market_bars as 0028 left it (NOT NULL prices and volume, no 0029 column).
OLD_DDL = (
    "CREATE TABLE market_bars (id INTEGER NOT NULL, instrument_id INTEGER NOT NULL, "
    "trading_date DATE NOT NULL, open FLOAT NOT NULL, high FLOAT NOT NULL, low FLOAT NOT NULL, "
    "close FLOAT NOT NULL, adj_close FLOAT NOT NULL, volume INTEGER NOT NULL, turnover FLOAT NOT NULL, "
    "turnover_status VARCHAR(20) DEFAULT 'unknown' NOT NULL, turnover_reason VARCHAR(40), "
    "source VARCHAR(120) NOT NULL, data_as_of DATETIME, collected_at DATETIME NOT NULL, "
    "raw_payload_id INTEGER, is_suspended BOOLEAN DEFAULT '0' NOT NULL, PRIMARY KEY (id), "
    "CONSTRAINT uq_market_bar_day UNIQUE (instrument_id, trading_date), "
    "FOREIGN KEY(instrument_id) REFERENCES instruments (id), "
    "FOREIGN KEY(raw_payload_id) REFERENCES raw_payloads (id))"
)
OLD_INDEXES = (
    "CREATE INDEX ix_market_bar_instrument_date ON market_bars (instrument_id, trading_date)",
    "CREATE INDEX ix_market_bars_instrument_id ON market_bars (instrument_id)",
    "CREATE INDEX ix_market_bars_trading_date ON market_bars (trading_date)",
    "CREATE INDEX ix_market_bars_raw_payload_id ON market_bars (raw_payload_id)",
)
ROWS = (
    (
        1,
        1,
        "2026-11-05",
        41.0,
        42.0,
        40.5,
        41.5,
        41.5,
        1200,
        49800.0,
        "available",
        None,
        "twse_daily",
        "2026-11-05 00:00:00",
        "2026-11-05 10:00:00",
        7,
        0,
    ),
    (
        2,
        9,
        "2026-11-05",
        41574.72,
        41574.72,
        41574.72,
        41574.72,
        41574.72,
        0,
        0.0,
        "unavailable",
        "synthetic_index",
        "twse_index",
        "2026-11-05 00:00:00",
        "2026-11-05 10:00:00",
        8,
        0,
    ),
)


def _old_database(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE instruments (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE raw_payloads (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(OLD_DDL)
        for sql in OLD_INDEXES:
            connection.exec_driver_sql(sql)
        connection.exec_driver_sql(
            "INSERT INTO market_bars VALUES "
            + ", ".join("(" + ", ".join("?" * len(ROWS[0])) + ")" for _ in ROWS),
            tuple(value for row in ROWS for value in row),
        )
    return engine


def _columns(connection):
    return {
        row[1]: row
        for row in connection.exec_driver_sql("PRAGMA table_info(market_bars)")
    }


def _indexes(connection):
    return {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='market_bars' "
            "AND sql IS NOT NULL"
        )
    }


def test_the_old_table_is_rebuilt_nullable_with_every_row_and_index(tmp_path):
    engine = _old_database(tmp_path / "old.db")
    with engine.begin() as connection:
        before = connection.exec_driver_sql(
            "SELECT * FROM market_bars ORDER BY id"
        ).all()
        assert needs_upgrade(connection)
        assert upgrade_market_bars(connection) is True
    with engine.begin() as connection:
        columns = _columns(connection)
        for name in ("open", "high", "low", "volume"):
            assert columns[name][3] == 0, name
        assert columns["close"][3] == 1
        assert set(NEW_COLUMNS) <= set(columns)
        names = [
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(market_bars)")
        ]
        old = [name for name in names if name not in NEW_COLUMNS]
        after = connection.exec_driver_sql(
            f"SELECT {', '.join(old)} FROM market_bars ORDER BY id"
        ).all()
        assert [tuple(row) for row in after] == [tuple(row) for row in before]
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM market_bars WHERE price_reason IS NOT NULL "
                "OR volume_raw_payload_id IS NOT NULL OR contract_month IS NOT NULL "
                "OR open_interest IS NOT NULL OR settlement_price IS NOT NULL"
            ).scalar()
            == 0
        )
        assert set(i for i in _indexes(connection)) >= {
            "ix_market_bar_instrument_date",
            "ix_market_bars_instrument_id",
            "ix_market_bars_trading_date",
            "ix_market_bars_raw_payload_id",
            "ix_market_bars_volume_raw_payload_id",
        }
        # The unique day key survives the rebuild.
        unique = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='market_bars'"
        ).scalar()
        assert "uq_market_bar_day" in unique
        assert "_market_bars_0029" not in unique
        # An index day without open/high/low or volume is now storable.
        connection.execute(
            text(
                "INSERT INTO market_bars (instrument_id, trading_date, open, high, low, close, "
                "adj_close, volume, turnover, turnover_status, source, collected_at, "
                "is_suspended, price_reason) VALUES (9, '2026-11-06', NULL, NULL, NULL, 39701.64, "
                "39701.64, NULL, 0, 'unavailable', 'twse_index_ohlcv', '2026-11-06', 0, "
                "'source_missing_ohlc')"
            )
        )
        assert not needs_upgrade(connection)
        assert upgrade_market_bars(connection) is False


def test_a_nullable_table_only_gets_the_missing_columns(tmp_path):
    engine = _old_database(tmp_path / "partial.db")
    with engine.begin() as connection:
        upgrade_market_bars(connection)
        connection.exec_driver_sql(
            "ALTER TABLE market_bars DROP COLUMN settlement_price"
        )
        rows = connection.exec_driver_sql("SELECT count(*) FROM market_bars").scalar()
        assert needs_upgrade(connection)
        assert upgrade_market_bars(connection) is True
        assert "settlement_price" in _columns(connection)
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM market_bars").scalar()
            == rows
        )


def test_a_column_outside_the_model_stops_the_rebuild(tmp_path):
    engine = _old_database(tmp_path / "extra.db")
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE market_bars ADD COLUMN local_note TEXT")
    with engine.begin() as connection, pytest.raises(RuntimeError, match="local_note"):
        upgrade_market_bars(connection)
    with engine.begin() as connection:
        assert "local_note" in _columns(connection)
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM market_bars").scalar() == 2
        )


def test_a_database_without_market_bars_is_left_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.begin() as connection:
        assert not needs_upgrade(connection)
        assert upgrade_market_bars(connection) is False
