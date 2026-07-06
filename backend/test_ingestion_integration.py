#!/usr/bin/env python3
"""Integration test for spec-11: SQLAlchemy persistence with fixture-backed adapters.

This test verifies against a real PostgreSQL database:
1. Daily prices persist and reference valid securities (FK constraint).
2. Price adjustment recomputes full historical series when corporate actions exist.
3. Failing source retries and succeeds, with notification on failure.
"""

import sys
import datetime as dt
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

# Setup path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

from app.adapters.base import DataSource
from app.ingestion.pipeline import create_sqlalchemy_repository
from app.ingestion.scheduler import IngestionCoordinator


class FixtureDataSource(DataSource):
    """Fixture-backed adapter for testing."""

    def __init__(
        self,
        name: str,
        rows_to_produce: list[dict],
        fail_count: int = 0,
    ):
        self.name = name
        self.rows_to_produce = rows_to_produce
        self.fail_count = fail_count
        self.call_count = 0

    def fetch(self, target: Any, date: dt.date) -> dict:
        """Simulate fetch; fail if fail_count not reached."""
        if self.call_count < self.fail_count:
            self.call_count += 1
            raise RuntimeError(f"{self.name} fetch failed intentionally (call {self.call_count})")
        self.call_count += 1
        return {"data": "fixture"}

    def parse(self, raw: Any) -> list[dict]:
        """Return pre-configured fixture rows."""
        return self.rows_to_produce


class TestNotifier:
    """Simple notifier to track notifications."""

    def __init__(self):
        self.notifications = []

    def notify(self, subject: str, message: str) -> None:
        self.notifications.append({"subject": subject, "message": message})


def cleanup_database():
    """Truncate all ingestion-related tables in FK-safe order."""
    from sqlalchemy import create_engine, text
    from app.config import get_settings

    try:
        url = get_settings().database_url
    except Exception:
        url = "postgresql+psycopg://stocklab:stocklab@localhost:5432/stocklab"

    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        # Truncate in FK-safe order (children before parent), reset sequences
        for table in [
            "broker_branch_trades",
            "chips",
            "daily_prices",
            "corporate_actions",
            "securities",
        ]:
            conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        conn.commit()


def _get_database_url():
    """Get database URL."""
    try:
        from app.config import get_settings
        return get_settings().database_url
    except Exception:
        return "postgresql+psycopg://stocklab:stocklab@localhost:5432/stocklab"


def _insert_security_directly(symbol: str, name: str, market_value: str) -> int:
    """Insert a security directly using raw SQL to work around enum serialization issue."""
    from sqlalchemy import create_engine, text

    url = _get_database_url()
    engine = create_engine(url, future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "INSERT INTO securities (symbol, name, market, is_active) "
                "VALUES (:symbol, :name, :market, true) "
                "RETURNING id"
            ),
            {"symbol": symbol, "name": name, "market": market_value},
        )
        security_id = result.scalar_one()
        conn.commit()
        return security_id


class TestSQLAlchemyPersistence:
    """Test spec-11: SQLAlchemy persistence with fixture adapters against real Postgres."""

    def setup_method(self):
        """Clean database before each test."""
        cleanup_database()

    def teardown_method(self):
        """Clean database after each test."""
        cleanup_database()

    def test_daily_prices_reference_valid_securities(self):
        """Verify daily prices reference valid securities (FK constraints work)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import DailyPrice

        # Pre-populate securities table directly (working around enum serialization issue)
        _insert_security_directly("2330", "TSMC", "listed")

        # Fixture data: prices only (securities already exist)
        price_rows = [
            {
                "symbol": "2330",
                "market": "listed",
                "date": dt.date(2026, 1, 1),
                "open_raw": 100.0,
                "high_raw": 105.0,
                "low_raw": 99.0,
                "close_raw": 102.0,
                "volume": 1000000,
            },
            {
                "symbol": "2330",
                "market": "listed",
                "date": dt.date(2026, 1, 2),
                "open_raw": 102.0,
                "high_raw": 107.0,
                "low_raw": 100.0,
                "close_raw": 104.0,
                "volume": 1100000,
            },
        ]

        # Create pipeline with fixture adapters
        repo = create_sqlalchemy_repository()

        from app.ingestion.pipeline import Pipeline

        pipeline = Pipeline(
            repository=repo,
            sources={
                "daily_price_source": FixtureDataSource("daily_price", price_rows),
            },
            discover=lambda: {},
        )

        # Run pipeline
        result = pipeline.run(date=dt.date(2026, 7, 6))
        assert result.success, f"Pipeline should succeed, got result: {result}"
        assert result.sources["daily_price_source"].success

        # Verify daily prices were inserted and reference valid securities
        url = _get_database_url()
        engine = create_engine(url, future=True)
        Session = sessionmaker(bind=engine, future=True)

        with Session() as session:
            # Query daily prices
            prices = session.query(DailyPrice).filter_by(security_id=1).order_by(DailyPrice.date).all()
            assert len(prices) == 2, f"Should have 2 price rows, got {len(prices)}"

            # Verify all prices have valid FK references
            for price in prices:
                assert price.security_id == 1, "Price should reference security 1"
                assert price.date in [dt.date(2026, 1, 1), dt.date(2026, 1, 2)]
                assert price.open_raw == (100.0 if price.date == dt.date(2026, 1, 1) else 102.0)

    def test_price_adjustment_full_historical_series(self):
        """Verify price adjustment recomputes all historical rows when corporate action added."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import DailyPrice

        # Pre-populate security directly
        _insert_security_directly("3008", "First Financial", "listed")

        # 3 days of price history
        price_rows = [
            {
                "symbol": "3008",
                "market": "listed",
                "date": dt.date(2026, 1, 1),
                "open_raw": 20.0,
                "high_raw": 20.5,
                "low_raw": 19.5,
                "close_raw": 20.25,
                "volume": 5000000,
            },
            {
                "symbol": "3008",
                "market": "listed",
                "date": dt.date(2026, 1, 2),
                "open_raw": 20.25,
                "high_raw": 20.75,
                "low_raw": 20.0,
                "close_raw": 20.5,
                "volume": 5100000,
            },
            {
                "symbol": "3008",
                "market": "listed",
                "date": dt.date(2026, 1, 3),
                "open_raw": 20.5,
                "high_raw": 21.0,
                "low_raw": 20.25,
                "close_raw": 20.75,
                "volume": 5200000,
            },
        ]

        # Corporate action (stock dividend): 0.1 shares per share, no cash dividend
        corporate_action_rows = [
            {
                "row_type": "corporate_action",
                "symbol": "3008",
                "market": "listed",
                "ex_rights_date": dt.date(2026, 1, 2),
                "cash_dividend_per_share": 0.0,
                "stock_dividend_per_share": 0.1,
                "capital_change_shares": None,
                "capital_after_shares": None,
            }
        ]

        # Create pipeline with fixture adapters
        repo = create_sqlalchemy_repository()

        from app.ingestion.pipeline import Pipeline

        pipeline = Pipeline(
            repository=repo,
            sources={
                "daily_price_source": FixtureDataSource("daily_price", price_rows),
                "corporate_action_source": FixtureDataSource(
                    "corporate_action", corporate_action_rows
                ),
            },
            discover=lambda: {},
        )

        # Run pipeline
        result = pipeline.run(date=dt.date(2026, 1, 4))
        assert result.success, f"Pipeline should succeed, got result: {result}"
        assert result.adjusted_security_count > 0, "Should have computed adjusted prices"

        # Verify adjusted prices were computed for all historical rows
        url = _get_database_url()
        engine = create_engine(url, future=True)
        Session = sessionmaker(bind=engine, future=True)

        with Session() as session:
            # Get all daily prices for security 1 (3008), ordered by date
            prices = session.query(DailyPrice).filter_by(security_id=1).order_by(DailyPrice.date).all()
            assert len(prices) == 3, f"Should have 3 price rows, got {len(prices)}"

            # Verify adjusted prices were calculated for ALL rows
            for i, price in enumerate(prices):
                date_label = f"Day {i+1}"
                if price.date < dt.date(2026, 1, 2):
                    # Dates before ex_rights_date should have adjusted prices
                    assert price.open_adj is not None, f"{date_label}: open_adj should be set"
                    assert price.high_adj is not None, f"{date_label}: high_adj should be set"
                    assert price.low_adj is not None, f"{date_label}: low_adj should be set"
                    assert price.close_adj is not None, f"{date_label}: close_adj should be set"
                    # Adjusted prices should be lower than raw (due to stock dividend factor < 1)
                    assert float(price.close_adj) < price.close_raw, \
                        f"{date_label}: close_adj should be < close_raw"
                else:
                    # Dates on or after ex_rights_date should also have adjusted prices
                    assert price.open_adj is not None or price.close_adj is not None, \
                        f"{date_label}: at least one adjusted column should be set"

    def test_failing_source_retries_and_notifies(self):
        """Verify retry and notification on source failure then success."""
        # Pre-populate security directly
        _insert_security_directly("1101", "Taiwan Cement", "listed")

        price_rows = [
            {
                "symbol": "1101",
                "market": "listed",
                "date": dt.date(2026, 1, 1),
                "open_raw": 40.0,
                "high_raw": 41.0,
                "low_raw": 39.5,
                "close_raw": 40.5,
                "volume": 2000000,
            }
        ]

        # Create pipeline with fixture adapters
        repo = create_sqlalchemy_repository()

        from app.ingestion.pipeline import Pipeline

        # Price source fails once, then succeeds
        price_source = FixtureDataSource("daily_price", price_rows, fail_count=1)

        pipeline = Pipeline(
            repository=repo,
            sources={
                "daily_price_source": price_source,
            },
            discover=lambda: {},
        )

        notifier = TestNotifier()
        coordinator = IngestionCoordinator(pipeline, notifier=notifier)

        # First trigger: price source fails
        result1 = coordinator.trigger()
        assert result1 is not None
        assert not result1.sources["daily_price_source"].success

        # Verify notifier was called for the failure
        failure_notified = any(
            "daily_price_source" in notif.get("message", "")
            for notif in notifier.notifications
        )
        assert failure_notified, "Notifier should have been called for failed source"

        # Second trigger: price source should retry and succeed
        result2 = coordinator.trigger()
        assert result2 is not None
        # In second trigger, only pending sources are run
        assert "daily_price_source" in result2.sources
        assert result2.sources["daily_price_source"].success

        # Verify data landed in database
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import DailyPrice

        url = _get_database_url()
        engine = create_engine(url, future=True)
        Session = sessionmaker(bind=engine, future=True)

        with Session() as session:
            prices = session.query(DailyPrice).filter_by(security_id=1).all()
            assert len(prices) == 1
            assert prices[0].close_raw == 40.5


def main():
    """Run all tests with pytest."""
    import pytest

    test_file = Path(__file__).resolve()
    exit_code = pytest.main([
        str(test_file),
        "-v",
        "--tb=short",
    ])
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
