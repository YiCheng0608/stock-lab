#!/usr/bin/env python3
"""Test spec-11: APScheduler coordination, retry logic, and adjustment recalculation.

This test verifies:
1. Failed sources are retried on next hourly trigger; succeeded sources are not re-fetched.
2. Once all sources succeed, further triggers do not re-run any source (all_green behavior).
3. Notifier is invoked when a source fails.
4. Securities/basic-data sources run before FK-dependent sources (ordering).
5. Price adjustment step receives full historical price series, not just new rows.
"""

import sys
import datetime as dt
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo
from unittest.mock import Mock, MagicMock, patch, call

# Setup path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

from app.adapters.base import DataSource


class MockDataSource(DataSource):
    """Mock adapter that can be configured to succeed or fail."""

    def __init__(self, name: str = "test_source", fail_count: int = 0):
        self.name = name
        self.fail_count = fail_count
        self.call_count = 0
        self.fetch_call_count = 0

    def fetch(self, target: Any, date: dt.date) -> dict:
        self.fetch_call_count += 1
        if self.call_count < self.fail_count:
            self.call_count += 1
            raise RuntimeError(f"{self.name} fetch failed intentionally (call {self.call_count})")
        self.call_count += 1
        return {"data": "mocked"}

    def parse(self, raw: Any) -> list[dict]:
        """Parse mocked raw data into normalized rows."""
        if self.name == "security":
            return [
                {
                    "row_type": "security",
                    "symbol": "2330",
                    "name": "TSMC",
                    "market": "listed",
                    "outstanding_shares": 2500000,
                    "is_active": True,
                }
            ]
        if "daily_price" in self.name:
            return [
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
        if "chips" in self.name:
            return [
                {
                    "symbol": "2330",
                    "market": "listed",
                    "date": dt.date(2026, 1, 2),
                    "foreign_net": 1000,
                    "investment_trust_net": 500,
                    "dealer_net": 200,
                }
            ]
        return []


class SpyingNotifier:
    """Notifier that records all calls."""

    def __init__(self):
        self.calls = []

    def notify(self, subject: str, message: str) -> None:
        self.calls.append({"subject": subject, "message": message})


class TestRetryLogic:
    """Test 1: Failed sources retry, succeeded sources don't re-fetch."""

    def test_failed_source_retried_succeeded_source_not_retried(self):
        """Verify retry logic: failed source retried, succeeded source skipped."""
        from app.ingestion.scheduler import IngestionCoordinator
        from app.ingestion.pipeline import Pipeline, InMemoryIngestionRepository

        # Create two sources: one that fails once, one that always succeeds
        failing_source = MockDataSource("daily_price", fail_count=1)
        succeeding_source = MockDataSource("security", fail_count=0)

        repo = InMemoryIngestionRepository()
        pipeline = Pipeline(
            repository=repo,
            sources={
                "security_source": succeeding_source,  # Pass instance directly
                "daily_price_source": failing_source,   # Pass instance directly
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        notifier = SpyingNotifier()
        coordinator = IngestionCoordinator(pipeline, notifier=notifier)

        # First trigger: security succeeds, daily_price fails
        result1 = coordinator.trigger()
        assert result1 is not None, "First trigger should return result"
        assert result1.sources["security_source"].success, "Security source should succeed"
        assert not result1.sources["daily_price_source"].success, "Daily price source should fail first"

        # Verify failure was recorded and notified
        assert failing_source.call_count == 1, "Failed source should have been called once"
        assert any("daily_price_source" in call_dict["message"] for call_dict in notifier.calls), \
            "Notifier should be called for failed source"

        # Second trigger (next hour): security should NOT be re-fetched, daily_price should retry
        initial_security_fetch = succeeding_source.fetch_call_count
        initial_daily_price_fetch = failing_source.fetch_call_count
        result2 = coordinator.trigger()

        assert result2 is not None, "Second trigger should return result"
        # Note: security_source is not in result2.sources because it was already succeeded,
        # so only pending sources (daily_price_source) are run in the second trigger
        assert "daily_price_source" in result2.sources, "Only pending source (daily_price) should be in result"
        assert result2.sources["daily_price_source"].success, "Daily price source should succeed on retry"

        # Verify that security was NOT re-fetched (already succeeded)
        assert succeeding_source.fetch_call_count == initial_security_fetch, \
            "Succeeded source should not be re-fetched in second trigger"

        # Verify that daily_price WAS re-fetched (was failing)
        assert failing_source.fetch_call_count > initial_daily_price_fetch, \
            "Failed source should be re-fetched in second trigger"


class TestAllGreen:
    """Test 2: Once all sources succeed, further triggers stop (all_green behavior)."""

    def test_all_green_stops_further_triggers(self):
        """Verify all_green behavior: no further source runs after all succeed."""
        from app.ingestion.scheduler import IngestionCoordinator
        from app.ingestion.pipeline import Pipeline, InMemoryIngestionRepository

        source1 = MockDataSource("security", fail_count=0)
        source2 = MockDataSource("daily_price", fail_count=0)

        repo = InMemoryIngestionRepository()
        pipeline = Pipeline(
            repository=repo,
            sources={
                "security_source": source1,
                "daily_price_source": source2,
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        notifier = SpyingNotifier()
        coordinator = IngestionCoordinator(pipeline, notifier=notifier)

        # First trigger: all succeed, adjustment succeeds
        result1 = coordinator.trigger()
        assert result1 is not None, "First trigger should return result"
        assert result1.success, "First run should succeed"
        assert coordinator.state.all_green, "State should be all_green after all succeed"

        # Record fetch counts
        fetch_count1_after_first = source1.fetch_call_count
        fetch_count2_after_first = source2.fetch_call_count

        # Second trigger (same day): should return None and NOT fetch anything
        result2 = coordinator.trigger()
        assert result2 is None, "Second trigger should return None when all_green"
        assert source1.fetch_call_count == fetch_count1_after_first, \
            "Source 1 should not be fetched again when all_green"
        assert source2.fetch_call_count == fetch_count2_after_first, \
            "Source 2 should not be fetched again when all_green"


class TestNotifierCalled:
    """Test 3: Notifier is invoked when a source fails."""

    def test_notifier_called_on_source_failure(self):
        """Verify notifier.notify() is actually called on source failure."""
        from app.ingestion.scheduler import IngestionCoordinator
        from app.ingestion.pipeline import Pipeline, InMemoryIngestionRepository

        failing_source = MockDataSource("daily_price", fail_count=1)

        repo = InMemoryIngestionRepository()
        pipeline = Pipeline(
            repository=repo,
            sources={
                "security_source": MockDataSource("security", fail_count=0),
                "daily_price_source": failing_source,
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        notifier = SpyingNotifier()
        coordinator = IngestionCoordinator(pipeline, notifier=notifier)

        # Trigger: daily_price fails
        result = coordinator.trigger()
        assert not result.sources["daily_price_source"].success, "Daily price should fail"

        # Verify notifier was called
        assert len(notifier.calls) > 0, "Notifier should have been called"
        assert any("daily_price_source" in call_dict["message"] for call_dict in notifier.calls), \
            "Notifier message should mention failed source name"
        assert any("Ingestion source failed" in call_dict["subject"] for call_dict in notifier.calls), \
            "Notifier subject should indicate source failure"

    def test_notifier_called_on_adjustment_failure(self):
        """Verify notifier is called when price adjustment fails."""
        from app.ingestion.scheduler import IngestionCoordinator
        from app.ingestion.pipeline import Pipeline

        # Use a mock repository that has data but fails on adjustment
        failing_adjustment_repo = Mock()
        failing_adjustment_repo.write_rows = Mock()
        # Return price series so adjustment step is triggered
        failing_adjustment_repo.list_price_series = Mock(return_value={
            1: [  # Security with ID 1
                {"date": dt.date(2026, 1, 1), "open_raw": 100.0, "high_raw": 105.0,
                 "low_raw": 99.0, "close_raw": 102.0},
            ]
        })
        failing_adjustment_repo.list_corporate_actions = Mock(return_value=[])

        def failing_replace_adjusted_prices(*args, **kwargs):
            raise ValueError("Adjustment failed intentionally")

        failing_adjustment_repo.replace_adjusted_prices = failing_replace_adjusted_prices

        pipeline = Pipeline(
            repository=failing_adjustment_repo,
            sources={
                "security_source": MockDataSource("security", fail_count=0),
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        notifier = SpyingNotifier()
        coordinator = IngestionCoordinator(pipeline, notifier=notifier)

        # Trigger: adjustment will fail
        result = coordinator.trigger()
        assert not result.adjustment_success, "Adjustment should fail"

        # Verify notifier was called for adjustment failure
        assert any("adjustment" in call_dict["subject"].lower() for call_dict in notifier.calls), \
            "Notifier should mention adjustment in subject for adjustment failure"


class TestSourceOrdering:
    """Test 4: Securities/basic-data sources run before FK-dependent sources."""

    def test_security_runs_before_dependent_sources(self):
        """Verify securities source runs first in a pipeline run."""
        from app.ingestion.pipeline import Pipeline, InMemoryIngestionRepository

        run_order = []

        class TrackingSource(MockDataSource):
            def __init__(self, name: str):
                super().__init__(name, fail_count=0)

            def fetch(self, target: Any, date: dt.date):
                run_order.append(self.name)
                return super().fetch(target, date)

        security_source = TrackingSource("securities")
        daily_price_source = TrackingSource("daily_price")
        chips_source = TrackingSource("chips")

        repo = InMemoryIngestionRepository()
        pipeline = Pipeline(
            repository=repo,
            sources={
                "securities_data": security_source,
                "daily_price": daily_price_source,
                "chips_data": chips_source,
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        result = pipeline.run(date=dt.date(2026, 7, 6))
        assert result.success, "Pipeline should succeed"

        # Verify security ran first
        assert run_order[0] == "securities", \
            f"Securities should run first, but order was {run_order}"
        assert "daily_price" in run_order[1:], "Daily price should run after securities"
        assert "chips" in run_order[1:], "Chips should run after securities"


class TestPriceAdjustmentFullHistory:
    """Test 5: Price adjustment receives FULL historical series."""

    def test_adjustment_receives_full_historical_series(self):
        """Verify adjustment is called with complete historical price series."""
        from app.ingestion.pipeline import Pipeline

        # Track what list_price_series and replace_adjusted_prices are called with
        adjustment_calls = []

        class TrackingRepository:
            def __init__(self):
                self.written_rows = {}

            def write_rows(self, source_name: str, rows: Sequence[Mapping[str, Any]]) -> None:
                self.written_rows[source_name] = list(rows)

            def list_price_series(self) -> Mapping[Any, Sequence[Mapping[str, Any]]]:
                """Return complete price history for security 2330."""
                return {
                    1: [  # Assuming security_id=1 after write
                        {"date": dt.date(2026, 1, 1), "open_raw": 100.0, "high_raw": 105.0,
                         "low_raw": 99.0, "close_raw": 102.0},
                        {"date": dt.date(2026, 1, 2), "open_raw": 102.0, "high_raw": 107.0,
                         "low_raw": 100.0, "close_raw": 104.0},
                        {"date": dt.date(2026, 1, 3), "open_raw": 104.0, "high_raw": 108.0,
                         "low_raw": 101.0, "close_raw": 105.0},
                    ]
                }

            def list_corporate_actions(self, security_key: Any) -> Sequence[Mapping[str, Any]]:
                return []

            def replace_adjusted_prices(
                self,
                security_key: Any,
                adjusted_rows: Sequence[Mapping[str, Any] | Any],
            ) -> None:
                adjustment_calls.append({
                    "security_key": security_key,
                    "adjusted_rows_count": len(list(adjusted_rows)),
                    "adjusted_rows": list(adjusted_rows),
                })

        repo = TrackingRepository()

        # Define a custom adjustment writer to capture what it receives
        def custom_adjustment_writer(security_key, adjusted, repo):
            # Verify we got full history (3 rows)
            adjusted_list = list(adjusted)
            assert len(adjusted_list) == 3, \
                f"Adjustment should receive full history (3 rows), got {len(adjusted_list)}"
            repo.replace_adjusted_prices(security_key, adjusted_list)

        pipeline = Pipeline(
            repository=repo,
            sources={
                "securities_data": MockDataSource("security", fail_count=0),
                "daily_price": MockDataSource("daily_price", fail_count=0),
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            adjustment_writer=custom_adjustment_writer,
        )

        result = pipeline.run(date=dt.date(2026, 7, 6))
        assert result.success, "Pipeline should succeed"

        # Verify adjustment was called with full series
        assert len(adjustment_calls) > 0, "Adjustment should have been called"
        assert adjustment_calls[0]["adjusted_rows_count"] == 3, \
            f"Adjustment should receive 3 rows (full history), got {adjustment_calls[0]['adjusted_rows_count']}"

    def test_adjustment_full_series_with_in_memory_repository(self):
        """Verify full history adjustment using InMemoryIngestionRepository."""
        from app.ingestion.pipeline import Pipeline, InMemoryIngestionRepository

        repo = InMemoryIngestionRepository()

        # Manually populate existing price data (simulating prior runs)
        repo.write_rows("daily_price_old", [
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
        ])

        # Now run pipeline with new data
        pipeline = Pipeline(
            repository=repo,
            sources={
                "securities_data": MockDataSource("security", fail_count=0),
                "daily_price": MockDataSource("daily_price", fail_count=0),
            },
            discover=lambda: {},
            clock=lambda: dt.datetime(2026, 7, 6, 18, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        result = pipeline.run(date=dt.date(2026, 7, 6))
        assert result.success, "Pipeline should succeed"

        # Verify that list_price_series returned both old and new data (full history)
        price_series = repo.list_price_series()
        total_prices = sum(len(v) for v in price_series.values())
        assert total_prices >= 3, \
            f"Should have at least 3 prices (1 old + 2 new), got {total_prices}"

        # Verify that adjusted prices were written back for the security
        security_key = ("listed", "2330")  # Key format used in InMemoryIngestionRepository
        assert security_key in repo.adjusted_by_security, \
            f"Adjusted prices should be recorded for {security_key}"
        adjusted_count = len(repo.adjusted_by_security[security_key])
        assert adjusted_count >= 3, \
            f"Should have adjusted at least 3 prices, got {adjusted_count}"


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
