"""Date-scoped MOPS event list (t05st02): events, verified-empty and failed dates (#464)."""

import socket
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import DataQuality, Event, IngestionRun, Instrument
import worker.backfill as backfill
import worker.mops_events as mops_events
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher, mops_event_list_payload

DAY = date(2026, 9, 4)
PREVIOUS = date(2026, 9, 3)
NOW = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)


def row(day, clock, code, subject, market="sii", serial=1):
    roc = f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"
    return [
        roc,
        clock,
        code,
        f"name {code}",
        subject,
        {
            "parameters": {
                "enterDate": roc.replace("/", ""),
                "serialNumber": serial,
                "companyId": code,
                "marketKind": market,
            },
            "apiName": "t05st02_detail",
        },
    ]


class ListFetcher:
    """Answers MOPS t05st02 per requested date; records every request body."""

    def __init__(self, by_date=None, fail=()):
        self.by_date = by_date or {}
        self.fail = set(fail)
        self.bodies = []

    def __call__(self, url, *, method="GET", data=None, json_body=None):
        assert url == mops_events.MOPS_EVENT_LIST_ENDPOINT and method == "POST"
        self.bodies.append(json_body)
        day = date(
            int(json_body["year"]) + 1911,
            int(json_body["month"]),
            int(json_body["day"]),
        )
        if day in self.fail:
            raise sources.OfficialDataError("fixture outage")
        value = self.by_date.get(day, [])
        return value if isinstance(value, dict) else mops_event_list_payload(value)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in MOPS event list tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(mops_events, "utcnow", lambda: NOW.replace(tzinfo=None))


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory
    engine.dispose()


def _instruments(db):
    db.add_all(
        [
            Instrument(
                market="TW",
                exchange="TWSE",
                symbol="1101",
                name="A",
                instrument_type="stock",
                status="active",
            ),
            Instrument(
                market="TW",
                exchange="TPEx",
                symbol="7001",
                name="B",
                instrument_type="stock",
                status="active",
            ),
        ]
    )
    db.flush()


# --- one date: events, verified empty, failure -----------------------------


def test_a_date_with_events_is_verified_and_keeps_listed_and_otc_rows_only():
    fetcher = ListFetcher(
        {
            DAY: [
                row(PREVIOUS, "17:45:00", "1101", "late yesterday"),
                row(DAY, "09:00:00", "1101", "listed news"),
                row(DAY, "10:00:00", "7001", "otc news", market="otc"),
                row(DAY, "11:00:00", "8888", "emerging", market="rotc"),
                row(DAY, "12:00:00", "9999", "public", market="pub"),
            ]
        }
    )
    events, payloads, coverage, warnings = mops_events.fetch_date(DAY, fetcher)

    assert fetcher.bodies == [{"year": "115", "month": "09", "day": "04"}]
    assert warnings == [] and len(payloads) == 1
    assert payloads[0].source == "mops" and payloads[0].data_as_of == DAY.isoformat()
    assert {(e.exchange, e.symbol, e.event_date, e.title) for e in events} == {
        ("TWSE", "1101", PREVIOUS, "late yesterday"),
        ("TWSE", "1101", DAY, "listed news"),
        ("TPEx", "7001", DAY, "otc news"),
    }
    assert all(e.source == "mops_material_information" for e in events)
    assert all(e.payload_sha256 == payloads[0].sha256 for e in events)
    assert coverage["status"] == "complete"
    assert coverage["verified_dates"] == [DAY.isoformat()]
    assert coverage["empty_dates"] == [] and coverage["partial_dates"] == []
    assert coverage["fetched_at"] is not None
    assert mops_events.coverage_state(coverage, DAY) == "verified"


def test_a_date_answered_without_listed_or_otc_rows_is_a_verified_empty_date():
    # Only the previous evening and an emerging-market row: nothing on DAY.
    fetcher = ListFetcher(
        {
            DAY: [
                row(PREVIOUS, "18:00:00", "1101", "late yesterday"),
                row(DAY, "09:00:00", "8888", "emerging", market="rotc"),
            ]
        }
    )
    events, payloads, coverage, warnings = mops_events.fetch_date(DAY, fetcher)

    assert warnings == [] and len(payloads) == 1
    assert [e.event_date for e in events] == [PREVIOUS]
    assert coverage["status"] == "verified_empty"
    assert coverage["empty_dates"] == [DAY.isoformat()]
    assert coverage["verified_dates"] == []
    assert mops_events.coverage_state(coverage, DAY) == "empty"


@pytest.mark.parametrize(
    "answer",
    [
        "outage",
        {"code": 500, "message": "系統忙碌", "result": None},
        {"code": 200, "message": "查詢成功", "result": {"data": []}},
        "wrong_date",
        "renamed_columns",
    ],
)
def test_a_failed_or_untrustworthy_answer_is_a_partial_date_never_empty(answer):
    if answer == "outage":
        fetcher = ListFetcher(fail={DAY})
    elif answer == "wrong_date":
        fetcher = ListFetcher({DAY: [row(date(2026, 9, 1), "09:00:00", "1101", "x")]})
    elif answer == "renamed_columns":
        payload = mops_event_list_payload([])
        payload["result"]["titles"][4] = {"main": "標題", "sub": []}
        fetcher = ListFetcher({DAY: payload})
    else:
        fetcher = ListFetcher({DAY: answer})
    events, _payloads, coverage, warnings = mops_events.fetch_date(DAY, fetcher)

    assert events == []
    assert coverage["status"] == "partial"
    assert coverage["partial_dates"] == [DAY.isoformat()]
    assert coverage["empty_dates"] == [] and coverage["verified_dates"] == []
    assert mops_events.coverage_state(coverage, DAY) == "partial"
    assert len(warnings) == 1 and warnings[0].startswith("MOPS event list unavailable")
    # Non-core: a missing event list never makes the collect partial.
    assert pipeline.split_collect_warnings(warnings) == ([], warnings)


# --- collect: the combined adapter queries the score date ------------------


def _combined(fetcher, *, snapshot_feeds=True):
    return sources.OfficialMarketDataAdapter(
        sources.TwseAdapter(fetcher, snapshot_feeds=snapshot_feeds),
        sources.TpexAdapter(fetcher, snapshot_feeds=snapshot_feeds),
    )


class CollectFetcher(FixtureFetcher):
    """Collect fixtures with numeric industry codes plus a scripted MOPS list."""

    def __init__(self, mops):
        super().__init__()
        self.mops = mops

    def __call__(self, url, **kwargs):
        if url == mops_events.MOPS_EVENT_LIST_ENDPOINT:
            self.calls.append(url)
            return self.mops(url, **kwargs)
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [
                dict(item, Industry="01" if item["Code"] == "1101" else "24")
                for item in payload
            ]
        return payload


@pytest.mark.parametrize("snapshot_feeds", [True, False])
def test_collect_records_the_dated_list_as_event_coverage(database, snapshot_feeds):
    mops = ListFetcher({DAY: [row(DAY, "09:00:00", "1101", "listed news")]})
    result = pipeline.collect(
        DAY, adapter=_combined(CollectFetcher(mops), snapshot_feeds=snapshot_feeds)
    )

    assert result["status"] == "success", result
    assert result["event_coverage"]["status"] == "complete"
    assert result["event_coverage"]["verified_dates"] == [DAY.isoformat()]
    with database() as db:
        titles = {
            (event.event_date, event.title, event.source)
            for event in db.scalars(select(Event))
        }
        assert (DAY, "listed news", "mops_material_information") in titles
        quality = {
            row.entity_key: row.status
            for row in db.scalars(
                select(DataQuality).where(
                    DataQuality.entity_type == "mops_events",
                    DataQuality.as_of_date == DAY,
                )
            )
        }
        assert quality == {"TWSE": "complete", "TPEx": "complete"}
        assert mops_events.event_coverage_states(db, [DAY]) == {DAY: "verified"}


def test_collect_with_a_failed_list_keeps_the_day_partial_and_successful(database):
    result = pipeline.collect(
        DAY, adapter=_combined(CollectFetcher(ListFetcher(fail={DAY})))
    )

    assert result["status"] == "success", result
    assert result["event_coverage"]["status"] == "partial"
    assert any(
        w.startswith("MOPS event list unavailable") for w in result["noncore_warnings"]
    )
    with database() as db:
        assert mops_events.event_coverage_states(db, [DAY]) == {DAY: "partial"}


def test_a_snapshot_row_keeps_its_text_when_the_dated_list_repeats_it(database):
    snapshot = mops_events.EventRecord(
        symbol="1101",
        event_date=DAY,
        event_type="material_information",
        title="same subject（發言時間 15:00:00）",
        description="full text",
        details={"發言時間": "150000"},
        exchange="TWSE",
    )
    dated = mops_events.parse_event_list(
        mops_event_list_payload(
            [
                row(DAY, "09:00:00", "1101", "same subject"),
                row(DAY, "15:00:00", "1101", "same subject", serial=2),
            ]
        ),
        DAY,
    )
    with database() as db:
        _instruments(db)
        instruments = {
            (i.exchange, i.symbol): i for i in db.scalars(select(Instrument))
        }
        pipeline._upsert_event(db, snapshot, instruments, None)
        for record in dated:
            pipeline._upsert_event(db, record, instruments, None)
        db.flush()
        rows = {(e.title, e.description) for e in db.scalars(select(Event))}
    # The snapshot only saw the 15:00 announcement and stored it suffixed; the
    # dated list adds the 09:00 one and does not overwrite the 15:00 text.
    assert rows == {
        ("same subject", None),
        ("same subject（發言時間 15:00:00）", "full text"),
    }


# --- event backfill and the coverage page ----------------------------------


def test_event_backfill_counts_verified_and_empty_dates_but_not_failed_ones(database):
    monday, tuesday, wednesday = date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9)
    fetcher = ListFetcher(
        {
            monday: [row(monday, "09:00:00", "1101", "news")],
            tuesday: [row(tuesday, "09:00:00", "8888", "emerging", market="rotc")],
        },
        fail={wednesday},
    )
    sleeps = []
    with database() as db:
        _instruments(db)
        result = mops_events.backfill_events(
            db,
            start=monday,
            end=wednesday,
            fetcher=fetcher,
            sleep=sleeps.append,
            interval_seconds=3.0,
        )
        db.commit()
        assert sleeps == [3.0, 3.0]
        assert result["status"] == "partial"
        assert (result["verified_dates"], result["empty_dates"]) == (1, 1)
        assert result["partial_dates"] == [wednesday.isoformat()]
        assert result["events_written"] == 1
        run = db.get(IngestionRun, result["run_id"])
        assert run.run_type == "event_backfill"
        assert set(run.metadata_json["coverage_manifest"]) == {
            monday.isoformat(),
            tuesday.isoformat(),
            wednesday.isoformat(),
        }
        assert mops_events.event_coverage_states(
            db, [monday, tuesday, wednesday, date(2026, 9, 10)]
        ) == {
            monday: "verified",
            tuesday: "empty",
            wednesday: "partial",
            date(2026, 9, 10): "unqueried",
        }
        # Re-running a failed date that now answers upgrades it; the
        # verified dates stay verified when a later query fails.
        mops_events.backfill_events(
            db,
            start=monday,
            end=wednesday,
            fetcher=ListFetcher({wednesday: []}, fail={monday, tuesday}),
            sleep=lambda _s: None,
        )
        db.commit()
        assert mops_events.event_coverage_states(db, [monday, tuesday, wednesday]) == {
            monday: "verified",
            tuesday: "empty",
            wednesday: "empty",
        }
        quality = {
            (row.as_of_date, row.entity_key): row.status
            for row in db.scalars(
                select(DataQuality).where(DataQuality.entity_type == "mops_events")
            )
        }
        assert set(quality.values()) == {"complete"}
        assert db.scalar(select(Event).where(Event.title == "news")) is not None


def test_coverage_report_counts_event_backfill_dates_over_snapshot_runs(database):
    with database() as db:
        _instruments(db)
        # A snapshot collect stored unsupported coverage for DAY first.
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=DAY,
                status="success",
                data_as_of=DAY.isoformat(),
                metadata_json={
                    "event_coverage": {
                        "status": "unsupported",
                        "unsupported_dates": [DAY.isoformat()],
                    }
                },
            )
        )
        db.flush()
        before = backfill.coverage_report(db, DAY, DAY)["summary"]["event_coverage"]
        mops_events.backfill_events(
            db,
            start=DAY,
            end=DAY,
            fetcher=ListFetcher({DAY: []}),
            sleep=lambda _s: None,
        )
        db.flush()
        after = backfill.coverage_report(db, DAY, DAY)["summary"]["event_coverage"]
    assert (before["status"], before["verified_sessions"]) == ("unsupported", 0)
    assert after["status"] == "complete"
    assert (after["verified_sessions"], after["verified_empty_sessions"]) == (1, 1)


def test_event_backfill_refuses_future_dates(database):
    with database() as db, pytest.raises(ValueError):
        mops_events.backfill_events(
            db,
            start=date(2026, 9, 12),
            end=date(2026, 9, 13),
            fetcher=ListFetcher(),
            sleep=lambda _s: None,
        )
