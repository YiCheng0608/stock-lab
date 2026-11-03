"""Issue #404: a margin balance of 0 five sessions ago is judged, not missing.

The five-day margin change ratio has no denominator when the balance five
sessions ago was 0.  From breakout_v3／pullback_v3 on, 0 then 0 is no change
(the margin condition holds) and 0 then more than 0 is
``margin_financing_increase_abnormal``; a window with missing data stays
``data_incomplete``.  The v2 rows are not rewritten and the pages read one
version per instrument-day: the newest one that day has.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app import decision
from app.domain import RuleEvaluation
from app.margin_lists import APPLICABLE, MISSING
from app.models import ChipSnapshot, Instrument, Signal, StrategyLevel, StrategyVersion
from app.strategies import (
    REGISTRY,
    SUPERSEDED,
    StrategyInputs,
    canonical_config_snapshot,
    levels,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, enable_sqlite_foreign_keys
from test_margin_not_applicable import SESSIONS, T, _instrument, _lists
from worker import pipeline

MISSING_REASON = "margin_balance_change_ratio_5d_missing_or_non_finite"
ABNORMAL = "margin_financing_increase_abnormal"
WINDOW = SESSIONS[-6:]


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


def _balances(db, instrument: Instrument, values: dict[date, int | None]) -> None:
    for day, balance in values.items():
        db.add(
            ChipSnapshot(
                instrument_id=instrument.id,
                trading_date=day,
                margin_balance=balance,
                margin_change=0 if balance is not None else None,
                source="twse_margin",
                data_as_of=datetime(day.year, day.month, day.day),
            )
        )
    db.flush()


def _window(*balances: int | None) -> dict[date, int | None]:
    assert len(balances) == 6
    return dict(zip(WINDOW, balances))


@pytest.fixture
def analyzed(db, tmp_path, monkeypatch):
    """T analyzed for margin securities whose window starts at 100 or at 0."""

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
    windows = {
        # 100 throughout: the ratio is 0, as before.
        "MRG": _window(100, 100, 100, 100, 100, 100),
        # 0 throughout (0057, 006204 on 10/30).
        "ZER": _window(0, 0, 0, 0, 0, 0),
        # 0 five sessions ago, 2 lots on T (0051 on 10/30).
        "INC": _window(0, 0, 0, 0, 1000, 2000),
        # 0 at both ends; a middle session's row has no margin value (a row of
        # the institutional group only, #395).
        "MID": _window(0, 0, None, 0, 0, 0),
        # 0 at both ends; the balance rose in between and went back to 0.
        "BUM": _window(0, 0, 500, 1000, 0, 0),
        # 0 five sessions ago, no chip row on one session of the window.
        "HOL": {day: 0 for day in WINDOW if day != WINDOW[2]},
        # 0 five sessions ago, no margin value on T.
        "NUL": _window(0, 0, 0, 0, 0, None),
    }
    instruments = {}
    for symbol, balances in windows.items():
        instruments[symbol] = _instrument(db, "TWSE", symbol)
        _balances(db, instruments[symbol], balances)
    _lists(db, tmp_path, "TWSE", list(windows))
    strategies = pipeline._ensure_strategies(db)
    for instrument in instruments.values():
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


def _judgement(signal: Signal, name: str) -> dict[str, Any]:
    stored = signal.rule_evidence_json[REGISTRY[name].kind]
    return {"state": stored["state"], "reasons": list(stored["reasons"])}


# ---- AC-1: the rule ----


def test_six_sessions_at_zero_are_no_change_and_the_condition_holds(analyzed):
    for name in REGISTRY:
        signal = analyzed[("ZER", name)]
        judgement = _judgement(signal, name)
        assert judgement["state"] in {"passed", "rejected"}, (name, signal.rationale)
        assert MISSING_REASON not in judgement["reasons"], (name, judgement)
        assert ABNORMAL not in judgement["reasons"], (name, judgement)
        assert signal.data_quality == analyzed[("MRG", name)].data_quality
        # Judged exactly as a balance that stayed at 100 (a change of 0).
        assert (signal.status, judgement) == (
            analyzed[("MRG", name)].status,
            _judgement(analyzed[("MRG", name)], name),
        ), name
        inputs = signal.rule_evidence_json["inputs"]
        # The ratio itself stays undefined; the state says why it is judged.
        assert inputs["margin_balance_change_ratio_5d"] is None
        assert inputs["margin_zero_base"] == "zero_base_unchanged"
        # app.margin_lists is unchanged (#392): applicable means a finite
        # ratio, so a listed security without one stays ``missing`` there.
        assert inputs["margin_eligibility"] == MISSING


def test_an_increase_from_zero_is_an_abnormal_increase(analyzed):
    for name, strategy in REGISTRY.items():
        signal = analyzed[("INC", name)]
        judgement = _judgement(signal, name)
        assert judgement["state"] == "rejected", (name, judgement)
        assert MISSING_REASON not in judgement["reasons"]
        # The other conditions read as for MRG; margin adds its own reason,
        # as a ratio above the maximum does.
        unchanged = _judgement(analyzed[("MRG", name)], name)
        assert judgement["reasons"] == [*unchanged["reasons"], ABNORMAL], name
        assert signal.rule_evidence_json["inputs"]["margin_zero_base"] == (
            "zero_base_increased"
        )
        above = strategy.evaluate(_inputs(margin_change_ratio_5d=0.06))
        assert list(above.reasons) == judgement["reasons"], name


@pytest.mark.parametrize("symbol", ["MID", "BUM"])
def test_only_the_two_ends_of_the_window_are_read(analyzed, symbol):
    """As the ratio: the middle sessions need a chip row, not a balance (#432 review)."""

    for name in REGISTRY:
        signal = analyzed[(symbol, name)]
        assert signal.rule_evidence_json["inputs"]["margin_zero_base"] == (
            "zero_base_unchanged"
        )
        assert (signal.status, _judgement(signal, name)) == (
            analyzed[("MRG", name)].status,
            _judgement(analyzed[("MRG", name)], name),
        ), name


@pytest.mark.parametrize("symbol", ["HOL", "NUL"])
def test_a_window_with_missing_data_stays_data_incomplete(analyzed, symbol):
    for name in REGISTRY:
        signal = analyzed[(symbol, name)]
        assert signal.status == "data_incomplete", (name, signal.rationale)
        assert _judgement(signal, name) == {
            "state": "data_incomplete",
            "reasons": [MISSING_REASON],
        }
        assert signal.rule_evidence_json["inputs"]["margin_zero_base"] is None


def _inputs(**changes: Any) -> StrategyInputs:
    values: dict[str, Any] = dict(
        bar_count=60,
        close=101.0,
        volume=2000.0,
        ma20=100.0,
        ma60=90.0,
        atr14=2.0,
        prior_highs=[100.0] * 20,
        prior_volumes=[1000] * 20,
        group_excess_return_20d=0.02,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=None,
        margin_financing=APPLICABLE,
    )
    values.update(changes)
    return StrategyInputs(**values)


def test_the_condition_list_and_levels_read_the_zero_base():
    for state, satisfied, actual in (
        ("zero_base_unchanged", True, 0.0),
        ("zero_base_increased", False, None),
    ):
        inputs = _inputs(margin_zero_base=state)
        for strategy in REGISTRY.values():
            evaluation = strategy.evaluate(inputs)
            assert evaluation.state != "data_incomplete"
            margin = next(
                item
                for item in strategy.conditions(
                    inputs, evaluation, levels.ObservationLevels("levels")
                )
                if item.code == "margin_financing"
            )
            assert (margin.satisfied, margin.actual, margin.reasons) == (
                satisfied,
                actual,
                (),
            ), (strategy.key, state)
        # The next session's levels do not wait for a ratio either.
        assert MISSING_REASON not in levels.missing_confirmations(
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
                margin_financing=APPLICABLE,
                margin_zero_base=state,
            )
        )


def test_the_margin_ablation_never_adds_the_margin_reason():
    from app.strategies.ablation import ablated_strategy

    inputs = _inputs(margin_zero_base="zero_base_increased")
    for key in REGISTRY:
        ablated = ablated_strategy(key, "margin")
        assert ABNORMAL not in ablated.evaluate(inputs).reasons, key
        other = ablated_strategy(key, "group")
        assert ABNORMAL in other.evaluate(inputs).reasons, key


def test_a_zero_base_never_turns_a_rule_without_data_into_a_rejection():
    inputs = _inputs(margin_zero_base="zero_base_increased", close=None)
    for strategy in REGISTRY.values():
        evaluation = strategy.evaluate(inputs)
        assert evaluation.state == "data_incomplete"
        assert ABNORMAL not in evaluation.reasons


def test_the_decision_does_not_list_a_zero_base_as_missing(db, analyzed):
    for symbol in ("ZER", "INC"):
        for name in REGISTRY:
            result = decision._strategy_result(
                analyzed[(symbol, name)],
                name,
                T,
                strategy_version=db.scalar(
                    select(StrategyVersion).where(StrategyVersion.name == name)
                ),
            )
            assert "margin_balance_change_ratio_5d" not in result["missing"]
    # A window with missing data still lists it.
    name = next(iter(REGISTRY))
    result = decision._strategy_result(
        analyzed[("HOL", name)],
        name,
        T,
        strategy_version=db.scalar(
            select(StrategyVersion).where(StrategyVersion.name == name)
        ),
    )
    assert "margin_balance_change_ratio_5d" in result["missing"]


def test_the_ratio_other_readers_use_is_not_redefined(db, analyzed):
    """hot_group_v1 and the candidate score read the ratio itself (not in #404)."""

    for symbol in ("ZER", "INC"):
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
        assert pipeline._margin_change_ratio(db, instrument.id, T) is None


# ---- AC-2: the stored versions ----


def _old_signal(db, instrument: Instrument, day: date, name: str) -> Signal:
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
        rationale=f"{name} fixture",
        rule_evidence_json={
            "strategy": name,
            "inputs": {"margin_balance_change_ratio_5d": None},
        },
    )
    db.add(signal)
    db.flush()
    return signal


V1 = ("breakout_v1", "pullback_v1")
V2 = ("breakout_v2", "pullback_v2")


def _row(signal: Signal) -> dict[str, Any]:
    return {
        column.name: getattr(signal, column.name) for column in Signal.__table__.columns
    }


def _zero_base_security(db, tmp_path, monkeypatch) -> Instrument:
    monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args: None)
    monkeypatch.setattr(
        pipeline, "_resolve_group_member_return", lambda *_args: (0.02, {})
    )
    monkeypatch.setattr(
        pipeline,
        "_strategy_institutional_flow_to_average_volume_ratio",
        lambda *_args, **_kwargs: 0.0,
    )
    instrument = _instrument(db, "TWSE", "ZER")
    _balances(db, instrument, _window(0, 0, 0, 0, 0, 0))
    _lists(db, tmp_path, "TWSE", ["ZER"])
    return instrument


def test_the_registry_is_v3_and_the_older_versions_are_superseded():
    assert list(REGISTRY) == ["breakout_v3", "pullback_v3"]
    assert set(SUPERSEDED) == {*V1, *V2}
    assert {
        key: strategy.config["supersedes"] for key, strategy in REGISTRY.items()
    } == {
        "breakout_v3": {"name": "breakout_v2", "version": "2.0.0"},
        "pullback_v3": {"name": "pullback_v2", "version": "2.0.0"},
    }
    # Only the margin zero-base rule and the identity differ from v2.
    for key, strategy in REGISTRY.items():
        old = dict(SUPERSEDED[strategy.config["supersedes"]["name"]].config)
        new = dict(strategy.config)
        policy = dict(new["data_policy"])
        assert policy.pop("margin_zero_base")
        assert policy == old["data_policy"], key
        for field in ("name", "version", "supersedes", "data_policy"):
            old.pop(field)
            new.pop(field)
        assert new == old, key


def test_analyze_writes_only_v3_and_leaves_the_v2_rows_alone(db, tmp_path, monkeypatch):
    instrument = _zero_base_security(db, tmp_path, monkeypatch)
    old = {
        (day, name): _old_signal(db, instrument, day, name)
        for day in (SESSIONS[-2], T)
        for name in V2
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
    assert sorted(names) == sorted([*REGISTRY, *V2])


def _shown(db, instrument: Instrument, as_of: date) -> dict[str, tuple[date, str]]:
    return {
        key: (
            signal.signal_date,
            db.get(StrategyVersion, signal.strategy_version_id).name,
        )
        for key, signal in decision._latest_strategy_signals(
            db, instrument.id, as_of
        ).items()
    }


def test_the_pages_read_the_newest_version_of_each_day(db, tmp_path, monkeypatch):
    instrument = _zero_base_security(db, tmp_path, monkeypatch)
    v1_day, v2_day = SESSIONS[-3], SESSIONS[-2]
    for name in V1:
        _old_signal(db, instrument, v1_day, name)
        # The day #392 switched: v1 written first, then v2.
        _old_signal(db, instrument, v2_day, name)
    for name in V2:
        _old_signal(db, instrument, v2_day, name)
    keys = {"breakout_v3", "pullback_v3"}

    assert _shown(db, instrument, v1_day) == {
        key: (v1_day, name) for key, name in zip(sorted(keys), V1)
    }
    # v1 and v2 on one day: only v2, never both (#404 adds a version to the chain).
    assert _shown(db, instrument, v2_day) == {
        key: (v2_day, name) for key, name in zip(sorted(keys), V2)
    }

    # v3 runs on T; a later v2 row of T itself (a stale writer) is not shown.
    pipeline._upsert_signal(
        db,
        instrument=instrument,
        signal_date=T,
        strategies=pipeline._ensure_strategies(db),
    )
    for name in (*V1, *V2):
        _old_signal(db, instrument, T, name)
    assert _shown(db, instrument, T) == {key: (T, key) for key in keys}
    # As of the earlier days the pages still show their versions.
    assert {name for _day, name in _shown(db, instrument, v2_day).values()} == set(V2)
    assert {name for _day, name in _shown(db, instrument, v1_day).values()} == set(V1)


def test_the_strategy_board_reads_one_version_per_day(db, tmp_path, monkeypatch):
    from app.strategy_board import strategy_board

    instrument = _zero_base_security(db, tmp_path, monkeypatch)
    v2_day = SESSIONS[-2]
    for name in (*V1, *V2):
        _old_signal(db, instrument, v2_day, name)
    pipeline._upsert_signal(
        db,
        instrument=instrument,
        signal_date=T,
        strategies=pipeline._ensure_strategies(db),
    )
    db.flush()

    def versions(day: date) -> list[str | None]:
        board = strategy_board(db, instrument, day, None)
        assert board["as_of"] == day.isoformat()
        return [row.get("strategy") for row in board["strategies"]]

    assert versions(v2_day) == list(V2)
    assert versions(T) == list(REGISTRY)


def test_levels_of_a_day_with_v2_and_v3_use_the_v3_rows(db, tmp_path, monkeypatch):
    from worker.strategy_levels import compute_strategy_levels

    instrument = _zero_base_security(db, tmp_path, monkeypatch)
    for name in (*V1, *V2):
        _old_signal(db, instrument, T, name)
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
        for name in [*REGISTRY, *V1, *V2]
    }
    assert [levels_of[name] for name in (*V1, *V2)] == [None] * 4
    for name in REGISTRY:
        row = levels_of[name]
        margin = next(
            item for item in row.conditions_json if item["code"] == "margin_financing"
        )
        assert margin.get("satisfied") is True, (name, margin)
        assert margin.get("actual") == 0.0, (name, margin)
        assert MISSING_REASON not in (row.missing_inputs_json or []), name


def test_a_rule_evaluation_is_rejected_with_the_reasons_in_order():
    """The margin reason comes last, where the margin comparison puts it."""

    from app.strategies.breakout_v3 import judge_zero_base

    seen: dict[str, Any] = {}

    def evaluate(**arguments: Any) -> RuleEvaluation:
        seen.update(arguments)
        return RuleEvaluation(False, "rejected", ("volume_ratio_below_1_20",))

    config = REGISTRY["breakout_v3"].config
    result = judge_zero_base(
        evaluate,
        margin_balance_change_ratio_5d=None,
        margin_financing=APPLICABLE,
        margin_zero_base="zero_base_increased",
        config=config,
    )
    assert result == RuleEvaluation(
        False, "rejected", ("volume_ratio_below_1_20", ABNORMAL)
    )
    assert "margin_financing" not in seen["config"]["confirmations"]
    assert seen["margin_balance_change_ratio_5d"] == 0.0
