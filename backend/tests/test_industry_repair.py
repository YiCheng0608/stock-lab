"""Issue #193: move pre-baseline industry memberships into canonical groups."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api import _product_group_taxonomy_verified
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ThemeGroup,
)
from app.taxonomy import canonical_group_id
from worker.industry_repair import (
    IndustryRepairError,
    plan_repair,
    repair_industry_memberships,
    rescore_recent,
)
from worker.pipeline import OFFICIAL_INDUSTRY_SOURCE, ensure_official_industry_group
from worker.sources import TPEX_LISTED_ENDPOINT, TWSE_LISTED_ENDPOINT

D0 = date(2026, 9, 8)
# 2026-09-08 11:44 UTC is 19:44 in Taipei: the observation date is D0.
CAPTURED = datetime(2026, 9, 8, 11, 44)
INSTRUMENTS = [
    # exchange, symbol, code, legacy (wrong) label or None for already-correct
    ("TWSE", "2881", "17", "Communications"),
    ("TWSE", "2882", "17", "Communications"),
    ("TWSE", "2377", "25", "Financial"),
    ("TWSE", "2330", "24", None),
    ("TWSE", "1101", "01", "Agriculture"),
    ("TWSE", "9105", "91", "91"),
    ("TPEx", "6026", "17", "Communications"),
    ("TPEx", "5508", "14", "Electronics"),
]


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'repair.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _legacy_group(db, label):
    group_id = canonical_group_id("industry", label)
    if db.get(ThemeGroup, group_id) is None:
        db.add(
            ThemeGroup(
                id=group_id,
                name=f"Industry · {label}",
                group_type="official_industry",
                definition_version="official-v1",
                source=OFFICIAL_INDUSTRY_SOURCE,
                active=True,
                display_name_zh={
                    "Communications": "通信網路",
                    "Financial": "金融",
                    "Semiconductor": "半導體",
                    "Agriculture": "農業科技",
                    "Electronics": "電子",
                    "Tourism": "觀光",
                }.get(label, f"產業代碼 {label}"),
                display_category="股票族群",
                name_source="TWSE/TPEx official classification",
                name_status="official" if not label.isdigit() else "pending",
            )
        )
        db.flush()
    return group_id


def _capture(db, tmp_path, exchange, codes, collected_at=CAPTURED, tamper=False):
    if exchange == "TWSE":
        payload = [
            {"公司代號": symbol, "產業別": code} for symbol, code in codes.items()
        ]
        endpoint = TWSE_LISTED_ENDPOINT
    else:
        payload = [
            {"SecuritiesCompanyCode": symbol, "SecuritiesIndustryCode": code}
            for symbol, code in codes.items()
        ]
        endpoint = TPEX_LISTED_ENDPOINT
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = tmp_path / f"{exchange}-{digest}.json"
    path.write_bytes(encoded + (b" " if tamper else b""))
    db.add(
        RawPayload(
            source=exchange.lower(),
            endpoint=endpoint,
            payload_path=str(path),
            sha256=digest,
            collected_at=collected_at,
        )
    )
    db.flush()


def _seed(factory, tmp_path, *, codes_override=None):
    with factory() as db:
        for exchange, symbol, code, legacy in INSTRUMENTS:
            instrument = Instrument(
                exchange=exchange,
                symbol=symbol,
                name=symbol,
                instrument_type="stock",
                industry=code,
                listing_date=date(2000, 1, 3),
                status="active",
            )
            db.add(instrument)
            db.flush()
            label = legacy or {"24": "Semiconductor"}[code]
            db.add(
                GroupMembership(
                    group_id=_legacy_group(db, label),
                    instrument_id=instrument.id,
                    role="member",
                    confidence=1.0,
                    valid_from=date(2000, 1, 3),
                    source=f"{OFFICIAL_INDUSTRY_SOURCE}; exchange={exchange}",
                )
            )
        _legacy_group(db, "Tourism")
        for exchange in ("TWSE", "TPEx"):
            codes = {
                symbol: code
                for ex, symbol, code, _legacy in INSTRUMENTS
                if ex == exchange
            }
            _capture(db, tmp_path, exchange, codes)
            _capture(
                db,
                tmp_path,
                exchange,
                {**codes, **(codes_override or {}).get(exchange, {})},
                collected_at=datetime(2026, 10, 17, 10, 0),
            )
        db.commit()


def _open_groups(db, symbol, on):
    return sorted(
        db.scalars(
            select(GroupMembership.group_id)
            .join(Instrument, Instrument.id == GroupMembership.instrument_id)
            .where(
                Instrument.symbol == symbol,
                GroupMembership.valid_from <= on,
                (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= on)),
            )
        ).all()
    )


def _snapshot(db):
    return (
        sorted(
            (m.group_id, m.instrument_id, m.valid_from, m.valid_to)
            for m in db.scalars(select(GroupMembership))
        ),
        sorted(
            (g.id, g.active, g.display_name_zh) for g in db.scalars(select(ThemeGroup))
        ),
        db.scalar(select(func.count(IngestionRun.id))),
    )


def test_dry_run_reports_changes_without_writing(factory, tmp_path):
    _seed(factory, tmp_path)
    with factory() as db:
        before = _snapshot(db)
        result = repair_industry_memberships(db)
        db.commit()
        assert _snapshot(db) == before
    assert result["status"] == "dry_run"
    assert result["memberships_closed"] == 7
    assert (
        result["memberships_opened"] == 6
    )  # 9105 (TDR 91) is closed without a replacement
    assert result["groups_created"] == [
        "Cement",
        "Computer and Peripherals",
        "Construction",
    ]
    assert {item.split(" ", 1)[1] for item in result["groups_deactivated"]} == {
        "Industry · 91",
        "Industry · Agriculture",
        "Industry · Electronics",
    }


def test_apply_moves_members_into_canonical_groups_and_is_idempotent(factory, tmp_path):
    _seed(factory, tmp_path)
    with factory() as db:
        result = repair_industry_memberships(db, apply=True, today=date(2026, 10, 18))
        db.commit()
    assert result["status"] == "applied"
    financial = canonical_group_id("industry", "Financial")
    with factory() as db:
        assert _open_groups(db, "2881", D0) == [financial]
        assert _open_groups(db, "6026", D0) == [financial]
        assert _open_groups(db, "2377", D0) == [
            canonical_group_id("industry", "Computer and Peripherals")
        ]
        assert _open_groups(db, "1101", D0) == [
            canonical_group_id("industry", "Cement")
        ]
        assert _open_groups(db, "5508", D0) == [
            canonical_group_id("industry", "Construction")
        ]
        assert _open_groups(db, "9105", D0) == []
        # History before D0 is kept as it was; nothing is deleted.
        assert _open_groups(db, "2881", date(2026, 9, 7)) == [
            canonical_group_id("industry", "Communications")
        ]
        assert db.scalar(select(func.count(GroupMembership.id))) == len(INSTRUMENTS) + 6
        assert _open_groups(db, "2330", D0) == [
            canonical_group_id("industry", "Semiconductor")
        ]
        assert not db.get(
            ThemeGroup, canonical_group_id("industry", "Agriculture")
        ).active
        assert not db.get(ThemeGroup, canonical_group_id("industry", "91")).active
        assert (
            db.get(
                ThemeGroup, canonical_group_id("industry", "Tourism")
            ).display_name_zh
            == "觀光餐旅"
        )
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == "industry_repair")
        )
        assert run.records == 7 and run.data_as_of == "2026-10-17"
        receipt = {(item["symbol"]): item for item in run.metadata_json["changes"]}
        assert receipt["2881"]["closed"][0]["new_valid_to"] == "2026-09-07"
        assert receipt["2881"]["opened"]["valid_from"] == "2026-09-08"

        # Every active official group now has a single member code and passes
        # the product taxonomy gate from D0 on.
        on = date(2026, 9, 10)
        for group in db.scalars(select(ThemeGroup).where(ThemeGroup.active.is_(True))):
            codes = set(
                db.scalars(
                    select(Instrument.industry)
                    .join(
                        GroupMembership, GroupMembership.instrument_id == Instrument.id
                    )
                    .where(
                        GroupMembership.group_id == group.id,
                        GroupMembership.valid_from <= on,
                        (
                            GroupMembership.valid_to.is_(None)
                            | (GroupMembership.valid_to >= on)
                        ),
                    )
                )
            )
            assert len(codes) <= 1, (group.name, codes)
            if codes:
                assert _product_group_taxonomy_verified(db, group, on), group.name
        before = _snapshot(db)
        again = repair_industry_memberships(db, apply=True)
        db.commit()
        assert again["status"] == "no_change"
        assert _snapshot(db) == before


def test_apply_fills_the_gap_before_a_collector_transition(factory, tmp_path):
    _seed(factory, tmp_path)
    financial = canonical_group_id("industry", "Financial")
    with factory() as db:
        # A weekday collector run observed 2881 on 2026-10-19 before the repair.
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "2881"))
        legacy = db.scalar(
            select(GroupMembership).where(
                GroupMembership.instrument_id == instrument.id
            )
        )
        legacy.valid_to = date(2026, 10, 18)
        db.add(
            GroupMembership(
                group_id=financial,
                instrument_id=instrument.id,
                role="member",
                confidence=1.0,
                valid_from=date(2026, 10, 19),
                source=f"{OFFICIAL_INDUSTRY_SOURCE}; exchange=TWSE",
            )
        )
        db.commit()
        repair_industry_memberships(db, apply=True)
        db.commit()
        rows = db.scalars(
            select(GroupMembership)
            .where(GroupMembership.instrument_id == instrument.id)
            .order_by(GroupMembership.valid_from)
        ).all()
        assert [(r.group_id == financial, r.valid_from, r.valid_to) for r in rows] == [
            (False, date(2000, 1, 3), date(2026, 9, 7)),
            (True, D0, date(2026, 10, 18)),
            (True, date(2026, 10, 19), None),
        ]


@pytest.mark.parametrize("problem", ["code_change", "tampered", "industry_mismatch"])
def test_inconsistent_evidence_rejects_the_whole_batch(factory, tmp_path, problem):
    _seed(
        factory,
        tmp_path,
        codes_override={"TWSE": {"2881": "25"}} if problem == "code_change" else None,
    )
    with factory() as db:
        if problem == "tampered":
            _capture(
                db,
                tmp_path,
                "TPEx",
                {"6026": "17"},
                collected_at=datetime(2026, 10, 18, 1, 0),
                tamper=True,
            )
        if problem == "industry_mismatch":
            db.scalar(
                select(Instrument).where(Instrument.symbol == "2377")
            ).industry = "24"
        db.commit()
        before = _snapshot(db)
        with pytest.raises(IndustryRepairError):
            repair_industry_memberships(db, apply=True)
        db.rollback()
        assert _snapshot(db) == before


def test_plan_uses_first_capture_date_per_instrument(factory, tmp_path):
    _seed(factory, tmp_path)
    with factory() as db:
        late = Instrument(
            exchange="TWSE",
            symbol="2883",
            name="2883",
            instrument_type="stock",
            industry="17",
            listing_date=date(2026, 10, 1),
            status="active",
        )
        db.add(late)
        db.flush()
        _capture(
            db,
            tmp_path,
            "TWSE",
            {"2883": "17"},
            collected_at=datetime(2026, 10, 16, 23, 30),
        )
        db.commit()
        plan = plan_repair(db)
    change = next(item for item in plan["changes"] if item["symbol"] == "2883")
    # 2026-10-16 23:30 UTC is already 2026-10-17 in Taipei.
    assert change["d0"] == date(2026, 10, 17) and change["closes"] == []
    assert change["opened"]["group_id"] == canonical_group_id("industry", "Financial")


def test_collector_helper_syncs_display_name_of_existing_group(factory):
    with factory() as db:
        group_id = _legacy_group(db, "Tourism")
        assert ensure_official_industry_group(db, "Tourism").id == group_id
        assert db.get(ThemeGroup, group_id).display_name_zh == "觀光餐旅"
        created = ensure_official_industry_group(db, "Electrical Cable")
        assert (
            created.display_name_zh == "電器電纜"
            and created.source == OFFICIAL_INDUSTRY_SOURCE
        )


def test_rescore_clears_rank_left_on_deactivated_groups(factory, tmp_path):
    _seed(factory, tmp_path)
    day = date(2026, 10, 16)
    with factory() as db:
        taiex = Instrument(
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        db.add(taiex)
        db.flush()
        db.add(
            MarketBar(
                instrument_id=taiex.id,
                trading_date=day,
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
            )
        )
        agriculture = canonical_group_id("industry", "Agriculture")
        db.add(
            GroupDailyScore(
                group_id=agriculture,
                trading_date=day,
                score=80.0,
                rank=2,
                data_quality="complete",
                eligible_members=7,
            )
        )
        db.add(
            GroupDailyScore(
                group_id=agriculture,
                trading_date=date(2026, 9, 1),
                score=70.0,
                rank=1,
                data_quality="complete",
                eligible_members=7,
            )
        )
        db.commit()
        repair_industry_memberships(db, apply=True)
        assert rescore_recent(db, 20) == [day.isoformat()]
        db.commit()
        ranks = dict(
            db.execute(
                select(GroupDailyScore.trading_date, GroupDailyScore.rank).where(
                    GroupDailyScore.group_id == agriculture
                )
            ).all()
        )
    # Only the rescored date is touched; the row itself is kept.
    assert ranks == {day: None, date(2026, 9, 1): 1}
