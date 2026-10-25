"""The strategy registry is the one declaration of the rule strategies (#272).

Every other non-test module under ``backend/app`` and ``backend/worker``
reads REGISTRY instead of naming a strategy, and a strategy added to the
registry gets its own ``signals`` rows from analyze with no other change.
"""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import strategies
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import RuleEvaluation
from app.models import IngestionRun, Instrument, MarketBar, Signal, StrategyVersion
from app.strategies import REGISTRY, SignalLevels, Strategy, StrategyInputs
from worker import pipeline

BACKEND = Path(__file__).resolve().parents[1]

# (module, top-level name) -> why a strategy name may stay a literal there.
ALLOWED_NAME_LITERALS = {
    ("app/domain.py", "LEGACY_SIGNAL_CONFIDENCE_STRATEGIES"): (
        "historical rows: only these strategies at 1.0.0 stored the fixed 0.75 "
        "confidence; a new strategy must never be read as legacy"
    ),
    ("app/domain.py", "CANDIDATE_SCORE_V1"): (
        "versioned candidate_score snapshot: its pool and per-strategy items are "
        "persisted with every candidate run, and a new strategy enters the pool "
        "only with a new score version"
    ),
    ("app/glossary.py", "_TERMS"): (
        "glossary search aliases (product vocabulary, not a strategy branch)"
    ),
    ("app/migrations.py", "_PRE_V2_CANONICAL_DIGESTS"): (
        "historical rows: closed digest list of the snapshots shipped before the "
        "0009 formula migration"
    ),
}


def _top_level_name(statement: ast.stmt) -> str:
    if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id
    return getattr(statement, "name", type(statement).__name__)


def _name_literals(
    names: set[str], root: Path = BACKEND
) -> list[tuple[str, str, int, str]]:
    """String constants (docstrings and f-string parts too) naming a strategy."""

    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names))) + r")\b")
    found = []
    for path in sorted((root / "app").rglob("*.py")) + sorted(
        (root / "worker").rglob("*.py")
    ):
        if root / "app" / "strategies" in path.parents:
            continue
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for statement in tree.body:
            owner = _top_level_name(statement)
            for node in ast.walk(statement):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and pattern.search(node.value)
                ):
                    found.append((module, owner, node.lineno, node.value[:60]))
    return found


def test_strategy_names_are_declared_only_in_the_registry():
    names = set(REGISTRY)
    assert names == {"breakout_v1", "pullback_v1"}
    found = _name_literals(names)
    outside = [item for item in found if item[:2] not in ALLOWED_NAME_LITERALS]
    assert outside == []
    # Every allowance is still needed; a stale one would hide a new literal.
    assert {item[:2] for item in found} == set(ALLOWED_NAME_LITERALS)


def test_the_scan_finds_a_strategy_name_outside_the_registry(tmp_path):
    (tmp_path / "app" / "strategies").mkdir(parents=True)
    (tmp_path / "worker").mkdir()
    (tmp_path / "app" / "strategies" / "probe_v1.py").write_text(
        'CONFIG = {"name": "probe_v1"}\n', encoding="utf-8"
    )
    (tmp_path / "app" / "probe.py").write_text(
        'def pick(name):\n    return name == "probe_v1"\n', encoding="utf-8"
    )
    (tmp_path / "worker" / "job.py").write_text(
        'NAMES = {f"probe_v1-{1}"}\n', encoding="utf-8"
    )
    assert _name_literals({"probe_v1"}, tmp_path) == [
        ("app/probe.py", "pick", 2, "probe_v1"),
        ("worker/job.py", "NAMES", 1, "probe_v1-"),
    ]


FAKE_CONFIG: dict[str, Any] = {
    "name": "fake_test_v1",
    "version": "0.0.1",
    "schema_version": "strategy-config/v1",
    "kind": "fake_test",
}


def _always_pass(**_arguments: Any) -> RuleEvaluation:
    return RuleEvaluation(True, "passed")


class FakeStrategy(Strategy):
    config = FAKE_CONFIG
    rule = staticmethod(_always_pass)
    entry_type = "breakout"
    label_zh = "測試條件"
    research_label_zh = "測試研究條件"
    requires_zh = ("收盤價",)

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return {"close": inputs.close}

    def actionable_levels(self, inputs: StrategyInputs) -> SignalLevels:
        entry, invalid, target_1, target_2 = strategies.risk_levels(
            inputs.close, inputs.atr14
        )
        return SignalLevels(
            breakout_price=entry,
            invalid_price=invalid,
            target_1=target_1,
            target_2=target_2,
        )


def test_a_strategy_added_to_the_registry_gets_signal_rows_from_analyze(
    monkeypatch,
):
    monkeypatch.setitem(REGISTRY, FAKE_CONFIG["name"], FakeStrategy())
    score_date = date(2026, 9, 4)
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as db:
            db.add(
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=score_date,
                    status="success",
                    data_as_of=score_date.isoformat(),
                )
            )
            instrument = Instrument(
                market="TW",
                exchange="TWSE",
                symbol="FAKE",
                name="Fake",
                instrument_type="stock",
                status="active",
            )
            db.add(instrument)
            db.flush()
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=score_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=2000,
                    turnover=200000,
                    source="fixture",
                )
            )
            db.flush()

            result = pipeline._analyze_session(db)
            db.flush()

            assert result["status"] == "success"
            rows = db.execute(
                select(Signal, StrategyVersion.name)
                .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
                .where(Signal.instrument_id == instrument.id)
            ).all()
            by_name = {name: signal for signal, name in rows}
            assert set(by_name) == set(REGISTRY)
            fake = by_name[FAKE_CONFIG["name"]]
            assert fake.signal_key == (
                f"analysis-TWSE-FAKE-{score_date.isoformat()}-fake_test_v1-0.0.1"
            )
            assert fake.entry_type == "breakout"
            assert fake.rule_evidence_json["strategy"] == "fake_test_v1"
            assert fake.rule_evidence_json["fake_test"] == {
                "state": "passed",
                "reasons": [],
            }
            # The fixture has no group score, so the passed rule is held back
            # exactly like a registered strategy's would be.
            assert fake.status == "data_incomplete"
            # Every row records every registered strategy's state.
            assert all(
                "fake_test=passed:" in (signal.rationale or "")
                for signal in by_name.values()
            )
            version = db.scalar(
                select(StrategyVersion).where(
                    StrategyVersion.name == FAKE_CONFIG["name"]
                )
            )
            assert version.kind == "fake_test"
            assert version.canonical_config_snapshot == FAKE_CONFIG
    finally:
        engine.dispose()


def test_registry_declaration_order_is_breakout_then_pullback():
    assert [strategy.entry_type for strategy in REGISTRY.values()] == [
        "breakout",
        "pullback",
    ]
    for key, strategy in REGISTRY.items():
        assert strategy.key == key == strategy.config["name"]
        assert strategy.kind == strategy.config["kind"]
