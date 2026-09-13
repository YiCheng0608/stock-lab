from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.db import Base, enable_sqlite_foreign_keys
from app.models import GroupMembership, ThemeGroup, Instrument, RawPayload, MarketBar, IngestionRun
from app.taxonomy import canonical_group_id
from worker import pipeline, sources


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'membership.db'}")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


def payload(day=4, **changes):
    return replace(sources.capture_payload("twse", sources.TWSE_LISTED_ENDPOINT,
                   {"fixture": "membership"}, "1900-01-01",
                   collected_at=datetime(2026, 9, day, 1)), **changes)


def record(capture, **changes):
    return replace(sources.InstrumentRecord("AAA", "Alpha", industry="24",
                   listing_date=date(2000, 1, 1), payload_sha256=capture.sha256), **changes)


def apply(db, capture, rec=None, score=date(2026, 9, 10), now=datetime(2026, 9, 10, 15)):
    rec = rec or record(capture)
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == rec.symbol))
    if instrument is None:
        instrument = Instrument(symbol=rec.symbol, name=rec.name, market="TW", exchange=rec.exchange, instrument_type=rec.instrument_type)
        db.add(instrument)
        db.flush()
    result = pipeline._ensure_official_groups(db, [rec], {(rec.exchange, rec.symbol): instrument},
             date(1990, 1, 1), score, payloads=[capture], observed_now=now)
    db.commit()
    return result


def rows(db):
    return [(r.group_id, r.valid_from, r.valid_to, r.source) for r in db.scalars(select(GroupMembership).order_by(GroupMembership.valid_from, GroupMembership.group_id))]


@pytest.mark.parametrize("value", ["00", "07", "91"])
def test_unknown_special_and_alias_close_without_inventing_group(env, value):
    with env() as db:
        apply(db, payload())
        result = apply(db, payload(5), record(payload(5), industry=value))
        assert len(rows(db)) == 1
        assert rows(db)[0][1:3] == (date(2026, 9, 4), date(2026, 9, 4))
        assert result["observations"][0]["classification_status"] == "unknown_special_or_unsupported"


def test_forward_change_repeat_and_closed_reentry(env):
    with env() as db:
        apply(db, payload())
        apply(db, payload(5), record(payload(5), industry="01"))
        apply(db, payload(6), record(payload(6), industry="01"))
        assert len(rows(db)) == 2
        apply(db, payload(7))
        assert [(r[1], r[2]) for r in rows(db)] == [(date(2026, 9, 4), date(2026, 9, 4)), (date(2026, 9, 5), date(2026, 9, 6)), (date(2026, 9, 7), None)]


@pytest.mark.parametrize("value", [None, "", "   ", "garbage", "Semiconductor", "22.0"])
def test_missing_fails_and_preserves_history(env, value):
    with env() as db:
        apply(db, payload())
        before = rows(db)
        with pytest.raises(sources.OfficialDataError, match="classification evidence"):
            apply(db, payload(5), record(payload(5), industry=value))
        db.rollback()
        assert rows(db) == before


@pytest.mark.parametrize("value", ["01", "00"])
def test_same_day_conflict_rejects(env, value):
    with env() as db:
        apply(db, payload())
        before = rows(db)
        apply(db, payload())
        assert rows(db) == before
        with pytest.raises(sources.OfficialDataError, match="same-day"):
            apply(db, payload(), record(payload(), industry=value))
        db.rollback()
        assert rows(db) == before


@pytest.mark.parametrize("kind", ["future", "closed", "inverted", "overlap"])
def test_period_conflicts_preserve_all_rows(env, kind):
    with env() as db:
        apply(db, payload())
        row = db.scalar(select(GroupMembership))
        if kind == "future":
            row.valid_from = date(2026, 9, 7)
        elif kind == "closed":
            row.valid_to = date(2026, 9, 8)
        elif kind == "inverted":
            row.valid_to = date(2026, 9, 3)
        else:
            db.add(GroupMembership(group_id=row.group_id, instrument_id=row.instrument_id,
                   valid_from=date(2026, 9, 3), source=row.source))
        db.commit()
        before = rows(db)
        with pytest.raises(sources.OfficialDataError):
            apply(db, payload(5))
        db.rollback()
        assert rows(db) == before


@pytest.mark.parametrize("field,value", [("name", "Wrong"), ("group_type", "manual"), ("definition_version", "other"), ("source", "manual"), ("active", False)])
def test_canonical_identity_not_overwritten(env, field, value):
    with env() as db:
        apply(db, payload())
        group = db.scalar(select(ThemeGroup))
        setattr(group, field, value)
        db.commit()
        with pytest.raises(sources.OfficialDataError, match="identity"):
            apply(db, payload(5))
        db.rollback()
        assert getattr(db.get(ThemeGroup, group.id), field) == value


@pytest.mark.parametrize("change", [{"endpoint": "https://invalid"}, {"source": "tpex"}, {"sha256": "wrong"}, {"collected_at": datetime(2099, 1, 1)}])
def test_invalid_capture_fails(env, change):
    with env() as db:
        cap = payload()
        with pytest.raises(sources.OfficialDataError):
            apply(db, replace(cap, **change), record(cap))


def test_after_score_skip_and_utc_rollover(env):
    with env() as db:
        cap = payload(collected_at=datetime(2026, 9, 4, 16, 1))
        result = apply(db, cap, score=date(2026, 9, 4))
        assert rows(db) == []
        assert result["skipped_count"] == 1
        assert result["observations"][0]["observed_date"] == "2026-09-05"
        assert result["observations"][0]["score_date"] == "2026-09-04"


def test_new_listing_only_unresolved_keeps_industry(env):
    with env() as db:
        apply(db, payload())
        before = rows(db)
        cap = payload(5, endpoint=sources.TWSE_NEW_LISTING_ENDPOINT)
        result = apply(db, cap, record(cap, instrument_type="ipo", industry=None))
        assert rows(db) == before
        assert result["unresolved_count"] == 1


def test_hot_group_does_not_mask_or_close_industry(env):
    with env() as db:
        cap = payload()
        apply(db, cap, record(cap, instrument_type="ipo", listing_date=date(2026, 9, 1)))
        cap = payload(5)
        apply(db, cap, record(cap, industry="01", instrument_type="ipo", listing_date=date(2026, 9, 1)))
        industry = db.scalars(select(GroupMembership).join(ThemeGroup).where(ThemeGroup.group_type == "official_industry").order_by(GroupMembership.valid_from)).all()
        assert [(r.valid_from, r.valid_to) for r in industry] == [(date(2026, 9, 4), date(2026, 9, 4)), (date(2026, 9, 5), None)]
        hot = db.scalar(select(GroupMembership).join(ThemeGroup).where(ThemeGroup.group_type == "daily_hot_group"))
        assert hot.valid_from == date(2026, 9, 4) and hot.valid_to == date(2026, 10, 31)


def batch(cap, industry="24"):
    instruments = [record(cap, industry=industry), sources.InstrumentRecord("TAIEX", "Index", instrument_type="index", payload_sha256=cap.sha256)]
    bars = [sources.BarRecord(r.symbol, date(2026, 9, 4), 100, 101, 99, 100, 1000, 100000, exchange="TWSE", payload_sha256=cap.sha256) for r in instruments]
    return sources.OfficialBatch(instruments=instruments, bars=bars, payloads=[cap])


def collect(cap, industry="24", force=False):
    return pipeline.collect(date(2026, 9, 4), adapter=SimpleNamespace(fetch=lambda *_: batch(cap, industry)), force=force)


def test_collect_failed_normalization_retains_raw_and_rolls_back(env):
    result = collect(payload(), industry=None)
    assert result["status"] == "failed"
    with env() as db:
        assert db.scalar(select(func.count(RawPayload.id))) == 1
        assert db.scalar(select(func.count(MarketBar.id))) == 0
        assert db.scalar(select(func.count(GroupMembership.id))) == 0
        assert db.scalar(select(IngestionRun)).metadata_json["industry_observation_attempt"]["status"] == "failed"


@pytest.mark.parametrize("timestamp", [None, "not-a-timestamp"])
def test_collect_missing_capture_timestamp_records_failed_run(env, timestamp):
    result = collect(payload(collected_at=timestamp))
    assert result["status"] == "failed"
    with env() as db:
        run = db.scalar(select(IngestionRun))
        assert run.status == "failed"
        attempt = run.metadata_json["industry_observation_attempt"]
        assert attempt["captures"][0]["collected_at"] is None
        assert attempt["captures"][0]["timestamp_status"] == "missing_or_invalid"
        assert db.scalar(select(func.count(RawPayload.id))) == 0
        assert attempt["raw_payload_ids"] == []
        assert "timestamp" in attempt["raw_persistence_errors"][0]["reason"]
        assert attempt["captures"][0]["payload_path"]
        assert db.scalar(select(func.count(MarketBar.id))) == 0
        assert db.scalar(select(func.count(GroupMembership.id))) == 0


def test_collect_raw_persistence_failure_still_records_failed_run(env, monkeypatch):
    def reject(db, run, cap):
        raise ValueError("simulated raw persistence failure")
    monkeypatch.setattr(pipeline, "_upsert_raw_payload", reject)
    result = collect(payload())
    assert result["status"] == "failed"
    with env() as db:
        run = db.scalar(select(IngestionRun))
        assert run.status == "failed"
        attempt = run.metadata_json["industry_observation_attempt"]
        assert "simulated raw persistence failure" in attempt["raw_persistence_errors"][0]["reason"]
        assert db.scalar(select(func.count(MarketBar.id))) == 0


def test_collect_receipt_forced_same_digest_and_reuse(env):
    cap = payload()
    first = collect(cap)
    assert first["status"] == "success", first
    later = replace(cap, collected_at=datetime(2026, 9, 5, 1))
    forced = collect(later, force=True)
    assert forced["status"] == "success", forced
    result = forced["industry_membership_observations"]
    assert result["status"] == "partial" and result["skipped_count"] == 1
    receipt = result["observations"][0]
    assert receipt["captured_at_utc"].startswith("2026-09-05")
    assert receipt["stored_raw_collected_at_utc"].startswith("2026-09-04")
    reused = collect(later)
    assert reused["idempotent_reuse"] is True
    assert reused["industry_membership_observations"] == result
    with env() as db:
        assert db.scalar(select(func.count(RawPayload.id))) == 1
        assert len(rows(db)) == 1


@pytest.mark.parametrize("offset", [8, -5])
def test_collect_aware_capture_stores_utc_and_retains_earliest_on_force(env, offset):
    earliest_utc = datetime(2026, 9, 3, 17, tzinfo=timezone.utc)
    cap = payload(collected_at=earliest_utc.astimezone(timezone(timedelta(hours=offset))))
    first = collect(cap)
    assert first["status"] == "success", first
    receipt = first["industry_membership_observations"]["observations"][0]
    assert receipt["captured_at_utc"] == "2026-09-03T17:00:00+00:00"
    assert receipt["stored_raw_collected_at_utc"] == "2026-09-03T17:00:00+00:00"
    assert receipt["observed_date"] == "2026-09-04"
    with env() as db:
        raw = db.scalar(select(RawPayload))
        assert raw.collected_at == datetime(2026, 9, 3, 17)
        assert rows(db)[0][1] == date(2026, 9, 4)
    later = replace(cap, collected_at=cap.collected_at + timedelta(hours=1))
    forced = collect(later, force=True)
    assert forced["status"] == "success", forced
    receipt = forced["industry_membership_observations"]["observations"][0]
    assert receipt["captured_at_utc"] == "2026-09-03T18:00:00+00:00"
    assert receipt["stored_raw_collected_at_utc"] == "2026-09-03T17:00:00+00:00"
    assert receipt["observed_date"] == "2026-09-04"
    with env() as db:
        assert db.scalar(select(func.count(RawPayload.id))) == 1
        assert db.scalar(select(RawPayload)).collected_at == datetime(2026, 9, 3, 17)
        assert len(rows(db)) == 1


def test_success_force_failure_preserves_prior_evidence(env):
    first = collect(payload())
    assert first["status"] == "success"
    failed = collect(payload(5), industry=None, force=True)
    assert failed["status"] == "failed"
    with env() as db:
        run = db.scalar(select(IngestionRun))
        assert run.metadata_json["industry_membership_observations"] == first["industry_membership_observations"]
        assert run.metadata_json["industry_failed_attempts"][-1]["status"] == "failed"
        assert len(rows(db)) == 1
        assert db.scalar(select(func.count(MarketBar.id))) == 2


def test_manual_and_absent_instruments_untouched(env):
    with env() as db:
        apply(db, payload())
        row = db.scalar(select(GroupMembership))
        row.source = "manual"
        db.commit()
        before = rows(db)
        apply(db, payload(5), record(payload(5), industry="00"))
        assert rows(db) == before
        apply(db, payload(6), record(payload(6), symbol="BBB"))
        assert rows(db)[0] == before[0]


@pytest.mark.parametrize("duplicate", ["records", "captures"])
def test_duplicate_evidence_is_rejected_before_membership_mutation(env, duplicate):
    with env() as db:
        cap = payload()
        rec = record(cap)
        instrument = Instrument(symbol="AAA", name="Alpha", market="TW", exchange="TWSE", instrument_type="stock")
        db.add(instrument)
        db.flush()
        with pytest.raises(sources.OfficialDataError):
            pipeline._ensure_official_groups(db, [rec, rec] if duplicate == "records" else [rec],
                {("TWSE", "AAA"): instrument}, date(2000, 1, 1), date(2026, 9, 4),
                payloads=[cap, cap] if duplicate == "captures" else [cap], observed_now=datetime(2026, 9, 5))
        assert rows(db) == []


def test_etf_observation_period_semantics_remain_separate(env):
    with env() as db:
        cap = payload(endpoint=sources.TWSE_ETF_ENDPOINT)
        apply(db, cap, record(cap, instrument_type="etf", etf_category="broad_market"))
        existing = rows(db)
        assert existing[0][1] == date(2026, 9, 4)
        later = payload(5, endpoint=sources.TWSE_ETF_ENDPOINT)
        result = apply(db, later, record(later, instrument_type="etf", etf_category="broad_market"))
        assert rows(db) == existing
        assert result["observations"] == []
