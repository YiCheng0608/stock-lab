"""A non-margin security's margin condition is not applicable (Issue #392).

AC-1: the official margin-trading lists are stored per exchange and session
from the stored raw, with source and data date; without a list the margin
condition stays missing.  AC-2: a security absent from the list is judged
with the margin condition not applicable; a listed security without margin
values stays ``data_incomplete``.  AC-3: ``breakout_v1``／``pullback_v1``
are not rewritten; the pages read v1 on its days and never both versions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import decision
from app.db import Base, enable_sqlite_foreign_keys
from app.margin_lists import (
    APPLICABLE,
    MISSING,
    NOT_APPLICABLE,
    NOT_APPLICABLE_REASON,
    margin_financing_state,
)
from app.models import (
    ChipSnapshot,
    Instrument,
    MarginList,
    MarketBar,
    RawPayload,
    Signal,
    StrategyVersion,
    TechnicalFeature,
)
from app.strategies import (
    REGISTRY,
    SUCCESSOR,
    SUPERSEDED,
    StrategyInputs,
    canonical_config_snapshot,
    levels,
)
from app.strategies.breakout_v1 import evaluate_breakout_v1
from app.strategies.pullback_v1 import evaluate_pullback_v1
from worker import margin_lists, pipeline
from worker.sources import TPEX_MARGIN_HISTORY_ENDPOINT, TWSE_MARGIN_HISTORY_ENDPOINT

T = date(2026, 10, 30)
SESSIONS = pipeline.business_days(T, 21)
# The versions #392 superseded; breakout_v2／pullback_v2 are superseded in
# turn by breakout_v3／pullback_v3 (#404), which keep the rule tested here.
V1 = ("breakout_v1", "pullback_v1")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    pipeline._MARGIN_LIST_CACHE.clear()
    with factory() as session:
        yield session
    pipeline._MARGIN_LIST_CACHE.clear()
    engine.dispose()


# ---- official report payloads ----


def twse_report(day: date, rows: list[tuple[str, str]]) -> dict[str, Any]:
    """MI_MARGN selectType=ALL: a summary table, then 融資融券彙總 (全部)."""

    fields = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額"]
    fields += ["次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額"]
    fields += ["次一營業日限額", "資券互抵", "註記"]
    return {
        "date": day.strftime("%Y%m%d"),
        "stat": "OK",
        "tables": [
            {
                "title": "信用交易統計",
                "fields": ["項目", "買進"],
                "data": [["融資", "1"]],
            },
            {
                "title": "融資融券彙總 (全部)",
                "fields": fields,
                "data": [
                    [code, code, "0", "0", "0", "10", "11", *["0"] * 8, note]
                    for code, note in rows
                ],
            },
        ],
    }


def tpex_report(day: date, rows: list[tuple[str, str]]) -> dict[str, Any]:
    """上櫃股票融資融券餘額, with its two code-less 合計 rows first."""

    fields = ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額"]
    fields += ["資屬證金", "資使用率(%)", "資限額", "前券餘額(張)", "券賣", "券買"]
    fields += ["券償", "券餘額", "券屬證金", "券使用率(%)", "券限額", "資券相抵(張)"]
    fields += ["備註"]
    return {
        "date": day.strftime("%Y%m%d"),
        "stat": "ok",
        "tables": [
            {
                "title": "上櫃股票融資融券餘額",
                "fields": fields,
                "data": [
                    ["", "合計(張)", *["1"] * 18],
                    ["", "融資金(仟元)", *["1"] * 18],
                    *[
                        [code, code, "10", *["0"] * 3, "11", *["0"] * 14, note]
                        for code, note in rows
                    ],
                ],
            }
        ],
    }


def store_raw(
    db,
    tmp_path,
    exchange: str,
    day: date,
    payload: Any,
    *,
    collected_at: datetime | None = None,
) -> RawPayload:
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / f"{exchange}-{day.isoformat()}-{digest[:8]}.json"
    path.write_bytes(content)
    if exchange == "TWSE":
        source = "twse"
        endpoint = (
            f"{TWSE_MARGIN_HISTORY_ENDPOINT}?date={day.strftime('%Y%m%d')}"
            "&selectType=ALL&response=json"
        )
    else:
        source, endpoint = "tpex", TPEX_MARGIN_HISTORY_ENDPOINT
    row = RawPayload(
        source=source,
        endpoint=endpoint,
        payload_path=str(path),
        sha256=digest,
        data_as_of=day.isoformat(),
        collected_at=collected_at or datetime(day.year, day.month, day.day, 13, 30),
    )
    db.add(row)
    db.flush()
    return row


def stored_list(db, exchange: str, day: date) -> MarginList | None:
    return db.scalar(
        select(MarginList).where(
            MarginList.exchange == exchange, MarginList.trading_date == day
        )
    )


# ---- AC-1: the lists ----


def test_the_lists_parse_codes_and_notes_and_skip_total_rows():
    twse = margin_lists.parse_margin_list(
        twse_report(T, [("2330", " "), ("00400A", "X "), ("1101", "OX!")]), "TWSE"
    )
    assert twse == {"2330": "", "00400A": "X", "1101": "OX!"}
    tpex = margin_lists.parse_margin_list(
        tpex_report(T, [("8299", ""), ("7794", "X")]), "TPEx"
    )
    assert tpex == {"8299": "", "7794": "X"}
    # A report without its security rows is no list, never an empty one.
    assert margin_lists.parse_margin_list(twse_report(T, []), "TWSE") is None
    assert margin_lists.parse_margin_list({"date": "20261030"}, "TPEx") is None
    assert margin_lists.parse_margin_list(tpex_report(T, []), "TPEx") is None


def test_a_list_is_stored_with_its_source_date_and_raw(db, tmp_path):
    raw = store_raw(db, tmp_path, "TWSE", T, twse_report(T, [("2330", "")]))
    tpex_raw = store_raw(db, tmp_path, "TPEx", T, tpex_report(T, [("8299", "O")]))

    result = margin_lists.sync_margin_lists(db, [T])

    assert result["status"] == "success"
    assert (result["written"], result["missing"]) == (2, 0)
    row = stored_list(db, "TWSE", T)
    assert (row.source, row.data_as_of, row.raw_payload_id) == (
        "twse_margin",
        "2026-10-30",
        raw.id,
    )
    assert row.endpoint == raw.endpoint
    assert row.collected_at == raw.collected_at
    assert (row.member_count, row.members_json) == (1, {"2330": ""})
    other = stored_list(db, "TPEx", T)
    assert (other.source, other.raw_payload_id, other.members_json) == (
        "tpex_margin",
        tpex_raw.id,
        {"8299": "O"},
    )


def test_the_latest_capture_with_rows_of_the_date_is_the_list(db, tmp_path):
    # 18:30 has no margin yet; 21:30 has it; a capture reporting another date
    # (a fallback to the latest day) is not this session's list.
    early = datetime(2026, 10, 30, 10, 30)
    store_raw(db, tmp_path, "TWSE", T, twse_report(T, []), collected_at=early)
    good = store_raw(
        db,
        tmp_path,
        "TWSE",
        T,
        twse_report(T, [("2330", "")]),
        collected_at=early + timedelta(hours=3),
    )
    store_raw(
        db,
        tmp_path,
        "TWSE",
        T,
        twse_report(T - timedelta(days=1), [("9999", "")]),
        collected_at=early + timedelta(hours=5),
    )

    assert margin_lists.store_margin_list(db, "TWSE", T) == "written"
    assert stored_list(db, "TWSE", T).raw_payload_id == good.id
    # The same codes and notes again are not rewritten.
    assert margin_lists.store_margin_list(db, "TWSE", T) == "unchanged"


def test_a_session_without_a_usable_capture_has_no_list(db, tmp_path):
    store_raw(db, tmp_path, "TWSE", T, twse_report(T, []))

    result = margin_lists.sync_margin_lists(db, [T])

    assert result["status"] == "partial"
    assert result["missing"] == 2
    assert result["missing_samples"] == ["TWSE:2026-10-30", "TPEx:2026-10-30"]
    assert db.scalars(select(MarginList)).all() == []


def test_a_file_that_does_not_match_its_hash_stops_the_sync(db, tmp_path):
    raw = store_raw(db, tmp_path, "TWSE", T, twse_report(T, [("2330", "")]))
    raw.sha256 = "0" * 64
    db.flush()

    result = margin_lists.sync_margin_lists(db, [T])

    assert result["status"] == "failed"
    assert result["failed_date"] == "2026-10-30"
    assert stored_list(db, "TWSE", T) is None


def test_the_backfill_covers_every_stored_session(db, tmp_path):
    for day in SESSIONS[-3:]:
        store_raw(db, tmp_path, "TWSE", day, twse_report(day, [("2330", "")]))
        store_raw(db, tmp_path, "TPEx", day, tpex_report(day, [("8299", "")]))

    result = margin_lists.sync_margin_lists(db, commit_each=True)

    assert (result["dates"], result["written"], result["status"]) == (
        3,
        6,
        "success",
    )
    assert result["first_date"] == SESSIONS[-3].isoformat()
    rerun = margin_lists.sync_margin_lists(db, start=SESSIONS[-2])
    assert (rerun["dates"], rerun["unchanged"], rerun["written"]) == (2, 4, 0)


# ---- the state ----


def test_the_margin_condition_state():
    listed = {"2330"}
    window = [listed] * 6
    assert margin_financing_state("2330", 0.01, window) == APPLICABLE
    # A computable ratio is applicable, whatever the lists say.
    assert margin_financing_state("9999", 0.0, [None] * 6) == APPLICABLE
    assert margin_financing_state("9999", None, window) == NOT_APPLICABLE
    # Only the signal day's list is needed to know it is not a margin security.
    assert margin_financing_state("9999", None, [None] * 5 + [listed]) == (
        NOT_APPLICABLE
    )
    # Listed on T but not over the whole window: no ratio is defined.
    assert margin_financing_state("2330", None, [set()] + [listed] * 5) == (
        NOT_APPLICABLE
    )
    # Listed but without margin values: missing data.
    assert margin_financing_state("2330", None, window) == MISSING
    # No list on T, or a gap in the window of a listed one: unknown, missing.
    assert margin_financing_state("9999", None, [listed] * 5 + [None]) == MISSING
    assert margin_financing_state("2330", None, [None] + [listed] * 5) == MISSING
    assert margin_financing_state("2330", None, [listed] * 3) == MISSING
    assert margin_financing_state("9999", float("nan"), []) == MISSING


# ---- AC-2: analyze ----


def _instrument(db, exchange: str, symbol: str) -> Instrument:
    instrument = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status="active",
    )
    db.add(instrument)
    db.flush()
    for index, day in enumerate(SESSIONS):
        last = day == T
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=99,
                high=101 if last else 100,
                low=98,
                close=101 if last else 99,
                adj_close=101 if last else 99,
                volume=2000 if last else 1000,
                turnover=100000,
                source="fixture",
            )
        )
    db.add(
        TechnicalFeature(
            instrument_id=instrument.id,
            trading_date=T,
            features_json={"bar_count_60d": 60, "ma20": 100, "ma60": 90, "atr14": 2},
            source="fixture",
        )
    )
    db.flush()
    return instrument


def _margin_rows(db, instrument: Instrument, days: list[date]) -> None:
    for day in days:
        db.add(
            ChipSnapshot(
                instrument_id=instrument.id,
                trading_date=day,
                margin_balance=100,
                margin_change=0,
                source="twse_margin",
                data_as_of=datetime(day.year, day.month, day.day),
            )
        )
    db.flush()


def _lists(db, tmp_path, exchange: str, codes: list[str]) -> None:
    report = twse_report if exchange == "TWSE" else tpex_report
    for day in SESSIONS[-6:]:
        store_raw(db, tmp_path, exchange, day, report(day, [(c, "") for c in codes]))
    margin_lists.sync_margin_lists(db, SESSIONS[-6:])


@pytest.fixture
def analyzed(db, tmp_path, monkeypatch):
    """T analyzed for a margin security, a non-margin one and two without data."""

    monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline,
        "_resolve_group_member_return",
        lambda *_args: (0.02, {"status": "fixture"}),
    )
    monkeypatch.setattr(
        pipeline,
        "_strategy_institutional_flow_to_average_volume_ratio",
        lambda *_args, **_kwargs: 0.0,
    )
    margin = _instrument(db, "TWSE", "MRG")
    _margin_rows(db, margin, SESSIONS[-6:])
    plain = _instrument(db, "TWSE", "NOM")
    gap = _instrument(db, "TWSE", "GAP")
    _margin_rows(db, gap, SESSIONS[-6:-1])  # listed, no margin values on T
    unknown = _instrument(db, "TPEx", "NOL")  # no TPEx list stored at all
    _lists(db, tmp_path, "TWSE", ["MRG", "GAP"])
    strategies = pipeline._ensure_strategies(db)
    for instrument in (margin, plain, gap, unknown):
        assert pipeline._upsert_signal(
            db, instrument=instrument, signal_date=T, strategies=strategies
        )
    db.flush()
    rows = db.execute(
        select(Signal, StrategyVersion.name, Instrument.symbol)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
    ).all()
    return {(symbol, name): signal for signal, name, symbol in rows}


def test_a_non_margin_security_is_judged_with_the_margin_condition_not_applicable(
    analyzed,
):
    for name in REGISTRY:
        signal = analyzed[("NOM", name)]
        kind = REGISTRY[name].kind
        # Judged by the rule (the fixture has no group score, so a passed
        # rule is held back for MRG alike; see the comparison below).
        assert signal.rule_evidence_json[kind]["state"] in {"passed", "rejected"}, (
            name,
            signal.rationale,
        )
        inputs = signal.rule_evidence_json["inputs"]
        assert inputs["margin_balance_change_ratio_5d"] is None
        assert inputs["margin_eligibility"] == NOT_APPLICABLE
        assert "margin" not in json.dumps(signal.rule_evidence_json[kind])
    # The same day's margin security is judged on its ratio as before.
    assert (
        analyzed[("MRG", "breakout_v3")].rule_evidence_json["inputs"][
            "margin_eligibility"
        ]
        == APPLICABLE
    )
    # NOM and MRG differ only in margin: their judgements are the same.
    for name in REGISTRY:
        assert (
            analyzed[("NOM", name)].status,
            analyzed[("NOM", name)].rule_evidence_json[REGISTRY[name].kind],
        ) == (
            analyzed[("MRG", name)].status,
            analyzed[("MRG", name)].rule_evidence_json[REGISTRY[name].kind],
        )


def test_a_margin_security_without_margin_values_stays_data_incomplete(analyzed):
    for name in REGISTRY:
        signal = analyzed[("GAP", name)]
        assert signal.status == "data_incomplete"
        assert signal.rule_evidence_json["inputs"]["margin_eligibility"] == MISSING
        assert signal.rule_evidence_json[REGISTRY[name].kind]["reasons"] == [
            "margin_balance_change_ratio_5d_missing_or_non_finite"
        ]


def test_without_an_official_list_the_margin_condition_stays_missing(analyzed):
    for name in REGISTRY:
        signal = analyzed[("NOL", name)]
        assert signal.status == "data_incomplete"
        assert signal.rule_evidence_json["inputs"]["margin_eligibility"] == MISSING
        assert (
            "margin_balance_change_ratio_5d_missing_or_non_finite"
            in signal.rule_evidence_json[REGISTRY[name].kind]["reasons"]
        )


def test_the_v1_rules_still_fail_closed_on_the_same_inputs(analyzed):
    """v1 is not changed: a non-margin security is still incomplete for it."""

    inputs = analyzed[("NOM", "breakout_v3")].rule_evidence_json["inputs"]
    common = dict(
        close=101.0,
        volume=2000.0,
        prior_volumes=inputs["prior_20_volumes"],
        group_excess_return_20d=inputs["group_excess_return_20d"],
        institutional_flow_to_turnover_ratio_5d=0.0,
        margin_balance_change_ratio_5d=None,
    )
    breakout = evaluate_breakout_v1(prior_highs=inputs["prior_20_highs"], **common)
    pullback = evaluate_pullback_v1(bar_count=60, ma20=100.0, ma60=90.0, **common)
    for result in (breakout, pullback):
        assert result.state == "data_incomplete"
        assert result.reasons == (
            "margin_balance_change_ratio_5d_missing_or_non_finite",
        )


def test_the_condition_list_says_not_applicable(analyzed):
    signal = analyzed[("NOM", "breakout_v3")]
    inputs = signal.rule_evidence_json["inputs"]
    strategy_inputs = StrategyInputs(
        bar_count=60,
        close=101.0,
        volume=2000.0,
        ma20=100.0,
        ma60=90.0,
        atr14=2.0,
        prior_highs=inputs["prior_20_highs"],
        prior_volumes=inputs["prior_20_volumes"],
        group_excess_return_20d=0.02,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=None,
        margin_financing=NOT_APPLICABLE,
    )
    for strategy in REGISTRY.values():
        evaluation = strategy.evaluate(strategy_inputs)
        assert evaluation.state != "data_incomplete"
        margin = next(
            item
            for item in strategy.conditions(
                strategy_inputs, evaluation, levels.ObservationLevels("levels")
            )
            if item.code == "margin_financing"
        )
        assert (margin.satisfied, margin.reasons) == (None, (NOT_APPLICABLE_REASON,))
    # The next session's levels do not wait for a margin ratio either.
    assert "margin_balance_change_ratio_5d_missing_or_non_finite" not in (
        levels.missing_confirmations(
            levels.NextSessionInputs(
                instrument_type="stock",
                etf_category=None,
                bar_count=60,
                is_suspended=False,
                close=101.0,
                atr14=2.0,
                closes=(),
                highs=(),
                volumes=(),
                group_excess_return_20d=0.02,
                institutional_flow_ratio_5d=0.0,
                margin_change_ratio_5d=None,
                margin_financing=NOT_APPLICABLE,
            )
        )
    )


def test_the_decision_does_not_list_margin_as_missing(db, analyzed):
    result = decision._strategy_result(
        analyzed[("NOM", "breakout_v3")],
        "breakout_v3",
        T,
        strategy_version=db.scalar(
            select(StrategyVersion).where(StrategyVersion.name == "breakout_v3")
        ),
    )
    assert "margin_balance_change_ratio_5d" not in result["missing"]


# ---- AC-3: the old versions ----


def _v1_signal(db, instrument: Instrument, day: date, name: str) -> Signal:
    strategy = SUPERSEDED[name]
    version = db.scalar(select(StrategyVersion).where(StrategyVersion.name == name))
    if version is None:
        snapshot = canonical_config_snapshot(SUPERSEDED)[name]
        version = StrategyVersion(
            name=name,
            version=strategy.version,
            formula_version=pipeline.INSTITUTIONAL_FLOW_FORMULA_VERSION,
            kind=strategy.kind,
            config_json=snapshot,
            canonical_config_snapshot=snapshot,
        )
        db.add(version)
        db.flush()
    signal = Signal(
        signal_key=(
            f"analysis-{instrument.exchange}-{instrument.symbol}-{day.isoformat()}-"
            f"{name}-{strategy.version}"
        ),
        signal_date=day,
        instrument_id=instrument.id,
        strategy_version_id=version.id,
        status="data_incomplete",
        entry_type=strategy.entry_type,
        data_quality="partial",
        rationale="v1 fixture",
        rule_evidence_json={"strategy": name, "inputs": {}},
    )
    db.add(signal)
    db.flush()
    return signal


def _row(signal: Signal) -> dict[str, Any]:
    return {
        column.name: getattr(signal, column.name) for column in Signal.__table__.columns
    }


def test_analyze_writes_only_v2_and_leaves_the_v1_rows_alone(db, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline, "_resolve_group_member_return", lambda *_args: (0.02, {})
    )
    instrument = _instrument(db, "TWSE", "NOM")
    _lists(db, tmp_path, "TWSE", ["MRG"])
    old = {
        (day, name): _v1_signal(db, instrument, day, name)
        for day in (SESSIONS[-2], T)
        for name in V1
    }
    before = {key: _row(signal) for key, signal in old.items()}

    strategies = pipeline._ensure_strategies(db)
    assert set(strategies) == {*REGISTRY, "hot_group_v1"}
    pipeline._upsert_signal(
        db, instrument=instrument, signal_date=T, strategies=strategies
    )
    db.flush()
    db.expire_all()

    for key, signal in old.items():
        assert _row(db.get(Signal, signal.id)) == before[key]
    names = db.scalars(
        select(StrategyVersion.name)
        .join(Signal, Signal.strategy_version_id == StrategyVersion.id)
        .where(Signal.signal_date == T)
    ).all()
    assert sorted(names) == sorted([*REGISTRY, *V1])


def test_the_pages_read_v1_on_its_days_and_never_both_versions(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline, "_resolve_group_member_return", lambda *_args: (0.02, {})
    )
    instrument = _instrument(db, "TWSE", "NOM")
    _lists(db, tmp_path, "TWSE", ["MRG"])
    earlier = SESSIONS[-2]
    v1 = {name: _v1_signal(db, instrument, earlier, name) for name in V1}
    # The registered key each v1 strategy is read as.
    assert {name: SUCCESSOR[name] for name in V1} == {
        "breakout_v1": "breakout_v3",
        "pullback_v1": "pullback_v4",
    }

    # Only v1 so far: the pages show it, keyed by its successor.
    shown = decision._latest_strategy_signals(db, instrument.id, T)
    assert {key: signal.id for key, signal in shown.items()} == {
        "breakout_v3": v1["breakout_v1"].id,
        "pullback_v4": v1["pullback_v1"].id,
    }

    # v2 runs on T; a later v1 row of T itself (a stale writer) is not shown.
    strategies = pipeline._ensure_strategies(db)
    pipeline._upsert_signal(
        db, instrument=instrument, signal_date=T, strategies=strategies
    )
    for name in V1:
        _v1_signal(db, instrument, T, name)
    shown = decision._latest_strategy_signals(db, instrument.id, T)
    versions = {
        key: db.get(StrategyVersion, signal.strategy_version_id).name
        for key, signal in shown.items()
    }
    assert versions == {"breakout_v3": "breakout_v3", "pullback_v4": "pullback_v4"}
    assert {signal.signal_date for signal in shown.values()} == {T}
    # As of the earlier day the pages still show v1.
    shown = decision._latest_strategy_signals(db, instrument.id, earlier)
    assert {key: signal.id for key, signal in shown.items()} == {
        "breakout_v3": v1["breakout_v1"].id,
        "pullback_v4": v1["pullback_v1"].id,
    }


# ---- AC-1: collect stores the day's list ----


def test_collect_stores_the_lists_of_the_margin_reports_it_captured(
    tmp_path, monkeypatch
):
    import test_institutional_revisions as revisions
    from app.migrations import upgrade_database
    from worker import sources

    engine = create_engine(f"sqlite:///{tmp_path / 'collect.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    day = revisions.DAY

    class Feeds(revisions.Fetcher):
        """MI_MARGN as published: empty at 18:30, the full table at 21:30."""

        published = False

        def __call__(self, url, **kwargs):
            payload = super().__call__(url, **kwargs)
            if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT):
                return twse_report(day, [("1101", "")] if self.published else [])
            return payload

    try:
        first = revisions.collect_at(monkeypatch, revisions.FIRST, Feeds())
        # The empty margin table is a core warning of its own (partial).
        assert first["status"] == "partial", first
        # 18:30: no margin rows yet, so no list (the margin data stays missing).
        assert first["margin_lists"]["written"] == 0
        with factory() as db:
            assert stored_list(db, "TWSE", day) is None
        revisions.reopen(factory)
        feeds = Feeds()
        feeds.published = True
        later = revisions.collect_at(monkeypatch, revisions.LATER, feeds)
        assert later["status"] == "success", later
        assert later["margin_lists"]["written"] == 1
        with factory() as db:
            row = stored_list(db, "TWSE", day)
            capture = db.get(RawPayload, row.raw_payload_id)
            assert capture.endpoint.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT)
            assert capture.collected_at == revisions.LATER
            assert (row.data_as_of, row.members_json) == (
                day.isoformat(),
                {"1101": ""},
            )
    finally:
        engine.dispose()


def test_levels_of_a_day_with_both_versions_use_the_v2_rows(db, tmp_path, monkeypatch):
    """#407 review M2: v1 rows written first on the switch day must not feed v2."""

    from app.models import StrategyLevel
    from worker.strategy_levels import compute_strategy_levels

    monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline, "_resolve_group_member_return", lambda *_args: (0.02, {})
    )
    monkeypatch.setattr(
        pipeline,
        "_strategy_institutional_flow_to_average_volume_ratio",
        lambda *_args, **_kwargs: 0.0,
    )
    instrument = _instrument(db, "TWSE", "NOM")
    _lists(db, tmp_path, "TWSE", ["MRG"])
    old = [_v1_signal(db, instrument, T, name) for name in V1]
    pipeline._upsert_signal(
        db,
        instrument=instrument,
        signal_date=T,
        strategies=pipeline._ensure_strategies(db),
    )
    db.flush()

    compute_strategy_levels(db, T)
    db.flush()

    levels_of = {
        name: db.scalar(
            select(StrategyLevel)
            .join(Signal, Signal.id == StrategyLevel.signal_id)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(StrategyVersion.name == name)
        )
        for name in [*REGISTRY, *V1]
    }
    # The superseded rows of a day the registered strategies have are skipped.
    assert [levels_of[name] for name in V1] == [None, None]
    assert all(signal.id for signal in old)
    for name in REGISTRY:
        row = levels_of[name]
        margin = next(
            item for item in row.conditions_json if item["code"] == "margin_financing"
        )
        assert margin.get("satisfied") is None, (name, margin)
        assert margin.get("reasons") == [NOT_APPLICABLE_REASON], (name, margin)
        assert "margin_balance_change_ratio_5d_missing_or_non_finite" not in (
            row.missing_inputs_json or []
        ), (name, row.missing_inputs_json)


# ---- #407 review M1: the readable-signal check uses an instrument-day index ----


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_instrument_day_index_of_signals(
    tmp_path, monkeypatch, entry
):
    import sqlite3
    from contextlib import closing

    from app import migrations

    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    try:
        migrations.upgrade_database(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        columns = [
            row[2]
            for row in connection.execute(
                "PRAGMA index_info('ix_signals_instrument_date')"
            )
        ]
    assert columns == ["instrument_id", "signal_date"]


def test_the_readable_signal_check_uses_the_instrument_day_index(db):
    from sqlalchemy.dialects import sqlite

    from app.signal_versions import readable_signal

    query = (
        select(Signal.id)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .where(Signal.instrument_id == 1, readable_signal())
    )
    compiled = query.compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    )
    plan = " | ".join(
        str(row[-1])
        for row in db.connection().exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}")
    )
    # The correlated lookup of the same instrument-day is an index search on
    # both columns, not a scan of the instrument's whole history.
    assert "ix_signals_instrument_date (instrument_id=? AND signal_date=?)" in plan, (
        plan
    )


# ---- #407 review suggestions 1～3 ----


def test_a_list_much_shorter_than_the_previous_one_is_not_written(db, tmp_path):
    """A truncated report must not turn the missing codes into 不適用."""

    day1, day2, day3 = SESSIONS[-3:]
    codes = [f"{n:04d}" for n in range(1000, 1100)]  # 100 securities
    store_raw(db, tmp_path, "TWSE", day1, twse_report(day1, [(c, "") for c in codes]))
    store_raw(
        db, tmp_path, "TWSE", day2, twse_report(day2, [(c, "") for c in codes[:94]])
    )
    store_raw(
        db, tmp_path, "TWSE", day3, twse_report(day3, [(c, "") for c in codes[:95]])
    )

    result = margin_lists.sync_margin_lists(db, [day1, day2, day3])

    assert result["status"] == "partial"
    assert result["suspicious_drop"] == 1
    assert result["suspicious_drop_samples"] == [f"TWSE:{day2.isoformat()}"]
    assert stored_list(db, "TWSE", day2) is None
    # 5% shorter is still within the guard; it compares with the last stored list.
    assert stored_list(db, "TWSE", day3).member_count == 95


def test_the_state_of_a_day_whose_list_was_not_written_is_missing(db):
    # The day without a list (suspicious or absent) is unknown, never 不適用.
    assert margin_financing_state("1099", None, [{"1099"}] * 5 + [None]) == MISSING


@pytest.mark.parametrize("damage", ["deleted", "not_json"])
def test_an_unreadable_raw_file_fails_the_sync_at_its_date(db, tmp_path, damage):
    day1, day2 = SESSIONS[-2:]
    store_raw(db, tmp_path, "TWSE", day1, twse_report(day1, [("2330", "")]))
    raw = store_raw(db, tmp_path, "TWSE", day2, twse_report(day2, [("2330", "")]))
    path = Path(raw.payload_path)
    if damage == "deleted":
        path.unlink()
    else:
        content = b"\xff not json"
        path.write_bytes(content)
        raw.sha256 = hashlib.sha256(content).hexdigest()
        db.flush()

    result = margin_lists.sync_margin_lists(db, [day1, day2], commit_each=True)

    assert (result["status"], result["failed_date"]) == ("failed", day2.isoformat())
    assert f"raw payload {raw.id}" in result["error"]
    # The earlier session was committed; the failed one wrote nothing.
    assert stored_list(db, "TWSE", day1) is not None
    assert stored_list(db, "TWSE", day2) is None


def test_every_analyze_starts_with_an_empty_list_cache(db):
    pipeline._MARGIN_LIST_CACHE[("TWSE", T)] = (1, 1, frozenset({"2330"}))

    assert pipeline._analyze_session(db)["status"] == "no_data"

    assert pipeline._MARGIN_LIST_CACHE == {}
