"""hot_group_v1 1.1.0 institutional-flow coverage (V1_SPEC hot_group_v1, #208).

A member absent from the day's received official institutional file counts as
zero net flow with evidence; a missing or mismatched file keeps it unavailable;
coverage is measured against eligible members; strategies and candidates keep
the fail-closed inputs; rows written by 1.0.0 are archived before an overwrite.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.candidates as candidates
import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import (
    HOT_GROUP_CONFIG,
    HOT_GROUP_LEGACY_VERSION,
    HOT_GROUP_VERSION,
)
from app.strategies import canonical_config_snapshot
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    Event,
    GroupDailyScore,
    GroupDailyScoreArchive,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    StrategyVersion,
    TechnicalFeature,
    ThemeGroup,
)
from worker.industry_repair import rescore_recent
from worker.sources import TPEX_CHIP_HISTORY_ENDPOINT, TWSE_CHIP_ENDPOINT

SCORE_DATE = date(2026, 9, 4)
LOCAL_API = "http://127.0.0.1:8000"
# Per-member constant flows (foreign, trust, dealer) and daily volume.
FLOWS = {"A": (30, 5, 1), "B": (-20, 5, 1), "C": (10, 0, 0), "D": (40, 5, 1)}
VOLUME = 1000


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _raw(db, exchange: str, day: date, *, data_as_of: str | None = None) -> RawPayload:
    endpoint = (
        f"{TWSE_CHIP_ENDPOINT}?date={day:%Y%m%d}&selectType=ALL&response=json"
        if exchange == "TWSE"
        else TPEX_CHIP_HISTORY_ENDPOINT
    )
    raw = RawPayload(
        source=exchange.lower(),
        endpoint=endpoint,
        sha256=f"{exchange}-{day.isoformat()}",
        data_as_of=data_as_of or day.isoformat(),
    )
    db.add(raw)
    db.flush()
    return raw


def _fixture(db, exchange: str = "TWSE"):
    """TAIEX plus four members of one industry; every chip row is from the official file."""

    dates = pipeline.business_days(SCORE_DATE, 25)
    benchmark = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="TAIEX",
        name="TAIEX",
        instrument_type="index",
        status="active",
    )
    db.add(benchmark)
    stocks = {}
    for index, symbol in enumerate(FLOWS):
        stocks[symbol] = Instrument(
            market="TW",
            exchange=exchange,
            symbol=symbol,
            name=symbol,
            instrument_type="stock",
            status="active",
        )
        db.add(stocks[symbol])
    db.flush()
    group = ThemeGroup(
        id="ind-x", name="ind-x", group_type="official_industry", active=True
    )
    peer = ThemeGroup(
        id="ind-peer", name="ind-peer", group_type="official_industry", active=True
    )
    db.add_all([group, peer])
    db.flush()
    for symbol in ("A", "B", "C"):
        db.add(
            GroupMembership(
                group_id=group.id,
                instrument_id=stocks[symbol].id,
                valid_from=dates[0],
                source="fixture",
            )
        )
    for symbol in ("A", "B", "D"):
        db.add(
            GroupMembership(
                group_id=peer.id,
                instrument_id=stocks[symbol].id,
                valid_from=dates[0],
                source="fixture",
            )
        )
    source = "twse_t86+twse_margin" if exchange == "TWSE" else "tpex_3insti+tpex_margin"
    raws = {}
    for index, day in enumerate(dates):
        level = 100 + index * 0.1
        db.add(
            MarketBar(
                instrument_id=benchmark.id,
                trading_date=day,
                open=level,
                high=level,
                low=level,
                close=level,
                adj_close=level,
                volume=0,
                turnover=0,
                source="fixture",
            )
        )
        raws[day] = _raw(db, exchange, day)
        for offset, (symbol, (foreign, trust, dealer)) in enumerate(FLOWS.items()):
            close = 50 * (1 + 0.001 * (offset + 1)) ** index
            db.add(
                MarketBar(
                    instrument_id=stocks[symbol].id,
                    trading_date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=VOLUME,
                    turnover=close * VOLUME,
                    turnover_status="available",
                    source="fixture",
                )
            )
            db.add(
                ChipSnapshot(
                    instrument_id=stocks[symbol].id,
                    trading_date=day,
                    foreign_buy=foreign,
                    trust_buy=trust,
                    dealer_buy=dealer,
                    margin_balance=1000,
                    margin_change=0,
                    source=source,
                    raw_payload_id=raws[day].id,
                )
            )
    for row in stocks.values():
        db.add(
            TechnicalFeature(
                instrument_id=row.id,
                trading_date=SCORE_DATE,
                features_json={},
                source="fixture",
            )
        )
    db.flush()
    return stocks, dates, raws


def _chip(db, instrument, day) -> ChipSnapshot:
    return db.scalar(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == instrument.id,
            ChipSnapshot.trading_date == day,
        )
    )


def _absent_from_file(db, instrument, day, *, margin_row: bool) -> None:
    chip = _chip(db, instrument, day)
    if margin_row:
        chip.foreign_buy = chip.trust_buy = chip.dealer_buy = None
        chip.source = "twse_margin" if instrument.exchange == "TWSE" else "tpex_margin"
        chip.raw_payload_id = None
    else:
        db.delete(chip)
    db.flush()


def _score(db, group_id="ind-x", day=SCORE_DATE) -> GroupDailyScore:
    return db.scalar(
        select(GroupDailyScore).where(
            GroupDailyScore.group_id == group_id, GroupDailyScore.trading_date == day
        )
    )


def _member(row: GroupDailyScore, symbol: str) -> dict:
    return next(
        item for item in row.details_json["member_returns"] if item["symbol"] == symbol
    )


@pytest.mark.parametrize("exchange", ["TWSE", "TPEx"])
def test_member_absent_from_received_official_file_counts_as_zero_with_evidence(
    factory, exchange
):
    with factory() as db:
        stocks, dates, raws = _fixture(db, exchange)
        # C traded on both days but is not in either official file: a margin-only
        # row on the score date, and no chip row at all two sessions earlier.
        _absent_from_file(db, stocks["C"], dates[-1], margin_row=True)
        _absent_from_file(db, stocks["C"], dates[-3], margin_row=False)
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()

        row = _score(db)
        coverage = row.details_json["institutional_flow_coverage"]
        assert (
            coverage["complete"] is True
            and coverage["available"] == coverage["eligible"] == 3
        )
        assert coverage["absent_from_official_file_members"] == 1
        assert coverage["absent_from_official_file_member_days"] == 2
        assert coverage["absent_from_official_file_dates"] == [
            dates[-3].isoformat(),
            dates[-1].isoformat(),
        ]
        member = _member(row, "C")
        assert member["institutional_flow_absent_from_official_file"] == [
            {
                "trading_date": dates[-3].isoformat(),
                "evidence_raw_payload_id": raws[dates[-3]].id,
            },
            {
                "trading_date": dates[-1].isoformat(),
                "evidence_raw_payload_id": raws[dates[-1]].id,
            },
        ]
        # Three present sessions of 10 shares over 20 x 1000 shares of volume.
        assert member[
            "hot_group_institutional_flow_to_sum_volume_ratio_5d"
        ] == pytest.approx(30 / 20000)
        assert _member(row, "A")["institutional_flow_absent_from_official_file"] == []
        expected = ((36 * 5) / 20000 + (-14 * 5) / 20000 + 30 / 20000) / 3
        assert row.details_json["raw_values"]["institutional_flow"] == pytest.approx(
            expected
        )
        assert row.institutional_flow is not None and row.rank is not None
        assert row.data_quality == "partial"  # no catalyst events in the fixture
        assert row.details_json["hot_group_version"] == HOT_GROUP_VERSION


def _no_file(db, stocks, day):
    # Nobody on the exchange has an official institutional row that day.
    for instrument in stocks.values():
        _absent_from_file(db, instrument, day, margin_row=True)


def _date_mismatch(db, stocks, day):
    _absent_from_file(db, stocks["C"], day, margin_row=True)
    for chip in db.scalars(
        select(ChipSnapshot).where(ChipSnapshot.trading_date == day)
    ):
        if chip.raw_payload_id:
            db.get(RawPayload, chip.raw_payload_id).data_as_of = (
                day - timedelta(days=1)
            ).isoformat()


def _other_endpoint(db, stocks, day):
    _absent_from_file(db, stocks["C"], day, margin_row=True)
    for chip in db.scalars(
        select(ChipSnapshot).where(ChipSnapshot.trading_date == day)
    ):
        if chip.raw_payload_id:
            db.get(
                RawPayload, chip.raw_payload_id
            ).endpoint = "https://openapi.twse.com.tw/v1/fund/T86"


def _other_exchange_file_only(db, stocks, day):
    # The TWSE file of that day is missing; a TPEx file is not evidence for C.
    _no_file(db, stocks, day)
    tpex = Instrument(
        market="TW",
        exchange="TPEx",
        symbol="T1",
        name="T1",
        instrument_type="stock",
        status="active",
    )
    db.add(tpex)
    db.flush()
    db.add(
        ChipSnapshot(
            instrument_id=tpex.id,
            trading_date=day,
            foreign_buy=1,
            trust_buy=0,
            dealer_buy=0,
            source="tpex_3insti",
            raw_payload_id=_raw(db, "TPEx", day).id,
        )
    )


def _official_row_with_null_component(db, stocks, day):
    _chip(db, stocks["C"], day).trust_buy = None


@pytest.mark.parametrize(
    "breaker",
    [
        _no_file,
        _date_mismatch,
        _other_endpoint,
        _other_exchange_file_only,
        _official_row_with_null_component,
    ],
)
def test_member_stays_unavailable_without_a_received_matching_official_file(
    factory, breaker
):
    with factory() as db:
        stocks, dates, _raws = _fixture(db)
        breaker(db, stocks, dates[-2])
        db.flush()
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()

        row = _score(db)
        coverage = row.details_json["institutional_flow_coverage"]
        assert (
            coverage["complete"] is False
            and coverage["absent_from_official_file_members"] == 0
        )
        assert (
            _member(row, "C")["hot_group_institutional_flow_to_sum_volume_ratio_5d"]
            is None
        )
        assert row.institutional_flow is None and row.score is None and row.rank is None
        assert row.data_quality == "insufficient_data"


def test_coverage_base_is_eligible_members(factory):
    with factory() as db:
        stocks, dates, _raws = _fixture(db)
        # E is an effective member without a bar on the score date: counted in
        # member_count, not eligible, and no longer blocks the flow component.
        late = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="E",
            name="E",
            instrument_type="stock",
            status="active",
        )
        db.add(late)
        db.flush()
        db.add(
            GroupMembership(
                group_id="ind-x",
                instrument_id=late.id,
                valid_from=dates[0],
                source="fixture",
            )
        )
        for day in dates[:-1]:
            db.add(
                MarketBar(
                    instrument_id=late.id,
                    trading_date=day,
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adj_close=10,
                    volume=VOLUME,
                    turnover=10 * VOLUME,
                    turnover_status="available",
                    source="fixture",
                )
            )
        db.flush()
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()

        row = _score(db)
        coverage = row.details_json["institutional_flow_coverage"]
        assert (
            coverage["eligible"],
            coverage["member_count"],
            coverage["available"],
        ) == (3, 4, 3)
        assert coverage["complete"] is True and row.eligible_members == 3
        flows = [
            _member(row, s)["hot_group_institutional_flow_to_sum_volume_ratio_5d"]
            for s in ("A", "B", "C")
        ]
        assert row.details_json["raw_values"]["institutional_flow"] == pytest.approx(
            sum(flows) / 3
        )
        assert row.rank is not None


def test_strategy_and_candidate_flow_inputs_keep_failing_closed(factory):
    with factory() as db:
        stocks, dates, _raws = _fixture(db)
        _absent_from_file(db, stocks["C"], dates[-1], margin_row=True)
        _absent_from_file(db, stocks["C"], dates[-3], margin_row=False)

        # Present member: the strategy and candidate values are the v2 formula, unchanged.
        assert pipeline._validated_flow_and_volume_inputs(
            db, stocks["A"].id, SCORE_DATE
        ) == (36 * 5, [VOLUME] * 20)
        assert pipeline._strategy_institutional_flow_to_average_volume_ratio(
            db, stocks["A"].id, SCORE_DATE
        ) == pytest.approx(36 * 5 / VOLUME)
        chips_a = candidates._chip_inputs(db, stocks["A"].id, SCORE_DATE)
        assert chips_a["institutional_flow_5d"] == pytest.approx(36 * 5 / VOLUME)
        assert chips_a["institutional_flow_20d"] == pytest.approx(36 * 20 / VOLUME)

        # Absent member: strategies and candidates still see missing data.
        assert (
            pipeline._validated_flow_and_volume_inputs(db, stocks["C"].id, SCORE_DATE)
            is None
        )
        assert (
            pipeline._strategy_institutional_flow_to_average_volume_ratio(
                db, stocks["C"].id, SCORE_DATE
            )
            is None
        )
        chips_c = candidates._chip_inputs(db, stocks["C"].id, SCORE_DATE)
        assert (
            chips_c["institutional_flow_5d"] is None
            and chips_c["institutional_flow_20d"] is None
        )
        # Without evidence the hot_group helper keeps the strategy behaviour too.
        assert (
            pipeline._hot_group_institutional_flow_ratio(db, stocks["C"].id, SCORE_DATE)
            is None
        )


def _legacy_row(db, group_id, day, **fields) -> GroupDailyScore:
    """A row as 1.0.0 wrote it: no ``hot_group_version`` marker."""

    values = dict(
        relative_return=0.01,
        relative_return_1d=0.001,
        relative_return_5d=0.005,
        relative_return_20d=0.01,
        breadth=0.5,
        volume_strength=0.4,
        institutional_flow=None,
        catalyst=None,
        score=None,
        rank=None,
        eligible_members=3,
        data_quality="insufficient_data",
        details_json={
            "institutional_flow_coverage": {
                "available": 2,
                "eligible": 3,
                "complete": False,
            }
        },
    )
    values.update(fields)
    row = GroupDailyScore(group_id=group_id, trading_date=day, **values)
    db.add(row)
    db.flush()
    return row


ROW_FIELDS = (
    "group_id",
    "trading_date",
    "relative_return",
    "relative_return_1d",
    "relative_return_5d",
    "relative_return_20d",
    "breadth",
    "volume_strength",
    "institutional_flow",
    "catalyst",
    "score",
    "rank",
    "eligible_members",
    "data_quality",
    "details_json",
)


def _fields(row) -> dict:
    return {name: getattr(row, name) for name in ROW_FIELDS}


def test_overwriting_a_1_0_0_row_archives_it_first_and_keeps_other_rows(factory):
    with factory() as db:
        stocks, dates, _raws = _fixture(db)
        _absent_from_file(db, stocks["C"], dates[-1], margin_row=True)
        legacy = _legacy_row(db, "ind-x", SCORE_DATE)
        untouched = _legacy_row(db, "ind-x", dates[-2])
        before, before_untouched = _fields(legacy), _fields(untouched)
        db.commit()

        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.commit()

        archived = db.scalars(select(GroupDailyScoreArchive)).all()
        assert len(archived) == 1
        copy = archived[0]
        assert _fields(copy) == before
        assert (copy.score_id, copy.hot_group_version) == (
            legacy.id,
            HOT_GROUP_LEGACY_VERSION,
        )
        assert (
            copy.archive_reason == f"superseded_by_{HOT_GROUP_VERSION}"
            and copy.archived_at is not None
        )
        rescored = _score(db)
        assert (
            rescored.id == legacy.id
            and rescored.details_json["hot_group_version"] == HOT_GROUP_VERSION
        )
        assert rescored.data_quality == "partial" and rescored.rank is not None
        assert _fields(_score(db, day=dates[-2])) == before_untouched

        # Recomputing a 1.1.0 row is the same version: nothing more is archived.
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.commit()
        assert len(db.scalars(select(GroupDailyScoreArchive)).all()) == 1


def test_rescore_archives_before_clearing_an_inactive_groups_rank(factory):
    with factory() as db:
        _stocks, dates, _raws = _fixture(db)
        gone = ThemeGroup(
            id="ind-gone", name="ind-gone", group_type="official_industry", active=False
        )
        db.add(gone)
        db.flush()
        stale = _legacy_row(db, "ind-gone", SCORE_DATE, rank=1, score=50.0)
        before = _fields(stale)
        db.commit()

        assert rescore_recent(db, 1) == [SCORE_DATE.isoformat()]
        db.commit()

        assert _score(db, "ind-gone").rank is None
        copies = {
            row.group_id: row for row in db.scalars(select(GroupDailyScoreArchive))
        }
        assert _fields(copies["ind-gone"]) == before
        assert copies["ind-gone"].archive_reason == "rank_cleared_inactive_group"


def test_new_version_gets_its_own_strategy_row_and_leaves_1_0_0_untouched(factory):
    with factory() as db:
        old_snapshot = canonical_config_snapshot()["hot_group_v1"]
        old_snapshot["version"] = HOT_GROUP_LEGACY_VERSION
        del old_snapshot["components"]["institutional_flow"]["coverage"]
        old = StrategyVersion(
            name="hot_group_v1",
            version=HOT_GROUP_LEGACY_VERSION,
            formula_version=HOT_GROUP_CONFIG["components"]["institutional_flow"][
                "formula"
            ]["formula_version"],
            kind="group_ranking",
            config_json=old_snapshot,
            canonical_config_snapshot=old_snapshot,
        )
        db.add(old)
        db.commit()
        before = (
            old.id,
            old.version,
            old.formula_version,
            old.config_json,
            old.canonical_config_snapshot,
            old.active,
        )

        versions = pipeline._ensure_strategies(db)
        db.commit()

        assert versions["hot_group_v1"].version == HOT_GROUP_VERSION == "1.1.0"
        assert versions["hot_group_v1"].id != old.id
        db.refresh(old)
        assert (
            old.id,
            old.version,
            old.formula_version,
            old.config_json,
            old.canonical_config_snapshot,
            old.active,
        ) == before
        coverage = versions["hot_group_v1"].config_json["components"][
            "institutional_flow"
        ]["coverage"]
        assert coverage["member_base"] == "eligible_members"
        assert coverage["absent_from_official_file"] == "net_zero_with_evidence"


@pytest.fixture
def api_client(factory, monkeypatch):
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app, base_url=LOCAL_API) as client:
        yield client
    app.dependency_overrides.pop(api_module.get_db, None)


@pytest.mark.parametrize("with_catalyst", [False, True])
def test_api_board_quality_for_a_zero_filled_group(factory, api_client, with_catalyst):
    with factory() as db:
        stocks, dates, _raws = _fixture(db)
        _absent_from_file(db, stocks["C"], dates[-1], margin_row=True)
        if with_catalyst:
            for group_member in ("A", "D"):
                db.add(
                    Event(
                        instrument_id=stocks[group_member].id,
                        event_date=SCORE_DATE,
                        event_type="material",
                        title="fixture",
                        source="mops_material_information",
                    )
                )
        db.flush()
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=SCORE_DATE,
                status="success",
                records=1,
                data_as_of=SCORE_DATE.isoformat(),
            )
        )
        db.commit()

    body = api_client.get("/api/themes", params={"board": "industry"}).json()
    item = next(entry for entry in body["items"] if entry["theme_id"] == "ind-x")
    assert item["quality"] == ("complete" if with_catalyst else "partial")
    assert item["rank"] is not None
