"""Every module constant a research tool's verdicts read is in its definitions hash (#945).

A research tool's ``definitions_sha256()`` is what keeps a validation from
running on numbers other than the ones the exploration was judged by
(docs/spec/evidence.md「第 2 步的工具」).  Three times a number the tool reads
was left out of it and only a review caught it: ``round5_research``'s momentum
window written as the literal 20 (PR #890), ``round9_research``'s ``MARKETS``
and ``NO_STOP`` (PR #930), ``round10_research``'s ``NEAR`` (PR #939).

The check is static (``ast``, nothing imported, no DB):

* the tools are every ``tools/research/*_research.py`` with a top-level
  ``definitions_sha256``, so a new tool is covered without a new test;
* a constant is a module-level ``NAME = ...`` with an upper-case name, the
  tool's own or another research module's read as ``alias.NAME``;
* covered: what ``definitions_sha256``, ``definitions`` and the tool's
  functions they call read, and what those constants are built from;
* read: what every other function or class of the tool reads.  A constant
  read and not covered passes when it is built from constants only (no
  literal, e.g. ``MOMENTUM_20 = features._momentum(MOMENTUM_WINDOW)``) that
  pass in turn, or when :data:`EXEMPT` lists it with the reason it cannot
  change a verdict.

Not seen: constants read through ``getattr``／``globals()``, a literal number
written in a function body, and the constants another module's function
reads when the tool calls it (``r5.cash_yield_parts`` reads round5's own
constants; tools name such a module's ``VERSION``／``DESIGN`` in their
definitions instead).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1].parent
RESEARCH = ROOT / "tools" / "research"
CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*$")
HASH_FUNCTIONS = ("definitions_sha256", "definitions")

# Report text, labels, file names and links: read by the tool, never by a
# verdict.  By name, for every research module's constant of that name.
REPORT_ONLY = {
    "DECISION": "link to the decision comment, written in the report",
    "REGISTRATION_COMMIT": "commit of the registration, written in the report",
    "CORRECTION_COMMIT": "commit of the correction, written in the report",
    "TOOL": "the tool's name, written in the report and the marker",
    "RAW_DIR_NAME": "name of the output directory",
    "REASONS": "the report's wording of each verdict",
    "STAGES": "names of the progress lines",
    "OTHER_COMPARISONS": "report text: the comparisons not judged",
    "SEGMENT_NAMES": "the segments' names in the report",
    "LIMITS": "report text: the registration's limits",
    "DEGENERATE": "report text: when a value is missing",
    "COVERAGE_NOTES": "report text of the coverage section",
    "OVERLAP_NOTE": "report text of the overlap section",
    "MISSING_SHARE_NOTE": "report text of the coverage section",
    "NO_MARKET_NOTE": "report text of the coverage section",
    "V3_LIMIT": "report text: the registration's limit of V3",
    "FEATURE_LABELS": "the features' names in the report",
    "ABANDON_LABELS": "the report's wording of an abandoned entry",
    "FALLBACK_LABELS": "the report's wording of a fallback",
    "FALLBACK_REASONS": "the report's wording of a fallback",
    "MARGIN_LABELS": "the report's wording of the margin cases",
    "SOURCE_LABELS": "the report's wording of the stop sources",
    "EXIT_LABELS": "the report's wording of an exit",
    "TRADE_FIELDS": "columns of the trades CSV",
    "PICK_FIELDS": "columns of the picks CSV",
    "PICK_EXTRAS": "extra columns of the picks CSV",
    "EVENT_FIELDS": "columns of the events CSV",
    "EVENT_TRADE_FIELDS": "columns of the event trades CSV",
    "EVENT_TRADE_TAIL": "columns of the event trades CSV",
    "PORTFOLIO_TRADE_FIELDS": "columns of the portfolio trades CSV",
    "GROUP_FIELDS": "columns of the groups CSV",
    "COVERAGE_KEYS": "keys of the coverage counters",
    "C1_KEYS": "keys of the coverage counters",
    "POPULATION": "the population curve's key in the result rows",
    "TAIEX": "the TAIEX curve's key in the result rows",
}

# By qualified name: "<module>.<NAME>" -> why it cannot change a verdict, or
# the question it is waiting on.
EXEMPT = {
    # explore_research: shared by the rounds (read as ``ex.NAME``)
    "explore_research.PASSED": "a verdict's label, the result and not an input",
    "explore_research.UNDECIDED": "a verdict's label, the result and not an input",
    "explore_research.REVERSED": "a verdict's label, the result and not an input",
    "explore_research.FORWARD_WATCH": "a verdict's label, the result and not an input",
    "explore_research.EXPLORATION_PASSED": "a verdict's label",
    "explore_research.EXPLORATION_FAILED": "a verdict's label",
    "explore_research.VALIDATION_FAILED": "a verdict's label",
    "explore_research.DESIGN": "written in the report; the hash has VERSION and the definitions",
    "explore_research.MARKER_NAME": "file name of the research DB marker",
    "explore_research.MARKER_PURPOSE": "the research DB marker's purpose string, checked on load",
    "explore_research.LEDGER_NAME": "file name of the ledger",
    "explore_research.REPO_LEDGER": "path of the ledger",
    "explore_research.ROOT": "path of the repo",
    "explore_research.URL_PATTERNS": "format of a decision link",
    "explore_research.FEATURES": "table of functions; each feature's definition is in HYPOTHESES",
    "explore_research.FEATURE_FUNCTIONS": "table of feature_evidence's functions by key",
    "explore_research.HYPOTHESES": "round10 reads X2's to list the overlap only (report)",
    "explore_research.LOAD_FROM": (
        "the first day read; explore_research, mainstream_research and round5_research "
        "have run all their hypotheses and do not run this version again; "
        "changing it takes a new issue and a new VERSION (#945 decision 7073010102)"
    ),
    "explore_research.WARMUP_CALENDAR_DAYS": (
        "the warm-up before a later segment; explore_research has run all its "
        "hypotheses and does not run this version again; "
        "changing it takes a new issue and a new VERSION (#945 decision 7073010102)"
    ),
    # other shared modules
    "evidence_lib.NAN": "the missing-value marker",
    "evidence_lib.CHIP_FIELDS": "the chip columns read from the copy",
    "portfolio_research.TRADING_DAYS": "annualises the report's statistics; the verdict uses t",
    "trade_research.EXIT_REASONS": "the exits' names, the result of settle",
    "trade_research.ENDED": (
        "the statuses settled as delisted; trade_research has run all its "
        "hypotheses and does not run this version again; "
        "changing it takes a new issue and a new VERSION (#945 decision 7073010102)"
    ),
    "exit_research.NOT_ACTIONABLE": (
        "the statuses that do not enter; trade_research has run all its "
        "hypotheses and does not run this version again; "
        "changing it takes a new issue and a new VERSION (#945 decision 7073010102)"
    ),
    "industry_members.GROUP_LABELS": "the groups' names; mainstream reads the members file by its sha256",
    "industry_members.ROW_FIELDS": "columns of the members file",
    "mainstream_research.MEMBERS_NAME": "file name of the members file; its sha256 is in the definitions",
    "mainstream_research.MEMBERS_LAST": "the members file's last month, written in the report",
    "mainstream_research.MEMBERS_SHA256": "the members file's sha256, checked on load",
    "mainstream_research.MEMBERS_DIR": "directory of the members file",
    # round-specific
    "round4_research.BAND": "a stop source's key",
    "round4_research.CLAMPED_HIGH": "a stop source's key",
    "round4_research.CLAMPED_LOW": "a stop source's key",
    "round4_research.FALLBACK": "a stop source's key",
    "round4_research.STOP_SOURCES": "the stop sources' keys",
    "round4_research.KEPT": "a margin case's key",
    "round4_research.OVER": "a margin case's key",
    "round4_research.MISSING": "a margin case's key",
    "round4_research.ZERO_BASE_INCREASED": "a margin case's key",
    "round4_research.EXCLUDED": "the margin cases' keys left out",
    "round4_research.SHORT": "a fallback case's key",
    "round4_research.SUSPENDED": "a fallback case's key",
    "round4_research.NO_RANGE": "a fallback case's key",
    "round4_research.NOT_APPLICABLE": "a fallback case's key",
    "round4_research.NO_CANDIDATE": "a fallback case's key",
    "round5_research.FEATURES": "table of functions; each feature's definition is in definitions()",
    "round5_research.DELISTED_STATUSES": "the coverage's count of delisted members (report)",
    "round6_research.FEATURES": "table of functions; each feature's definition is in definitions()",
    "round7_research.FEATURES": "table of functions; each feature's definition is in definitions()",
    "round7_research.MARKETS": "the coverage table's columns (report)",
    "round8_research.FEATURES": "table of functions; each feature's definition is in definitions()",
    "round9_research.TOP_X_DAYS": "the coverage's list of the days with most X (report)",
    "round10_research.X2": "the key of explore_research's X2, for the overlap only (report)",
    "round10_research.RANKERS": "table of functions by hypothesis",
    "trade_research.SCORE_FUNCTIONS": "table of functions; the scores are in HYPOTHESES",
    "trade_research.SCORE_KEYS": "the scores' keys; the scores are in HYPOTHESES",
    "trade_research.UNDECIDED": "a verdict's label",
    "trade_research.PASSED": "a verdict's label",
}


@dataclass
class Module:
    name: str
    constants: dict[str, ast.expr] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    functions: dict[str, ast.AST] = field(default_factory=dict)

    def refs(self, node: ast.AST) -> tuple[set[str], set[str]]:
        """The qualified constants ``node`` reads and the module's functions it calls."""

        names, calls = set(), set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in self.constants:
                names.add(f"{self.name}.{sub.id}")
            elif (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id in self.aliases
                and CONSTANT.match(sub.attr)
            ):
                target = module(self.aliases[sub.value.id])
                if sub.attr in target.constants:
                    names.add(f"{target.name}.{sub.attr}")
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                if sub.func.id in self.functions:
                    calls.add(sub.func.id)
        return names, calls


def _sources() -> dict[str, Path]:
    return {path.stem: path for path in sorted(RESEARCH.glob("*.py"))}


@cache
def module(name: str) -> Module:
    tree = ast.parse(_sources()[name].read_text(encoding="utf-8"))
    out = Module(name)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _sources():
                    out.aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and CONSTANT.match(target.id):
                    out.constants[target.id] = node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.functions[node.name] = node
    return out


def constant(qualified: str) -> tuple[Module, ast.expr]:
    name, _, attr = qualified.rpartition(".")
    owner = module(name)
    return owner, owner.constants[attr]


def has_literal(value: ast.expr) -> bool:
    """A literal in the value, other than a subscript's key (``SOURCE["effective"]``)."""

    keys = {id(sub.slice) for sub in ast.walk(value) if isinstance(sub, ast.Subscript)}
    return any(
        isinstance(sub, ast.Constant) and id(sub) not in keys for sub in ast.walk(value)
    )


def tools() -> list[str]:
    out = []
    for name, path in _sources().items():
        if not name.endswith("_research"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "definitions_sha256"
            for node in tree.body
        ):
            out.append(name)
    return out


def covered(tool: Module) -> tuple[set[str], set[str]]:
    """The constants the hash reads (with what they are built from) and the
    functions on its path."""

    path, todo, names = set(), [f for f in HASH_FUNCTIONS if f in tool.functions], set()
    while todo:
        name = todo.pop()
        if name in path:
            continue
        path.add(name)
        refs, calls = tool.refs(tool.functions[name])
        names |= refs
        todo += calls
    stack = list(names)
    while stack:
        owner, value = constant(stack.pop())
        for ref in owner.refs(value)[0] - names:
            names.add(ref)
            stack.append(ref)
    return names, path


def missing(name: str, exempted: set[str] | None = None) -> list[str]:
    """``<constant> (read through <constant>, ...)`` for every constant the tool
    reads outside its definitions hash."""

    tool = module(name)
    hashed, path = covered(tool)
    read = set()
    for function, node in tool.functions.items():
        if function not in path:
            read |= tool.refs(node)[0]

    out: list[str] = []

    def check(qualified: str, via: tuple[str, ...], seen: frozenset[str]) -> None:
        bare = qualified.rpartition(".")[2]
        if qualified in hashed or qualified in seen:
            return
        if qualified in EXEMPT or bare in REPORT_ONLY:
            if exempted is not None:
                exempted.add(qualified if qualified in EXEMPT else bare)
            return
        owner, value = constant(qualified)
        refs = owner.refs(value)[0]
        if not has_literal(value) and refs:
            for ref in sorted(refs):
                check(ref, via + (qualified,), seen | {qualified})
            return
        line = qualified if not via else f"{qualified} (read through {', '.join(via)})"
        out.append(line)

    for qualified in sorted(read):
        check(qualified, (), frozenset())
    return sorted(set(out))


@pytest.mark.parametrize("name", tools())
def test_every_constant_the_verdicts_read_is_in_the_definitions_hash(name):
    lines = missing(name)
    assert not lines, (
        f"tools/research/{name}.py reads module constants that are not in its "
        "definitions_sha256(): "
        + "; ".join(lines)
        + ".  Add each to definitions(), or to EXEMPT in "
        "backend/tests/test_research_definitions.py with the reason it cannot "
        "change a verdict (#945)"
    )


def test_the_tools_are_found():
    found = tools()
    for name in ("explore_research", "trade_research", "round10_research"):
        assert name in found


def test_every_exemption_is_still_needed():
    exempted: set[str] = set()
    for name in tools():
        missing(name, exempted)
    stale = sorted(set(EXEMPT) - exempted) + sorted(set(REPORT_ONLY) - exempted)
    assert not stale, (
        "backend/tests/test_research_definitions.py exempts constants no tool "
        f"reads outside its definitions hash any more: {', '.join(stale)}; delete "
        "them from EXEMPT／REPORT_ONLY (#945)"
    )


def test_every_exemption_names_a_constant():
    for qualified in EXEMPT:
        name, _, attr = qualified.rpartition(".")
        assert name in _sources(), f"EXEMPT {qualified}: no tools/research/{name}.py"
        assert attr in module(name).constants, (
            f"EXEMPT {qualified}: tools/research/{name}.py has no constant {attr}; "
            "delete the line"
        )
