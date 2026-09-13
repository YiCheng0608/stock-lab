from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.product_time import (
    PRODUCT_TIME_VERSION,
    build_action_product_time,
    build_news_product_time,
    build_signal_product_time,
)


UTC = timezone.utc


def test_news_product_time_preserves_date_precision_and_normalizes_aware_values():
    item = SimpleNamespace(
        event_date=date(2026, 9, 8),
        event_at=datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc),
        published_at="2026-09-08T09:30:00+08:00",
        collected_at=datetime(2026, 9, 8, 2, 0, tzinfo=UTC),
        display_time=datetime(2026, 9, 8),
        time_basis="published",
        time_precision="datetime",
        time_consistency="verified",
    )

    result = build_news_product_time(
        item,
        response_generated_at="2026-09-08T10:00:00+08:00",
    )

    assert result["version"] == PRODUCT_TIME_VERSION
    assert result["roles"]["event_date"]["value"] == "2026-09-08"
    assert result["roles"]["event_date"]["precision"] == "date"
    assert result["roles"]["published_at"]["value"] == "2026-09-08T01:30:00+00:00"
    assert result["roles"]["collected_at"]["status"] == "known"
    assert result["response_generated_at"] == "2026-09-08T02:00:00+00:00"
    assert result["roles"]["event_date"]["timezone_policy"] == "calendar_date_no_timezone_conversion"


def test_news_product_time_fails_closed_for_naive_date_only_missing_and_conflict():
    item = SimpleNamespace(
        event_date="2026-09-08",
        event_at="2026-09-08T09:30:00",
        published_at="2026-09-08",
        collected_at=datetime(2026, 9, 8, 10, 0),
        display_time=datetime(2026, 9, 8),
        time_basis="event_date",
        time_precision="date",
        time_consistency="conflict",
    )

    result = build_news_product_time(item)
    roles = result["roles"]

    assert roles["event_date"]["status"] == "unknown"
    assert roles["event_date"]["reason"] == "time_consistency_conflict"
    assert roles["event_at"]["status"] == "unknown"
    assert roles["published_at"]["status"] == "unknown"
    assert roles["collected_at"]["status"] == "unknown"
    assert roles["first_available_at"]["status"] == "unknown"
    assert result["legacy"]["published_at"] == "2026-09-08"
    assert any("fail-closed" in value for value in result["limitations"])


def test_news_product_time_requires_explicit_basis_and_precision_for_instants():
    for precision, basis in (("none", "unverified"), ("invalid", "unverified"), ("datetime", "unverified")):
        item = SimpleNamespace(
            event_date=date(2026, 9, 8),
            event_at=datetime(2026, 9, 8, 1, 30, tzinfo=UTC),
            published_at=datetime(2026, 9, 8, 2, 0, tzinfo=UTC),
            collected_at=datetime(2026, 9, 8, 3, 0, tzinfo=UTC),
            display_time=datetime(2026, 9, 8),
            time_basis=basis,
            time_precision=precision,
            time_consistency="verified",
        )
        roles = build_news_product_time(item)["roles"]
        assert roles["published_at"]["status"] == "unknown"
        assert roles["event_at"]["status"] == "unknown"


def test_signal_product_time_ignores_spoofed_evidence_and_keeps_legacy_dates():
    signal = SimpleNamespace(
        signal_date=date(2026, 9, 8),
        earliest_execution_date=date(2026, 9, 9),
        execution_date=None,
        data_cutoff="2026-09-08",
        created_at=datetime(2026, 9, 8, 9, 0),
        rule_evidence_json={
            "product_time": {"roles": {"generated_at": {"status": "known"}}},
            "generated_at": "2026-09-08T09:00:00+00:00",
        },
    )

    result = build_signal_product_time(signal)

    assert result["roles"]["market_date"]["value"] == "2026-09-08"
    assert result["roles"]["earliest_execution_at"]["status"] == "unknown"
    assert result["roles"]["earliest_execution_at"]["reason"] == "legacy_earliest_execution_date_is_date_only"
    assert result["roles"]["earliest_execution_date"]["value"] == "2026-09-09"
    assert result["roles"]["earliest_execution_date"]["precision"] == "date"
    assert result["roles"]["generated_at"]["status"] == "unknown"
    assert result["roles"]["generated_at"]["reason"] == "legacy_generated_at_not_persisted_with_timezone"
    assert result["legacy"]["created_at"] == "2026-09-08T09:00:00"
    assert any("evidence markers" in value for value in result["limitations"])


def test_action_product_time_requires_unique_event_and_keeps_response_separate():
    event_one = SimpleNamespace(event_date=date(2026, 9, 7))
    event_two = SimpleNamespace(event_date=date(2026, 9, 8))
    many = build_action_product_time(
        as_of=date(2026, 9, 8),
        price_as_of=date(2026, 9, 8),
        earliest_execution_date=date(2026, 9, 9),
        related_events=[event_one, event_two],
        collected_at=datetime(2026, 9, 8, 10, 0),
        response_generated_at="2026-09-08T18:00:00+08:00",
        legacy_generated_at="2026-09-08T18:00:00+08:00",
    )
    unique = build_action_product_time(
        as_of=date(2026, 9, 8),
        related_events=[event_one],
        earliest_execution_date=None,
        response_generated_at="2026-09-08T10:00:00+00:00",
    )

    assert many["roles"]["market_date"]["value"] == "2026-09-08"
    assert many["roles"]["event_date"]["status"] == "unknown"
    assert many["roles"]["event_date"]["reason"] == "action_event_date_not_unique"
    assert many["roles"]["collected_at"]["status"] == "unknown"
    assert many["roles"]["earliest_execution_at"]["status"] == "unknown"
    assert many["roles"]["earliest_execution_date"]["value"] == "2026-09-09"
    assert many["roles"]["generated_at"]["status"] == "unknown"
    assert many["response_generated_at"] == "2026-09-08T10:00:00+00:00"
    assert many["legacy"]["generated_at"] == "2026-09-08T18:00:00+08:00"
    assert unique["roles"]["event_date"]["value"] == "2026-09-07"
