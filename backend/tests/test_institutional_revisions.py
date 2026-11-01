"""A later official capture revises institutional flow (Issue #387).

The exchanges publish T86 / TPEx institutional flow at about 18:30 Taipei and
revise it by 21:30; before #387 collect kept the 18:30 values.  The fixture
numbers are 2313's 2026-10-19 T86 row: the 18:30 capture had investment-trust
flow -162,968 shares, the 21:30 one 1,133,032 (the sign flipped).
"""

import socket
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import ChipSnapshot, IngestionRun, Instrument, MarketBar, RawPayload
import worker.chip_revisions as chip_revisions
import worker.pipeline as pipeline
import worker.sources as sources
from test_sources import FixtureFetcher

DAY = date(2026, 9, 4)
FIRST = datetime(2026, 9, 4, 10, 30)  # 18:30 Taipei
LATER = datetime(2026, 9, 4, 13, 30)  # 21:30 Taipei
LATEST = datetime(2026, 9, 5, 10, 30)
INITIAL = ("-1733324", "-162968", "307854")
REVISED = ("-1733324", "1133032", "307854")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in institutional revision tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'revisions.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


class Fetcher(FixtureFetcher):
    """The fixture feeds with 1101's T86 row, margin balance and close set."""

    def __init__(self, t86=INITIAL, *, margin="11242", close="100", extra=()):
        super().__init__()
        self.t86, self.margin, self.close, self.extra = t86, margin, close, extra

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [
                dict(row, Industry="01" if row["Code"] == "1101" else "24")
                for row in payload
            ]
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            quotes = payload["tables"][1]
            row = list(quotes["data"][0])
            row[4] = self.close
            return dict(
                payload, tables=[payload["tables"][0], dict(quotes, data=[row])]
            )
        if url.startswith(sources.TWSE_CHIP_ENDPOINT):
            return dict(payload, data=[["1101", *self.t86], *self.extra])
        if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT):
            table = payload["tables"][1]
            row = list(table["data"][0])
            row[6] = self.margin
            return dict(payload, tables=[payload["tables"][0], dict(table, data=[row])])
        return payload


def collect_at(monkeypatch, when, fetcher, **kwargs):
    monkeypatch.setattr(sources, "utcnow", lambda: when)
    return pipeline.collect(
        DAY,
        adapter=sources.OfficialMarketDataAdapter(
            sources.TwseAdapter(fetcher), sources.TpexAdapter(fetcher)
        ),
        **kwargs,
    )


def reopen(database):
    """Let the next collect of the same request fetch again, as 21:30 does."""

    with database() as db:
        db.execute(update(IngestionRun).values(status="partial"))
        db.commit()


def chip(db, symbol="1101"):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return db.scalar(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == instrument.id,
            ChipSnapshot.trading_date == DAY,
        )
    )


def bar(db, symbol="1101"):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    return db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date == DAY
        )
    )


def t86_capture(db, when):
    return db.scalar(
        select(RawPayload.id).where(
            RawPayload.endpoint.like(f"{sources.TWSE_CHIP_ENDPOINT}%"),
            RawPayload.collected_at == when,
        )
    )


def test_a_later_capture_replaces_the_institutional_values(database, monkeypatch):
    first = collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    assert first["status"] == "success", first
    with database() as db:
        row = chip(db)
        assert (row.foreign_buy, row.trust_buy, row.dealer_buy) == (
            -1733324,
            -162968,
            307854,
        )
        stored_raw, stored_at = row.raw_payload_id, row.collected_at
        assert stored_raw == t86_capture(db, FIRST)
    reopen(database)

    second = collect_at(monkeypatch, LATER, Fetcher(REVISED))
    assert second["status"] == "success" and second["value_revisions"] == 1
    with database() as db:
        row = chip(db)
        revised_raw = t86_capture(db, LATER)
        assert (row.foreign_buy, row.trust_buy, row.dealer_buy) == (
            -1733324,
            1133032,
            307854,
        )
        assert row.raw_payload_id == revised_raw != stored_raw
        assert row.collected_at > stored_at
        assert row.source == "twse_t86+twse_margin"
        metadata = db.get(IngestionRun, second["run_id"]).metadata_json
    assert metadata["value_revision_rows"] == [
        {
            "table": "chip_snapshots",
            "exchange": "TWSE",
            "symbol": "1101",
            "trading_date": DAY.isoformat(),
            "fields": {"trust_buy": {"stored": -162968.0, "incoming": 1133032.0}},
            "stored_raw_payload_id": stored_raw,
            "raw_payload_id": revised_raw,
        }
    ]
    assert metadata["value_conflicts"] == 0

    # A still later capture with the same 1101 values (another row differs, so
    # it is a new capture) changes nothing, and the record of the revision stays.
    reopen(database)
    with database() as db:
        row = chip(db)
        kept = (row.trust_buy, row.raw_payload_id, row.collected_at)
    third = collect_at(
        monkeypatch, LATEST, Fetcher(REVISED, extra=[["2330", "1", "2", "3"]])
    )
    assert third["status"] == "success" and third["value_revisions"] == 0
    with database() as db:
        assert t86_capture(db, LATEST) not in (None, kept[1])
        row = chip(db)
        assert (row.trust_buy, row.raw_payload_id, row.collected_at) == kept
        metadata = db.get(IngestionRun, third["run_id"]).metadata_json
    assert [item["raw_payload_id"] for item in metadata["value_revision_rows"]] == [
        revised_raw
    ]


def test_margin_and_bars_keep_the_stored_value_of_a_later_capture(
    database, monkeypatch
):
    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    with database() as db:
        stored = (chip(db).margin_balance, bar(db).close)
    reopen(database)

    second = collect_at(
        monkeypatch, LATER, Fetcher(REVISED, margin="11300", close="100.5")
    )
    assert second["value_revisions"] == 1
    with database() as db:
        row = chip(db)
        assert row.trust_buy == 1133032
        assert (row.margin_balance, bar(db).close) == stored == (11242, 100)
        samples = db.get(IngestionRun, second["run_id"]).metadata_json[
            "value_conflict_samples"
        ]
    assert {(item["row"].split(":")[0], item["field"]) for item in samples} == {
        ("chip_snapshots", "margin_balance"),
        ("chip_snapshots", "margin_change"),
        ("market_bars", "close"),
        ("market_bars", "adj_close"),
    }


def test_an_earlier_capture_does_not_replace_a_later_one(database, monkeypatch):
    # The later capture is stored first (say a rerun read captures out of order).
    collect_at(monkeypatch, LATER, Fetcher(REVISED))
    with database() as db:
        kept = (chip(db).trust_buy, chip(db).raw_payload_id)
    reopen(database)

    earlier = collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    assert earlier["value_revisions"] == 0 and earlier["value_conflicts"] == 1
    with database() as db:
        assert (
            (chip(db).trust_buy, chip(db).raw_payload_id)
            == kept
            == (
                1133032,
                t86_capture(db, LATER),
            )
        )


def test_a_capture_taken_at_the_same_time_does_not_revise(database, monkeypatch):
    # Only a strictly later capture replaces a value (PR #398 review 2).
    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    reopen(database)
    same = collect_at(monkeypatch, FIRST, Fetcher(REVISED))
    assert same["value_revisions"] == 0 and same["value_conflicts"] == 1
    with database() as db:
        first = t86_capture(db, FIRST)
        assert db.scalar(
            select(RawPayload.id).where(
                RawPayload.endpoint.like(f"{sources.TWSE_CHIP_ENDPOINT}%"),
                RawPayload.collected_at == FIRST,
                RawPayload.id != first,
            )
        )
        assert chip(db).trust_buy == -162968


class NoMargin(Fetcher):
    """A capture whose margin report is for another day, so it has no margin."""

    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT):
            return dict(payload, date="20260903")
        return payload


def test_a_revision_without_margin_keeps_the_margin_source(database, monkeypatch):
    # PR #398 review 1: the stored margin value is still the margin capture's.
    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    with database() as db:
        assert chip(db).source == "twse_t86+twse_margin"
    reopen(database)

    later = collect_at(monkeypatch, LATER, NoMargin(REVISED))
    assert later["value_revisions"] == 1
    with database() as db:
        row = chip(db)
        assert (row.trust_buy, row.margin_balance) == (1133032, 11242)
        assert row.raw_payload_id == t86_capture(db, LATER)
        assert row.source == "twse_t86+twse_margin"


def test_force_still_replaces_with_the_capture_it_fetched(database, monkeypatch):
    collect_at(monkeypatch, LATER, Fetcher(REVISED))
    forced = collect_at(monkeypatch, FIRST, Fetcher(INITIAL), force=True)
    assert forced["value_revisions"] == 0
    with database() as db:
        assert chip(db).trust_buy == -162968


def test_a_row_from_another_source_is_not_revised(database, monkeypatch):
    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    with database() as db:
        row = chip(db)
        row.source = row.institutional_source = "legacy_import"
        db.commit()
    reopen(database)

    second = collect_at(monkeypatch, LATER, Fetcher(REVISED))
    assert second["value_revisions"] == 0 and second["value_conflicts"] == 1
    with database() as db:
        assert chip(db).trust_buy == -162968


# --- chips revise: replay the stored captures ---------------------------------


def stored_like_before_387(database, monkeypatch):
    """Both captures stored, the row still at the first one, as collect left it."""

    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    reopen(database)
    collect_at(monkeypatch, LATER, Fetcher(REVISED))
    with database() as db:
        row = chip(db)
        row.trust_buy = -162968.0
        row.raw_payload_id = row.institutional_raw_payload_id = t86_capture(db, FIRST)
        db.commit()


def test_revise_replays_the_captures_in_capture_order(database, monkeypatch):
    stored_like_before_387(database, monkeypatch)

    with database() as db:
        dry = chip_revisions.revise_institutional(db, DAY, DAY)
    assert (dry["status"], dry["applied"], dry["revised_rows"]) == (
        "success",
        False,
        1,
    )
    with database() as db:
        assert chip(db).trust_buy == -162968
        assert not db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == "chip_revision")
        ).all()

    with database() as db:
        applied = chip_revisions.revise_institutional(db, DAY, DAY, apply=True)
    assert applied["revised_rows"] == 1 and applied["revised_dates"] == [
        DAY.isoformat()
    ]
    with database() as db:
        row = chip(db)
        later = t86_capture(db, LATER)
        assert (row.trust_buy, row.raw_payload_id) == (1133032, later)
        assert row.source == "twse_t86+twse_margin"
        assert row.margin_balance == 11242
        run = db.get(IngestionRun, applied["run_id"])
        assert run.run_type == "chip_revision" and run.status == "success"
        assert run.metadata_json["value_revision_rows"][0]["fields"] == {
            "trust_buy": {"stored": -162968.0, "incoming": 1133032.0}
        }
        assert run.metadata_json["value_revision_rows"][0]["raw_payload_id"] == later

    with database() as db:
        again = chip_revisions.revise_institutional(db, DAY, DAY, apply=True)
    assert again["revised_rows"] == 0


def test_revise_ends_at_the_later_capture_when_it_has_the_smaller_id(
    database, monkeypatch
):
    # The 21:30 capture got the smaller id; the 18:30 one must not win.  What
    # stops it is the strict capture-time comparison in
    # _is_later_institutional_capture, not the replay order: replaying by id
    # gives the same values (only the conflict count differs).
    collect_at(monkeypatch, LATER, Fetcher(REVISED))
    reopen(database)
    collect_at(monkeypatch, FIRST, Fetcher(INITIAL))
    with database() as db:
        assert t86_capture(db, LATER) < t86_capture(db, FIRST)
        row = chip(db)
        row.trust_buy = -162968.0
        row.raw_payload_id = row.institutional_raw_payload_id = t86_capture(db, FIRST)
        row.collected_at = row.institutional_collected_at = FIRST
        db.commit()
    with database() as db:
        assert (
            chip_revisions.revise_institutional(db, DAY, DAY, apply=True)[
                "revised_rows"
            ]
            == 1
        )
    with database() as db:
        assert chip(db).trust_buy == 1133032


def test_revise_creates_no_row(database, monkeypatch):
    stored_like_before_387(database, monkeypatch)
    with database() as db:
        db.delete(chip(db))
        db.commit()
    with database() as db:
        assert (
            chip_revisions.revise_institutional(db, DAY, DAY, apply=True)[
                "revised_rows"
            ]
            == 0
        )
    with database() as db:
        assert chip(db) is None


def test_revise_writes_nothing_when_a_file_is_not_its_capture(database, monkeypatch):
    stored_like_before_387(database, monkeypatch)
    with database() as db:
        path = db.get(RawPayload, t86_capture(db, LATER)).payload_path
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(" ")
    result = chip_revisions.run_revise_institutional(DAY, DAY, apply=True)
    assert result["status"] == "failed" and "SHA-256" in result["error"]
    with database() as db:
        assert chip(db).trust_buy == -162968
        assert not db.scalars(
            select(IngestionRun).where(IngestionRun.run_type == "chip_revision")
        ).all()


def test_revise_lists_a_missing_capture_and_is_partial(database, monkeypatch):
    stored_like_before_387(database, monkeypatch)
    with database() as db:
        later = t86_capture(db, LATER)
        db.get(RawPayload, later).payload_path = str(sources.RAW_DIR / "missing.json")
        db.commit()
    with database() as db:
        result = chip_revisions.revise_institutional(db, DAY, DAY, apply=True)
    assert result["status"] == "partial" and result["revised_rows"] == 0
    assert [item["raw_payload_id"] for item in result["unreadable_captures"]] == [later]
