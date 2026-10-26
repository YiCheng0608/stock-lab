"""Condition copy has one source (#277-B AC-B3, as #272 AC-A1 does for names).

The strategies declare their conditions (``Strategy.conditions``) and each
condition's short name (``Strategy.short_label``); the frontend words them in
one table, ``CONDITIONS`` of ``frontend/src/stock/strategyBoard.ts``.  The
action list's short names and 「差：…」 lines read those two, so no other
module may hold a list of condition codes.  This file checks the backend and
that the frontend table has the registry's codes; the frontend test
copy.test.tsx scans the frontend sources.  It reads only the table file,
which tools/ci/checks.py routes to the backend job (BACKEND_READ_FILES).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.strategies import REGISTRY
from app.strategies import levels as level_rules

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND_SRC = BACKEND.parent / "frontend" / "src"
CONDITION_TABLE = "stock/strategyBoard.ts"

# Codes that are also the name of something else, so a literal of them is no
# sign of a condition list; every other code is.
SHARED_NAMES = {
    "institutional_flow": "a hot_group_v1 component, a chip summary key, a glossary term",
    "breakout_price": "a signals column and its level field",
    "eligibility": "a condition kind (Condition.kind) as well as a code",
}


def condition_codes() -> set[str]:
    return {
        code
        for strategy in REGISTRY.values()
        for code in level_rules.condition_defaults(strategy)
    }


def backend_literals(codes: set[str], root: Path = BACKEND) -> list[tuple[str, int]]:
    """(module, line) of string constants equal to a code, outside the strategies."""

    found = []
    for path in sorted((root / "app").rglob("*.py")) + sorted(
        (root / "worker").rglob("*.py")
    ):
        if root / "app" / "strategies" in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += [
            (path.relative_to(root).as_posix(), node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value in codes
        ]
    return found


def frontend_table_codes(root: Path = FRONTEND_SRC) -> set[str]:
    """The keys of ``CONDITIONS`` in the frontend condition table."""

    source = (root / CONDITION_TABLE).read_text(encoding="utf-8")
    body = source.split("const CONDITIONS: Record<string, ConditionCopy> = {", 1)[1]
    body = body.split("\n}\n", 1)[0]
    return set(re.findall(r"^  (\w+):", body, re.MULTILINE))


def test_every_condition_has_a_short_label():
    for strategy in REGISTRY.values():
        for code in level_rules.condition_defaults(strategy):
            assert strategy.short_label(code), (strategy.key, code)
        # A short name of a code the strategy does not have is a second list.
        assert set(strategy.condition_short_labels_zh) <= set(
            level_rules.condition_defaults(strategy)
        )


def test_the_frontend_condition_table_is_the_registrys_conditions():
    assert frontend_table_codes() == condition_codes()


def test_condition_codes_are_listed_only_in_the_strategies_and_the_table():
    codes = condition_codes()
    assert set(SHARED_NAMES) <= codes
    own = codes - set(SHARED_NAMES)
    assert backend_literals(own) == []
    # The frontend half (only stock/strategyBoard.ts lists codes) is copy.test.tsx.


def test_the_scans_find_a_second_condition_list(tmp_path):
    (tmp_path / "app" / "strategies").mkdir(parents=True)
    (tmp_path / "worker").mkdir()
    (tmp_path / "app" / "strategies" / "probe.py").write_text(
        'CODES = ["probe_zone"]\n', encoding="utf-8"
    )
    (tmp_path / "app" / "copy.py").write_text(
        'SHORT = {"probe_zone": "支撐區"}\n', encoding="utf-8"
    )
    (tmp_path / "worker" / "job.py").write_text("X = 1\n", encoding="utf-8")
    assert backend_literals({"probe_zone"}, tmp_path) == [("app/copy.py", 1)]
