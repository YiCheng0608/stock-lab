"""tools/research/research_report.py (#318): the report tables of a research run, read only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    Signal,
    SignalSettlement,
    StrategyVersion,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "research" / "research_report.py"

spec = importlib.util.spec_from_file_location("research_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report  # its dataclasses look their module up
spec.loader.exec_module(report)

COST = 0.003
BUY = 1.0005


def sessions(count: int) -> list[date]:
    days, day = [], date(2026, 1, 5)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def grown(index: int, rate: float) -> float:
    return round(100.0 * (1.0 + rate) ** index, 6)


def hold_return(rate: float, horizon: int) -> float:
    """Open of T+1 (the close of T) to the close of T+horizon, growing at ``rate``."""

    return (1.0 + rate) ** horizon / BUY - 1.0 - COST


def bar(instrument_id: int, day: date, close: float, open_: float, **extra) -> MarketBar:
    return MarketBar(
        instrument_id=instrument_id,
        trading_date=day,
        open=open_,
        high=max(open_, close),
        low=min(open_, close),
        close=close,
        adj_close=close,
        volume=extra.pop("volume", 1000),
        source="test",
        **extra,
    )


@pytest.fixture
def research_db(tmp_path) -> Path:
    """A research run of two strategies on five instruments over 30 sessions.

    A grows 1 % a session and B 2 %, with a 2:1 split on session 4 (raw prices
    halve; the action's price factor restores them).  C misses session 3,
    the IPO D is suspended on session 4, E is an ETF.  breakout_v2 has two
    comparable T+5 settlements on session 1 and one on session 2;
    breakout_v2_ablate_group three on session 1.
    """

    path = tmp_path / "copy" / "stock.db"
    path.parent.mkdir()
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = sessions(30)
    with Session(engine) as db:
        kinds = {1: "index", 2: "stock", 3: "stock", 4: "stock", 5: "ipo", 6: "etf"}
        for instrument_id, kind in kinds.items():
            symbol = "TAIEX" if kind == "index" else f"S{instrument_id}"
            db.add(
                Instrument(
                    id=instrument_id,
                    exchange="TWSE",
                    symbol=symbol,
                    name=symbol,
                    instrument_type=kind,
                    status="active" if instrument_id != 4 else "delisted",
                )
            )
        rates = {1: 0.005, 2: 0.01, 3: 0.02, 4: 0.01, 5: 0.01, 6: 0.01}
        for instrument_id, rate in rates.items():
            for index, day in enumerate(days):
                if instrument_id == 4 and index == 3:
                    continue  # C misses a market session
                close = grown(index, rate)
                open_ = grown(index - 1, rate) if index else close
                if instrument_id == 3 and index >= 4:
                    close, open_ = close / 2, open_ / 2
                db.add(
                    bar(
                        instrument_id,
                        day,
                        close,
                        open_,
                        is_suspended=instrument_id == 5 and index == 4,
                    )
                )
        db.add(
            CorporateAction(
                instrument_id=3,
                action_date=days[4],
                action_type="split",
                details_json={"price_factor": 0.5},
                source="test",
            )
        )
        run = IngestionRun(
            id=7,
            run_type="backtest",
            source="technical_backtest",
            run_date=days[-1],
            status="success",
            request_key="technical-backtest:v1:x:y:research:breakout_v2,breakout_v2_ablate_group",
        )
        db.add(run)
        db.add(IngestionRun(id=8, run_type="backtest", source="other", run_date=days[-1]))
        canonical = StrategyVersion(
            id=1, name="breakout_v2", version="2.0.0", kind="breakout", config_json={}
        )
        ablation = StrategyVersion(
            id=2,
            name="breakout_v2_ablate_group",
            version="2.0.0",
            kind="breakout_ablate_group",
            config_json={
                "ablation": {
                    "base_strategy": "breakout_v2",
                    "removed_condition": "group",
                }
            },
        )
        db.add_all([canonical, ablation])
        db.flush()
        signal_id = 0

        def signal(strategy: StrategyVersion, day_index: int, actionable: bool,
                   returns: tuple[float | None, ...] = (), reasons=(), run_id=7):
            nonlocal signal_id
            signal_id += 1
            row = Signal(
                id=signal_id,
                signal_key=f"backtest-{run_id}-TWSE-S{signal_id}-{days[day_index]}-{strategy.name}",
                signal_date=days[day_index],
                instrument_id=2,
                strategy_version_id=strategy.id,
                status="active" if actionable else "observation",
                breakout_price=100.0 if actionable else None,
                invalid_price=95.0 if actionable else None,
                target_1=108.0 if actionable else None,
                target_2=115.0 if actionable else None,
                rationale="required inputs complete",
                rule_evidence_json={
                    "actionable": actionable,
                    strategy.kind: {"state": "x", "reasons": list(reasons)},
                },
            )
            db.add(row)
            for horizon, value in zip((5, 20), returns):
                db.add(
                    SignalSettlement(
                        signal_id=signal_id,
                        horizon=horizon,
                        settlement_date=days[day_index + 1],
                        final_status="target_1_hit" if value is not None else "incomparable",
                        return_or_risk=value,
                        comparable=value is not None,
                        execution_date=days[day_index + 1] if value is not None else None,
                    )
                )

        for value in (0.04, 0.02):
            signal(canonical, 1, True, (value, None))
        signal(canonical, 2, True, (0.01, None))
        signal(canonical, 2, True, (None, None))  # never executed
        for day_index in (3, 4):
            signal(canonical, day_index, False, reasons=("volume_ratio_below_1_20",))
        signal(canonical, 4, False, reasons=("volume_ratio_below_1_20", "x_below"))
        for value in (0.03, 0.03, 0.03):
            signal(ablation, 1, True, (value, None))
        signal(ablation, 3, True, (None, None))
        signal(ablation, 4, False)
        signal(canonical, 1, True, (0.5, None), run_id=8)  # another run
        db.commit()
    engine.dispose()
    return path


def run_report(db: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--db", str(db), "--run-id", "7"]
        + ["--out", str(out), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_the_tables_of_a_run_and_benchmark_one_are_what_the_bars_give(
    research_db, tmp_path
):
    before = hashlib.sha256(research_db.read_bytes()).hexdigest()
    result = run_report(research_db, tmp_path / "out", "--draws", "5")
    assert result.returncode == 0, result.stderr
    tables = json.loads((tmp_path / "out" / "tables.json").read_text("utf-8"))
    # Read only: the copy is byte for byte what it was.
    assert hashlib.sha256(research_db.read_bytes()).hexdigest() == before

    canonical = tables["results"]["breakout_v2:T+5"]
    assert canonical["returns"]["n"] == 3
    assert canonical["returns"]["mean"] == pytest.approx((0.04 + 0.02 + 0.01) / 3)
    assert canonical["incomparable"] == {"not_executed": 1}
    # Session 1's pool is A and B (B through its split); C misses session 3,
    # the IPO D is suspended on session 4 and E is an ETF.  Two of two are
    # drawn on session 1; session 2 draws one of A and B.
    session_1 = [hold_return(0.01, 5), hold_return(0.02, 5)]
    assert canonical["benchmark"]["instruments_per_draw"] == 3
    means = [
        float(line.split(",")[2])
        for line in (tmp_path / "out" / "benchmark_means.csv").read_text().splitlines()[1:]
        if line.startswith("breakout_v2:T+5,")
    ]
    assert len(means) == 5
    for mean in means:
        assert mean == pytest.approx(
            (sum(session_1) + session_1[0]) / 3
        ) or mean == pytest.approx((sum(session_1) + session_1[1]) / 3)
    # TAIEX grows 0.5 % a session: close of the signal date to T+5's close.
    assert canonical["taiex"]["mean"] == pytest.approx(1.005**5 - 1.0)

    ablation = tables["results"]["breakout_v2_ablate_group:T+5"]
    assert ablation["benchmark"]["instruments_per_draw"] == 2  # the pool's size
    assert ablation["benchmark"]["mean_of_means"] == pytest.approx(sum(session_1) / 2)
    # Run 8's signal is not in run 7's tables.
    assert tables["signal_totals"]["breakout_v2"]["actionable"] == 4
    assert tables["signal_totals"]["breakout_v2"]["executed"] == 3
    assert tables["levels"]["breakout_v2"]["target_1_r"]["p50"] == pytest.approx(1.6)


def test_days_without_a_conditional_signal_and_what_one_removal_gives(
    research_db, tmp_path
):
    result = run_report(research_db, tmp_path / "out", "--draws", "2")
    assert result.returncode == 0, result.stderr
    zero = json.loads((tmp_path / "out" / "tables.json").read_text("utf-8"))[
        "zero_days"
    ]["breakout_v2"]
    assert zero["sessions"] == 4
    assert zero["dates"] == [d.isoformat() for d in sessions(5)[3:5]]
    # Removing the group condition gives a signal on session 3, not on 4.
    assert zero["single_removal_gives_a_signal"] == {
        "group": 1,
        "(no single removal)": 1,
    }
    assert zero["reasons_on_zero_days"] == {"volume_ratio_below_1_20": 3, "x_below": 1}
    assert zero["statuses_on_zero_days"] == {"observation": 3}
    summary = (tmp_path / "out" / "summary.md").read_text("utf-8")
    assert "`breakout_v2`：2／4 天" in summary
    assert (tmp_path / "out" / "returns.svg").read_text("utf-8").startswith("<svg")


def test_the_draws_are_seeded_and_never_repeat_an_instrument_in_a_day():
    pools = {date(2026, 1, 5): [1.0, 2.0, 3.0], date(2026, 1, 6): [10.0]}
    counts = {date(2026, 1, 5): 3, date(2026, 1, 6): 2}
    means, medians, size = report.draw_means(counts, pools, 3, random.Random(1))
    assert size == 4 and means == [4.0, 4.0, 4.0] and medians == [2.5, 2.5, 2.5]
    first = report.draw_means({date(2026, 1, 5): 1}, pools, 20, random.Random(318))
    again = report.draw_means({date(2026, 1, 5): 1}, pools, 20, random.Random(318))
    assert first == again and len(set(first[0])) > 1
    assert report.quantile([1.0, 2.0, 3.0, 4.0], 0.25) == pytest.approx(1.75)
    assert report.rank(2.0, [1.0, 2.0, 3.0, 4.0]) == 0.5


def test_the_production_database_is_refused(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    result = run_report(production, tmp_path / "out")
    assert result.returncode == 2
    assert "stock-lab-data" in json.loads(result.stdout)["refused"][0]
    assert not (tmp_path / "out").exists()
