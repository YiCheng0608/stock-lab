"""Round 3 of the new-strategy exploration: M1, M2 主流族群前 20 (#813).

docs/spec/evidence.md 第三輪：M1、M2: the hypotheses were registered (commit
``31a09e9e``, #773, decision 6894054847) and their members corrected twice
(#779, merged in ``b417f716``) before anyone ran a tool on the backfilled
history.  Nothing here is a command-line option: a change of a definition is a
new code, and the golden tests lock the engine.

Each signal date T (after its close, only T's data and before):

- the population is the common one (``evidence_lib.universe``); a member's
  240-session return is ``feature_evidence._momentum(240)`` on its own bars
  (the research basis); one without it stays in the population and cannot
  be picked.
- TAIEX's return is its close on T over the earliest of its 241 closes to T;
  without a close on T or with fewer than 241, T picks nothing (that
  account keeps its cash, the population still buys).
- the groups are T's official industry members: the latest snapshot of
  ``industry_members_v1.json`` (#779) with ``snapshot_date <= T``, each row's
  symbol matched to the instrument with a bar on T.  Both markets count; the
  47 TWSE companies of the 2023 list go back to their code before 2023-07-03
  (AC-1 decision 6913227984, ``REMAP_2023``).
- the groups are ranked and the stocks taken as ``app.mainstream``'s
  ``mainstream_v1`` does (``rank_groups``, ``rank_items``), copied here and
  not imported; backend/tests/test_mainstream_research.py compares both on
  one fixture, so a change of the product turns it red.

M1 holds 20 sessions, M2 60, in ``portfolio_research.simulate``'s K accounts
(20 names, 1/20 of the account's cash each); the benchmark is the same engine
over the day's whole population.  ``explore_research.explore_judge`` judges;
the segments, the floors, the public check, the gate (the exploration once
per version, the validation once after a published exploration report) and
the ledgers (``explore-ledger.json`` beside the DB and the repository's
``tools/research/explore_ledger.json``, each entry with ``"tool":
"mainstream_research"``) are ``explore_research``'s.  ``--coverage-only``
writes the yearly member coverage and no return at all.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import industry_members as im  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 1
DESIGN = "813"
TOOL = "mainstream_research"
REGISTRATION_COMMIT = "31a09e9e"
CORRECTION_COMMIT = "b417f716"  # the first and second corrections (#779)
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/813"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T
ROUND = 3
ROUND_SIZE = 2
CUMULATIVE = 15  # X1～X8, S1～S3, R1～R2, M1～M2; H1 and #619～#689 apart
LOAD_FROM = ex.LOAD_FROM  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

# mainstream_v1 (#768 decision 6892019991), word for word.
WINDOW = 240
GROUP_COUNT = 5
LIST_SIZE = 20
MIN_MEMBERS = 5
TOP_SHARE_DIVISOR = 3  # the top ⌈n/3⌉ members
MIN_TOP_MEMBERS = 3
DEDUP_OVERLAP = 0.8
MOMENTUM = features._momentum(WINDOW)

# The member table (#779): its bytes are part of the definition.
MEMBERS_NAME = im.TABLE_NAME
MEMBERS_SHA256 = "2a7e0bf4b36425896ba77cd253b936a430669d1e5754e71f50a72661ae651827"
MEMBERS_DIR = ("research", "industry_members")  # beside the DB, docs RESEARCH_DB
# Its last snapshot: every T after it (the used segment) takes this one.
MEMBERS_LAST = "2024-09-30"
# AC-1 (#813 decision 6913227984): which rows of the table are T's groups.
# Both markets; TWSE rows before 2023-07-03 of the 47 companies of TWSE's 2023
# list go back to their code before that day ("remap_2023"; the other two
# policies were measured for AC-1 and are kept for the record only).  TWSE's
# other yearly reclassifications stay retroactive (docs 官方產業的成員 限制).
SOURCE_EXCHANGES: tuple[str, ...] = (im.TWSE, im.TPEX)
RETROACTIVE = "remap_2023"
RETROACTIVE_POLICIES = ("exclude", "keep", "remap_2023")
# TWSE 112年上市公司產業類別調整名單: symbol -> (code from 2023-07-03, code
# before).  42 went into 35-38 (the table's 42 retroactive symbols,
# 12/4/15/11), 5 moved between old codes.  A row is put back only while its
# snapshot is before 2023-07-03 and it still carries the new code; a row put
# back is not retroactive any more.
REMAP_SOURCE = {
    "announcement": "臺灣證券交易所公告 1121802250 附件「112年上市公司產業類別調整名單」",
    "url": "https://wwwc.twse.com.tw/staticFiles/announcement/announcement/1121802250-1.pdf",
    "created": "2023-05-19",  # the PDF's creation date
    "effective": "2023-07-03",
    "sha256": "da00070185c9b927bc78d5d7bd2f74304b84c06171901bf62db5b8226e289d8f",
    "downloaded": "2026-11-16",
}
REMAP_BEFORE = REMAP_SOURCE["effective"]
REMAP_2023: dict[str, tuple[str, str]] = {
    # 35 綠能環保 (12)
    "3708": ("35", "21"),
    **{s: ("35", "20") for s in ("6581", "6641", "6806", "6869", "6873", "8341")},
    **{s: ("35", "20") for s in ("8422", "8438", "8473", "9930", "9955")},
    # 36 數位雲端 (4)
    "3130": ("36", "30"),
    "6165": ("36", "20"),
    "6689": ("36", "31"),
    "8454": ("36", "18"),
    # 37 運動休閒 (15)
    "1432": ("37", "18"),
    "1598": ("37", "22"),
    "1736": ("37", "22"),
    "8462": ("37", "16"),
    **{s: ("37", "20") for s in ("4536", "5306", "6670", "6768", "8467", "8478")},
    **{s: ("37", "20") for s in ("9802", "9904", "9910", "9914", "9921")},
    # 38 居家生活 (11)
    **{s: ("38", "20") for s in ("2062", "3557", "6671", "6754", "6807", "8464")},
    **{s: ("38", "20") for s in ("8482", "9911", "9924", "9934", "9935")},
    # between old codes (5)
    "1439": ("14", "04"),
    "1472": ("14", "04"),
    "2442": ("14", "25"),
    "2424": ("27", "25"),
    "3054": ("02", "24"),
}

# The registration (docs 第三輪：M1、M2): the first signal date is the first
# session from 2013-02-10 (2013-01's revenues due, rolled; expected 2013-02-18).
START = ("date", date(2013, 2, 10))
HYPOTHESES: dict[str, dict[str, Any]] = {
    "M1": {
        "direction": "主流族群",
        "label": "官方產業族群強弱前 5 個族群，成員中 240 日報酬前 20 名",
        "rule": "daily",
        "top": LIST_SIZE,
        "hold": 20,
        "start": START,
    },
    "M2": {
        "direction": "主流族群",
        "label": "同 M1，持有 60 日",
        "rule": "daily",
        "top": LIST_SIZE,
        "hold": 60,
        "start": START,
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
VOLATILE_KEYS = ex.VOLATILE_KEYS


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "mainstream": {
            "window": WINDOW,
            "group_count": GROUP_COUNT,
            "list_size": LIST_SIZE,
            "min_members": MIN_MEMBERS,
            "top_share_divisor": TOP_SHARE_DIVISOR,
            "min_top_members": MIN_TOP_MEMBERS,
            "dedup_overlap": DEDUP_OVERLAP,
            "tie_break": "sha256(<T>:<instrument_id>)",
            "group_key": "group_id",
        },
        "members": {
            "table_sha256": MEMBERS_SHA256,
            # the code -> label table, E-commerce, TPEx 18 into Wholesale and
            # Retail, no depositary receipts or managed stocks (#779)
            "table_definitions": im.definitions(),
            "source_exchanges": list(SOURCE_EXCHANGES),
            "retroactive": RETROACTIVE,
            "remap_2023": {"source": REMAP_SOURCE, "companies": REMAP_2023},
            "available": "snapshot_date <= T",
            "match": "symbol, the instrument with a bar on T",
        },
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "bonferroni": [ex.BONFERRONI_AFTER, ex.ONE_SIDED],
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "warmup": WARMUP_CALENDAR_DAYS,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on.  A changed tool needs
    a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the ranking (app.mainstream's, copied) -------------------------------------


@dataclass(frozen=True)
class RankedGroup:
    group_id: str
    strength: float
    member_count: int
    top_count: int


@dataclass(frozen=True)
class RankedItem:
    instrument_id: int
    rank: int
    return_w: float
    excess_w: float
    group_ids: tuple[str, ...]


def top_count(member_count: int) -> int:
    """⌈n/3⌉ and at least 3 (never more than n)."""

    return min(
        member_count,
        max(MIN_TOP_MEMBERS, math.ceil(member_count / TOP_SHARE_DIVISOR)),
    )


def tie_key(day: date, instrument_id: int) -> str:
    return hashlib.sha256(f"{day.isoformat()}:{instrument_id}".encode()).hexdigest()


def rank_groups(
    returns: dict[int, float],
    members: dict[str, set[int]],
    index_return: float,
) -> tuple[list[RankedGroup], int]:
    """The chosen groups in rank order, and how many groups were ranked."""

    scored: list[tuple[float, str, list[int]]] = []
    for group_id, ids in members.items():
        valued = sorted((i for i in ids if i in returns), key=lambda i: -returns[i])
        if len(valued) < MIN_MEMBERS:
            continue
        top = valued[: top_count(len(valued))]
        strength = sum(returns[i] for i in top) / len(top) - index_return
        scored.append((strength, group_id, valued))
    scored.sort(key=lambda row: (-row[0], row[1]))
    chosen: list[RankedGroup] = []
    covered: set[int] = set()
    for strength, group_id, valued in scored:
        if len(chosen) == GROUP_COUNT:
            break
        ids = set(valued)
        if len(ids & covered) / len(ids) >= DEDUP_OVERLAP:
            continue
        chosen.append(
            RankedGroup(group_id, strength, len(valued), top_count(len(valued)))
        )
        covered |= ids
    return chosen, len(scored)


def rank_items(
    day: date,
    returns: dict[int, float],
    members: dict[str, set[int]],
    groups: list[RankedGroup],
    index_return: float,
) -> list[RankedItem]:
    owners: dict[int, list[str]] = {}
    for group in groups:
        for instrument_id in members[group.group_id]:
            if instrument_id in returns:
                owners.setdefault(instrument_id, []).append(group.group_id)
    ordered = sorted(owners, key=lambda i: (-returns[i], tie_key(day, i)))
    return [
        RankedItem(
            instrument_id=instrument_id,
            rank=rank,
            return_w=returns[instrument_id],
            excess_w=returns[instrument_id] - index_return,
            group_ids=tuple(owners[instrument_id]),
        )
        for rank, instrument_id in enumerate(ordered[:LIST_SIZE], start=1)
    ]


# --- the member table -------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    exchange: str
    code: str
    label: str
    group_id: str
    symbol: str
    retroactive: bool


def members_path(db: Path) -> Path:
    return db.resolve().parent.joinpath(*MEMBERS_DIR, MEMBERS_NAME)


def members_problems(path: Path) -> list[str]:
    """Refusals before anything is read: the table must be #779's."""

    if not path.is_file():
        return [f"{path} does not exist (the #779 member table)"]
    digest = ex.file_sha256(path)
    if digest != MEMBERS_SHA256:
        return [f"{path} has sha256 {digest}, not the member table's {MEMBERS_SHA256}"]
    return []


def read_members(path: Path, end: date) -> dict[date, list[Member]]:
    """The snapshots to ``end`` (none after it read), every row checked
    against the table's definitions."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("definitions_sha256") != im.definitions_sha256():
        raise ValueError("the member table's definitions are not industry_members'")
    fields = document["fields"]
    if list(fields) != list(im.ROW_FIELDS):
        raise ValueError(f"the member table's fields are {fields}")
    snapshots: dict[date, list[Member]] = defaultdict(list)
    last = end.isoformat()
    for day, exchange, code, _c, label, group_id, symbol, _n, retro in document["rows"]:
        if day > last:
            continue
        if im.GROUP_LABELS[exchange][code] != label or im.group_id(label) != group_id:
            raise ValueError(f"{day} {exchange} {code} is not the table's label")
        if bool(retro) != im.retroactive(exchange, code, day):
            raise ValueError(f"{day} {exchange} {code} {symbol}: retroactive flag")
        snapshots[date.fromisoformat(day)].append(
            Member(exchange, code, label, group_id, symbol, bool(retro))
        )
    return dict(sorted(snapshots.items()))


def group_of(
    member: Member,
    snapshot: date,
    exchanges: tuple[str, ...] | None = None,
    retroactive: str | None = None,
) -> str | None:
    """The row's group under the AC-1 decision; None when it is not counted."""

    exchanges = SOURCE_EXCHANGES if exchanges is None else exchanges
    retroactive = RETROACTIVE if retroactive is None else retroactive
    if member.exchange not in exchanges:
        return None
    if retroactive == "remap_2023":
        moved = REMAP_2023.get(member.symbol)
        if (
            member.exchange == im.TWSE
            and moved is not None
            and moved[0] == member.code
            and snapshot.isoformat() < REMAP_BEFORE
        ):
            return im.group_id(im.GROUP_LABELS[im.TWSE][moved[1]])
        return member.group_id
    if member.retroactive and retroactive == "exclude":
        return None
    return member.group_id


# --- reading ----------------------------------------------------------------------


@dataclass
class Context:
    market: pr.Market
    snapshots: dict[date, list[Member]]
    snapshot_days: list[date] = field(default_factory=list)
    by_symbol: dict[str, list[int]] = field(default_factory=dict)
    index_days: list[date] = field(default_factory=list)
    quotes: ex.Context | None = None

    @property
    def panel(self) -> lib.Panel:
        return self.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.quotes.quote(instrument_id, s)


def build_context(market: pr.Market, snapshots: dict[date, list[Member]]) -> Context:
    ctx = Context(market, snapshots)
    ctx.snapshot_days = sorted(snapshots)
    by_symbol: dict[str, list[int]] = defaultdict(list)
    for instrument_id, (_exchange, symbol, _name) in sorted(
        market.panel.symbols.items()
    ):
        by_symbol[symbol].append(instrument_id)
    ctx.by_symbol = dict(by_symbol)
    ctx.index_days = sorted(market.panel.index_close)
    ctx.quotes = ex.Context(market)
    return ctx


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel and the member snapshots from ``start`` to ``end``; nothing
    after ``end`` is read."""

    market = pr.load_market(db, start, raw_dir, end=end)
    return build_context(market, read_members(members, end))


# --- one signal date --------------------------------------------------------------


def snapshot_on(ctx: Context, day: date) -> date | None:
    """The latest snapshot with ``snapshot_date <= day``."""

    at = bisect_right(ctx.snapshot_days, day)
    return ctx.snapshot_days[at - 1] if at else None


def instrument_on(ctx: Context, member: Member, day: date) -> int | None:
    """The instrument of the row's symbol with a bar on ``day`` (the one of
    the row's exchange first)."""

    found = [
        instrument_id
        for instrument_id in ctx.by_symbol.get(member.symbol, ())
        if day in ctx.panel.series[instrument_id].position
    ]
    if len(found) > 1:
        found = [
            i for i in found if ctx.panel.symbols[i][0] == member.exchange
        ] or found
    return found[0] if found else None


def group_members(
    ctx: Context,
    day: date,
    exchanges: tuple[str, ...] | None = None,
    retroactive: str | None = None,
) -> tuple[dict[str, set[int]], set[int], set[int]]:
    """T's groups (group id -> instruments) under the AC-1 decision; the
    instruments of the rows still retroactive (35-38 before 2023-07-03, not
    put back) and of the rows put back by REMAP_2023 (both listed only)."""

    snapshot = snapshot_on(ctx, day)
    members: dict[str, set[int]] = defaultdict(set)
    retro: set[int] = set()
    remapped: set[int] = set()
    if snapshot is None:
        return {}, retro, remapped
    for member in ctx.snapshots[snapshot]:
        instrument_id = instrument_on(ctx, member, day)
        if instrument_id is None:
            continue
        group_id = group_of(member, snapshot, exchanges, retroactive)
        if group_id is not None and group_id != member.group_id:
            remapped.add(instrument_id)
        elif member.retroactive:
            retro.add(instrument_id)
        if group_id is not None:
            members[group_id].add(instrument_id)
    return dict(members), retro, remapped


def taiex_return(ctx: Context, day: date) -> float | None:
    """TAIEX's close on T over the earliest of its 241 closes to T, minus one;
    None without a close on T or with fewer closes."""

    at = bisect_right(ctx.index_days, day) - 1
    if at < WINDOW or ctx.index_days[at] != day:
        return None
    now = ctx.panel.index_close[day]
    then = ctx.panel.index_close[ctx.index_days[at - WINDOW]]
    if not (now and then and now > 0 and then > 0):
        return None
    return now / then - 1.0


def window_returns(members: list[tuple[lib.Series, int]]) -> dict[int, float]:
    returns = {}
    for item, at in members:
        value = MOMENTUM(item, at)
        if value is not None and math.isfinite(value):
            returns[item.instrument_id] = value
    return returns


@dataclass
class Day:
    """One signal date: what it picks and what the coverage counts."""

    universe: list[int]
    picks: list[int]
    groups: list[RankedGroup]
    items: list[RankedItem]
    ranked: int
    grouped: int  # universe members in some group
    selectable: int  # ... with a 240-session return
    retro: int  # universe members of a row still retroactive
    remapped: int  # universe members put back by REMAP_2023
    taiex: bool


def signal_day(
    ctx: Context,
    at: int,
    exchanges: tuple[str, ...] | None = None,
    retroactive: str | None = None,
) -> Day:
    panel = ctx.panel
    day = panel.sessions[at]
    universe = lib.universe(panel, day, MIN_LOTS)
    ids = [item.instrument_id for item, _ in universe]
    returns = window_returns(universe)
    members, retro, remapped = group_members(ctx, day, exchanges, retroactive)
    grouped = set().union(*members.values()) & set(ids) if members else set()
    index_return = taiex_return(ctx, day)
    # The order of the groups does not depend on TAIEX (one shift for all):
    # the coverage counts the ranked groups on a day without it too.
    groups, ranked = rank_groups(returns, members, index_return or 0.0)
    items: list[RankedItem] = []
    if index_return is None:
        groups = []
    else:
        items = rank_items(day, returns, members, groups, index_return)
    return Day(
        universe=ids,
        picks=[item.instrument_id for item in items],
        groups=groups,
        items=items,
        ranked=ranked,
        grouped=len(grouped),
        selectable=sum(1 for i in grouped if i in returns),
        retro=len(retro & set(ids)),
        remapped=len(remapped & set(ids)),
        taiex=index_return is not None,
    )


# --- one segment ------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None
    (``explore_research.segment_window`` on this tool's segments)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    group_rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    signal_days: int = 0


COVERAGE_KEYS = (
    "days",
    "universe",
    "grouped",
    "selectable",
    "ranked_groups",
    "retroactive",
    "remapped",
    "taiex_missing",
    "no_group",
    "short_groups",
)


def _coverage_add(coverage: dict[str, dict[str, int]], day: date, d: Day) -> None:
    year = coverage.setdefault(str(day.year), dict.fromkeys(COVERAGE_KEYS, 0))
    year["days"] += 1
    year["universe"] += len(d.universe)
    year["grouped"] += d.grouped
    year["selectable"] += d.selectable
    year["ranked_groups"] += d.ranked
    year["retroactive"] += d.retro
    year["remapped"] += d.remapped
    if not d.taiex:
        year["taiex_missing"] += 1
    elif not d.groups:
        year["no_group"] += 1
    elif len(d.groups) < GROUP_COUNT:
        year["short_groups"] += 1


def plan(
    ctx: Context,
    first: int,
    last: int,
    exchanges: tuple[str, ...] | None = None,
    retroactive: str | None = None,
    keep_rows: bool = True,
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    labels = {
        im.group_id(label): label
        for table in im.GROUP_LABELS.values()
        for label in table.values()
    }
    out = Plan()
    for at in range(first - 1, last):
        day = panel.sessions[at]
        d = signal_day(ctx, at, exchanges, retroactive)
        _coverage_add(out.coverage, day, d)
        out.signal_days += 1
        out.population[at + 1] = d.universe
        if d.picks:
            out.picks[at + 1] = d.picks
        if not keep_rows:
            continue
        for rank, group in enumerate(d.groups, 1):
            out.group_rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": rank,
                    "group": labels.get(group.group_id, group.group_id),
                    "strength": f"{group.strength:.10f}",
                    "members": group.member_count,
                    "top": group.top_count,
                }
            )
        for item in d.items:
            exchange, symbol, _ = panel.symbols.get(item.instrument_id, ("", "", ""))
            out.rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": item.rank,
                    "exchange": exchange,
                    "symbol": symbol,
                    "return_240": f"{item.return_w:.10f}",
                    "groups": ";".join(labels[g] for g in item.group_ids),
                    "tie": tie_key(day, item.instrument_id)[:12],
                }
            )
    return out


def _window_facts(sessions: list[date], window: tuple[int, int]) -> dict[str, Any]:
    first, last = window
    return {
        "first_signal": sessions[first - 1].isoformat(),
        "first_session": sessions[first].isoformat(),
        "last_session": sessions[last].isoformat(),
        "days": last - first + 1,
    }


def run_segment(
    ctx: Context,
    db: Path,
    names: list[str],
    segment: str,
    min_t: float = MIN_T,
    coverage_only: bool = False,
) -> dict[str, dict[str, Any]]:
    """The hypotheses on one segment; M1 and M2 share the plan (the same
    picks, held 20 or 60 sessions)."""

    sessions = ctx.panel.sessions
    spec = HYPOTHESES[names[0]] if names else HYPOTHESES["M1"]
    results = {
        name: {
            "hypothesis": name,
            "segment": segment,
            "verdict": None if segment == USED else ex.UNDECIDED,
            "reason": None,
            "window": {"days": 0},
            "prerequisites": None,
        }
        for name in names
    }
    window = segment_window(sessions, segment, spec)
    if window is None:
        for result in results.values():
            result["reason"] = "no_sessions"
        return results
    first, last = window
    days = last - first + 1
    for result in results.values():
        result["window"] = _window_facts(sessions, window)
    if segment != USED and not coverage_only:
        need = MIN_SEGMENT_DAYS[segment]
        delisted = ex.delisted_count(db, sessions[first], sessions[last])
        prerequisites = {
            "days": days,
            "min_days": need,
            "delisted": delisted,
            "ok": days >= need and delisted > 0,
        }
        for result in results.values():
            result["prerequisites"] = prerequisites
        if not prerequisites["ok"]:
            for result in results.values():
                result["reason"] = "segment_too_short" if days < need else "no_delisted"
            return results  # not run (docs 段長下限、先決條件)
    planned = plan(ctx, first, last, keep_rows=not coverage_only)
    for result in results.values():
        result["window"]["signal_days"] = planned.signal_days
        result["coverage"] = planned.coverage
    if coverage_only:
        return results
    taiex = ex._taiex(ctx.panel, first, last)
    for name in names:
        result = results[name]
        hold = HYPOTHESES[name]["hold"]
        mine = pr.simulate(planned.picks, ctx.quote, first, last, hold, LIST_SIZE)
        population = pr.simulate(planned.population, ctx.quote, first, last, hold, None)
        returns = pr.daily_returns(mine.equity)
        others = pr.daily_returns(population.equity)
        excess = {
            POPULATION: pr.excess_metrics([a - b for a, b in zip(returns, others)]),
            TAIEX: pr.excess_metrics(
                [a - b for a, b in zip(returns, taiex) if b is not None]
            ),
        }
        absolute = statistics.fmean(returns) if returns else None
        result["excess"] = excess
        result["absolute"] = {"days": len(returns), "mean": absolute}
        result["curves"] = {
            name: pr.curve_metrics(returns, mine.invested, ex._turnover(mine)),
            POPULATION: pr.curve_metrics(
                others, population.invested, ex._turnover(population)
            ),
            TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
        }
        result["win"] = ex.win_rate(mine)
        result["counts"] = {
            name: dict(mine.counts),
            POPULATION: dict(population.counts),
        }
        if segment != USED:
            result["min_t"] = min_t
            result["verdict"] = ex.explore_judge(
                segment, days, True, excess[POPULATION], absolute, min_t
            )
        result["_dates"] = sessions[first : last + 1]
        result["_equity"] = (mine.equity, population.equity)
        result["_positions"] = mine.positions
        result["_rows"] = planned.rows
        result["_groups"] = planned.group_rows
    return results


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public


def coverage_lines(coverage: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "| 年 | 訊號日 | 母體檔次（日均） | 有族群（占母體） | 有族群且有 240 日報酬（日均） "
        "| 可排名的族群（日均） | 依 2023 名單放回原產業（日均） | 仍標回溯（日均） "
        "| TAIEX 不足不選 "
        "| 沒有可排名的族群 | 湊不滿 5 個族群 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in sorted(coverage.items()):
        n = row["days"] or 1
        share = _pct(row["grouped"] / row["universe"], 1) if row["universe"] else "—"
        lines.append(
            f"| {year} | {row['days']:,} | {row['universe'] / n:,.0f} | {share} "
            f"| {row['selectable'] / n:,.0f} | {row['ranked_groups'] / n:,.1f} "
            f"| {row['remapped'] / n:,.1f} | {row['retroactive'] / n:,.1f} "
            f"| {row['taiex_missing']:,} "
            f"| {row['no_group']:,} | {row['short_groups']:,} |"
        )
    return lines


def _members_line() -> str:
    exchanges = "、".join("上市" if e == im.TWSE else "上櫃" for e in SOURCE_EXCHANGES)
    retro = {
        "exclude": "上市 35～38 在 2023-07-03 以前的回溯列排除",
        "keep": "上市 35～38 在 2023-07-03 以前的回溯列保留",
        "remap_2023": "上市 2023-07-03 改分類的 47 家，在那天以前依證交所調整名單"
        f"（公告 1121802250，sha256 `{REMAP_SOURCE['sha256'][:16]}…`）放回原產業；"
        "其他年度的調整仍是回溯的",
    }[RETROACTIVE]
    return (
        f"- 族群來源：{exchanges}的官方產業逐月成員表（sha256 `{MEMBERS_SHA256[:16]}…`）；"
        + retro
        + f"。成員表到 {MEMBERS_LAST}，之後的 T 都用那一份"
    )


def hypothesis_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（mainstream_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}，不跑）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、K＝{spec['hold']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`，更正 `{CORRECTION_COMMIT}`；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        _members_line(),
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日 "
        f"{window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 日",
    ]
    prerequisites = result.get("prerequisites")
    if prerequisites:
        lines.append(
            f"- 先決條件：段長 {prerequisites['days']}／下限 {prerequisites['min_days']} 日；"
            f"段內已下市公司 {prerequisites['delisted']} 檔"
        )
    lines += [
        f"- 副本：最新交易日 {header['copy']['latest']}，alembic `{header['copy']['alembic']}`",
        f"- 重現：`{header['command']}`",
        "",
    ]
    if "excess" in result:
        e, a = result["excess"], result["absolute"]
        lines += [
            "## 數字",
            "",
            "| 量 | 日數 | 日均 | 年化 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
            f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
            f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
            f"| 超額（對母體，判定） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
            f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {result.get('min_t', MIN_T):.2f}。",
            "",
            "## 只列出",
            "",
            "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        labels = {name: name, POPULATION: "母體（基準）", TAIEX: "加權指數（價格指數）"}
        for key in (TAIEX, name, POPULATION):
            c = result["curves"][key]
            held = (
                "| — | — |"
                if key == TAIEX
                else f"| {_pct(c.get('invested'), 1)} | {lib.num(c.get('turnover'), 1)} |"
            )
            lines.append(
                f"| {labels[key]} | {c['days']} | {_pct(c.get('annual'))} "
                f"| {_pct(c.get('volatility'))} | {_pct(c.get('max_drawdown'))} " + held
            )
        w = result["win"]
        counts = result["counts"][name]
        lines += [
            "",
            f"勝率（買進的每一筆，期末未賣以最後收盤計）：{_pct(w['rate'], 1)}"
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if result.get("coverage"):
        lines += [
            "## 成員覆蓋（不含報酬）",
            "",
            *coverage_lines(result["coverage"]),
            "",
        ]
    return "\n".join(lines)


TRADE_FIELDS = (
    "account",
    "exchange",
    "symbol",
    "bought",
    "due",
    "sold",
    "how",
    "cost",
    "proceeds",
)
PICK_FIELDS = (
    "signal_date",
    "rank",
    "exchange",
    "symbol",
    "return_240",
    "groups",
    "tie",
)
GROUP_FIELDS = ("signal_date", "rank", "group", "strength", "members", "top")


def write_hypothesis(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    body = {
        **{
            key: header[key]
            for key in ("tool", "version", "design", "definitions_sha256")
        },
        "label": spec["label"],
        "direction": spec["direction"],
        "parameters": {
            key: value
            for key, value in spec.items()
            if key not in ("label", "direction")
        },
        **public(result),
    }
    (out / "tables.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(
        hypothesis_markdown(result, header), encoding="utf-8"
    )
    if "_dates" not in result:
        return
    panel = header["_panel"]
    mine, population = result["_equity"]
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", name, POPULATION, "taiex_close"])
        for at, day in enumerate(result["_dates"]):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{mine[at]:.8f}",
                    f"{population[at]:.8f}",
                    panel.index_close.get(day),
                ]
            )
    for file, fields, rows in (
        ("picks.csv", PICK_FIELDS, result["_rows"]),
        ("groups.csv", GROUP_FIELDS, result["_groups"]),
    ):
        with (out / file).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRADE_FIELDS)
        for position in result["_positions"]:
            exchange, symbol, _ = panel.symbols.get(
                position.instrument_id, ("", "", "")
            )
            writer.writerow(
                [
                    position.account,
                    exchange,
                    symbol,
                    sessions[position.bought].isoformat(),
                    sessions[position.due].isoformat()
                    if position.due < len(sessions)
                    else "",
                    sessions[position.sold].isoformat()
                    if position.sold is not None
                    else "",
                    position.how,
                    f"{position.cost:.10f}",
                    "" if position.proceeds is None else f"{position.proceeds:.10f}",
                ]
            )


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（mainstream_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`、更正 `{CORRECTION_COMMIT}`"
        f"（docs/spec/evidence.md「第三輪：M1、M2」）；工具 {DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        _members_line(),
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        f"- 門檻：超額日均 > 0 且 t ≥ {report['min_t']:.2f}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司",
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀）",
        f"- 耗時 {report.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(report.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{report['command']}`",
    ]
    if segment == EXPLORATION:
        lines.append("- 本次跑的假設：" + "、".join(report.get("selected") or []))
    if segment == VALIDATION:
        lines.append(
            f"- 前瞻觀察：超額日均 > 0 但 t < {report['min_t']:.2f}，且絕對報酬日均 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    lines += [
        "",
        "## 判定",
        "",
        "| 代號 | 方向 | N／K | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 | 判定 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, row in report["hypotheses"].items():
        spec = HYPOTHESES[name]
        e = row.get("excess") or {}
        x = row.get("taiex_excess") or {}
        verdict = row["verdict"] + (
            f"（{REASONS[row['reason']]}）" if row.get("reason") else ""
        )
        lines.append(
            f"| {name} | {spec['direction']} | {spec['top']}／{spec['hold']} | {row['days']} "
            f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
            f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
            f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
        )
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            "| 代號 | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, row in report["used"].items():
            e = row.get("excess") or {}
            x = row.get("taiex_excess") or {}
            lines.append(
                f"| {name} | {row['days']} | {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
                f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
                f"| {_pct(row.get('absolute_mean'), 3)} |"
            )
    lines += [
        "",
        "各假設的數字、只列出的指標與成員覆蓋見 `<代號>/summary.md`。",
        "",
    ]
    return "\n".join(lines)


def coverage_markdown(body: dict[str, Any]) -> str:
    window = body["window"] or {}
    return "\n".join(
        [
            f"# 新策略探索 第 {body['round']} 輪 M1、M2 成員覆蓋（探索段，不含報酬）",
            "",
            f"- mainstream_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
            _members_line(),
            f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
            f"alembic `{body['copy']['alembic']}`",
            f"- 訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日"
            "（M1、M2 同一份名單）",
            f"- 重現：`{body['command']}`",
            "- 有族群：母體中 T 日的成員表裡有族群的檔；可排名的族群：有值成員 ≥ "
            f"{MIN_MEMBERS} 檔；沒有可排名的族群、湊不滿 {GROUP_COUNT} 個族群只數 TAIEX "
            "足夠的日子",
            "",
            *coverage_lines(body["coverage"]),
            "",
        ]
    )


def _row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": result["verdict"],
        "reason": result["reason"],
        "days": (result["window"] or {}).get("days", 0),
        "taiex_excess": (result.get("excess") or {}).get(TAIEX),
        "excess": (result.get("excess") or {}).get(POPULATION),
        "absolute_mean": (result.get("absolute") or {}).get("mean"),
        "prerequisites": result.get("prerequisites"),
    }


# --- the runs ---------------------------------------------------------------------


def _header(db: Path, segment: str, command: str, read_until: date) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "version": VERSION,
        "design": DESIGN,
        "registration_commit": REGISTRATION_COMMIT,
        "correction_commit": CORRECTION_COMMIT,
        "segment": segment,
        "round": ROUND,
        "round_size": ROUND_SIZE,
        "cumulative": CUMULATIVE,
        "definitions_sha256": definitions_sha256(),
        "members_sha256": MEMBERS_SHA256,
        "tool_commit": ex.tool_commit(),
        "command": command,
        "copy": pr.copy_facts(db),
        "read_until": read_until.isoformat(),
    }


def _finish(out: Path, report: dict[str, Any], started: float) -> str:
    report["elapsed_seconds"] = time.monotonic() - started
    report["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    path = out / "explore.json"
    path.write_text(
        json.dumps(public(report), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    sha256 = ex.file_sha256(path)
    (out / "explore.md").write_text(overview_markdown(report, sha256), encoding="utf-8")
    return sha256


def load_from(segment: str) -> date:
    """The first day read: the copy's start for the exploration (as
    ``explore_research``), the warm-up before a later segment."""

    first_day = SEGMENTS[segment][0]
    if first_day is None:
        return LOAD_FROM
    return first_day - timedelta(days=WARMUP_CALENDAR_DAYS)


def run_exploration(
    db: Path,
    out: Path,
    names: list[str],
    command: str = "",
    coverage_only: bool = False,
    members: Path | None = None,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    members = members_path(db) if members is None else members
    ctx = load(db, members, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    header["_panel"] = ctx.panel
    if coverage_only:
        results = run_segment(ctx, db, ["M1"], EXPLORATION, coverage_only=True)
        body = {
            **public(header),
            "coverage_only": True,
            "window": results["M1"]["window"],
            "coverage": results["M1"].get("coverage", {}),
        }
        (out / "coverage.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        (out / "coverage.md").write_text(coverage_markdown(body), encoding="utf-8")
        progress("coverage")
        return {"out": str(out.resolve()), "coverage_only": True}
    report = {**header, "min_t": MIN_T, "selected": list(names), "hypotheses": {}}
    results = run_segment(ctx, db, list(names), EXPLORATION)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
    sha256 = _finish(out, report, started)
    # Only a finished run with its report written counts as the one run (#721).
    commit, finished = ex.tool_commit(), ex._now()
    mine = [
        {
            "hypothesis": name,
            "tool": TOOL,
            "round": ROUND,
            "segment": EXPLORATION,
            "version": VERSION,
            "status": "finished",
            "finished_at": finished,
            "report_sha256": sha256,
            "tool_commit": commit,
            "definitions_sha256": report["definitions_sha256"],
            "verdict": report["hypotheses"][name]["verdict"],
        }
        for name in names
    ]
    ledger = ex.ledger_path(db)
    ex.write_ledger(ledger, ex.read_ledger(ledger) + mine)
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": EXPLORATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def run_validation(
    db: Path,
    out: Path,
    names: list[str],
    source: dict[str, str],
    command: str = "",
    members: Path | None = None,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the validation segment, once: the ledger first, then the data."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    members = members_path(db) if members is None else members
    commit = ex.tool_commit()
    ledger = ex.ledger_path(db)
    entries = ex.read_ledger(ledger)
    for name in names:
        entries.append(
            {
                "hypothesis": name,
                "tool": TOOL,
                "round": ROUND,
                "segment": VALIDATION,
                "version": VERSION,
                "status": "started",
                "started_at": ex._now(),
                "report_sha256": source["sha256"],
                "url": source["url"],
                "tool_commit": commit,
                "definitions_sha256": definitions_sha256(),
            }
        )
    ex.write_ledger(ledger, entries)  # before any validation data is read
    end = SEGMENTS[VALIDATION][1]
    ctx = load(db, members, load_from(VALIDATION), end, out / RAW_DIR_NAME)
    header = _header(db, VALIDATION, command, end)
    header["_panel"] = ctx.panel
    min_t = ex.validation_min_t(CUMULATIVE)
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    results = run_segment(ctx, db, names, VALIDATION, min_t=min_t)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
    for entry in entries:
        if (
            entry.get("tool") == TOOL
            and entry["status"] == "started"
            and entry["hypothesis"] in report["hypotheses"]
        ):
            entry["status"] = "finished"
            entry["finished_at"] = ex._now()
            entry["verdict"] = report["hypotheses"][entry["hypothesis"]]["verdict"]
    ex.write_ledger(ledger, entries)
    passed = [
        name for name in names if report["hypotheses"][name]["verdict"] == ex.PASSED
    ]
    if passed:  # the used segment only for the passed ones
        used_end = SEGMENTS[USED][1]
        used_ctx = load(db, members, load_from(USED), used_end, out / RAW_DIR_NAME)
        used_header = {**header, "_panel": used_ctx.panel}
        used = run_segment(used_ctx, db, passed, USED)
        report["used"] = {}
        for name in passed:
            write_hypothesis(out / name / USED, used[name], used_header)
            report["used"][name] = _row(used[name])
    sha256 = _finish(out, report, started)
    mine = [
        entry
        for entry in entries
        if entry.get("tool") == TOOL
        and entry["hypothesis"] in names
        and entry.get("segment") == VALIDATION
    ]
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": VALIDATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mainstream_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        f"{MEMBERS_NAME} beside the DB); its sha256 must be MEMBERS_SHA256",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: the yearly member coverage, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): M1, M2 or "
        "M1,M2; each runs once per tool version",
    )
    parser.add_argument(
        "--exploration-report", help="validation: the exploration explore.json"
    )
    parser.add_argument(
        "--exploration-sha256",
        help="validation: the sha256 quoted in the public comment",
    )
    parser.add_argument(
        "--exploration-url", help="validation: the public comment or pr-assets link"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    gate = (args.exploration_report, args.exploration_sha256, args.exploration_url)
    if args.segment == EXPLORATION and any(gate):
        parser.error("--exploration-* go with --segment validation only")
    if args.segment == VALIDATION and args.coverage_only:
        parser.error("--coverage-only goes with --segment exploration only")
    if args.hypotheses is not None and (
        args.segment == VALIDATION or args.coverage_only
    ):
        parser.error(
            "--hypotheses goes with --segment exploration only, not --coverage-only"
        )
    db = Path(args.db)
    members = Path(args.members) if args.members else members_path(db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    problems = [*problems, *members_problems(members)]
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/mainstream_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(
            db,
            Path(args.out),
            names,
            command,
            args.coverage_only,
            members=members,
            progress=progress,
        )
    else:
        problems, names, _report = ex.validation_problems(
            db, *gate, HYPOTHESES, DESIGN, definitions_sha256()
        )
        if problems:
            print(json.dumps({"refused": problems}, ensure_ascii=False))
            return 2
        line = run_validation(
            db,
            Path(args.out),
            names,
            {
                "sha256": args.exploration_sha256.strip().lower(),
                "url": args.exploration_url,
            },
            command,
            members=members,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
