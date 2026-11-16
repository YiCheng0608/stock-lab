"""tools/research/mainstream_research.py: the registered M1, M2 (#813).

The registered numbers (N, K, start, mainstream_v1's parameters) are asserted
as written in docs/spec/evidence.md 第三輪：M1、M2, and the ranking is compared
with the product's ``app.mainstream`` on one fixture: a change of
``mainstream_v1`` turns these tests red instead of changing the registered
hypotheses silently.  The runs use a synthetic copy on a compressed calendar
(``compressed``): the segments, the floors and the start are moved into the
fixture's 330 sessions, everything else is the registered one, and every
output file is locked by a golden file in
``backend/tests/fixtures/mainstream_research/`` (``MAINSTREAM_GOLDEN_UPDATE=1``
rewrites them; a diff there is a change of a hypothesis, not an edit).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import shutil
import sys
from dataclasses import astuple
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app import mainstream as product
from app.models import Base, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "mainstream_research"
URL = "https://github.com/YiCheng0608/stock-lab/issues/813#issuecomment-1"


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
ex = _tool("explore_research")
im = _tool("industry_members")
tool = _tool("mainstream_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    assert list(tool.HYPOTHESES) == ["M1", "M2"]
    assert {n: (s["top"], s["hold"]) for n, s in tool.HYPOTHESES.items()} == {
        "M1": (20, 20),
        "M2": (20, 60),
    }
    assert {s["start"] for s in tool.HYPOTHESES.values()} == {
        ("date", date(2013, 2, 10))
    }
    assert (tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (3, 2, 15)
    assert tool.SEGMENTS == ex.SEGMENTS and tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "31a09e9e"
    assert tool.MEMBERS_SHA256 == (
        "2a7e0bf4b36425896ba77cd253b936a430669d1e5754e71f50a72661ae651827"
    )


def test_the_parameters_are_the_products_mainstream_v1():
    """W＝240, G＝5, 80 %, ⌈n/3⌉ ≥ 3, ≥ 5 members, the first 20, the hash."""

    mine = (
        tool.WINDOW,
        tool.GROUP_COUNT,
        tool.LIST_SIZE,
        tool.MIN_MEMBERS,
        tool.TOP_SHARE_DIVISOR,
        tool.MIN_TOP_MEMBERS,
        tool.DEDUP_OVERLAP,
        tool.MIN_LOTS,
    )
    assert mine == (240, 5, 20, 5, 3, 3, 0.8, 1000.0)
    theirs = (
        product.WINDOW,
        product.GROUP_COUNT,
        product.LIST_SIZE,
        product.MIN_MEMBERS,
        product.TOP_SHARE_DIVISOR,
        product.MIN_TOP_MEMBERS,
        product.DEDUP_OVERLAP,
        product.MIN_AVERAGE_LOTS,
    )
    assert mine == theirs
    assert product.MAINSTREAM_VERSION == "mainstream_v1"
    assert product.MAINSTREAM_CONFIG == {
        "window": 240,
        "group_count": 5,
        "list_size": 20,
        "min_members": 5,
        "group_strength": "mean_of_top_third_minus_taiex",
        "min_top_members": 3,
        "dedup_overlap": 0.8,
        "liquidity_bars": 20,
        "min_average_lots": 1000.0,
        "group_types": ["official_industry", "theme"],
        "instrument_types": ["stock", "ipo"],
        "index": "TAIEX",
        "tie_break": "sha256(<T>:<instrument_id>)",
    }


# --- the ranking, against app.mainstream --------------------------------------------


def _world(seed: int):
    """Random returns and overlapping groups: ties, dedup at and around 80 %,
    groups under 5 valued members, members outside the universe."""

    rng = random.Random(seed)
    ids = list(range(1, rng.randint(20, 90)))
    levels = [round(rng.uniform(-0.5, 1.5), 2) for _ in range(6)]
    returns = {
        i: rng.choice(levels) if rng.random() < 0.3 else rng.uniform(-0.6, 2.0)
        for i in ids
        if rng.random() < 0.85
    }
    members = {}
    for g in range(rng.randint(3, 14)):
        size = rng.randint(2, 25)
        chosen = set(rng.sample(ids, min(size, len(ids))))
        if members and rng.random() < 0.3:  # a near copy of an earlier group
            base = rng.choice(list(members.values()))
            chosen = set(
                list(base)[: max(1, int(len(base) * rng.choice((0.75, 0.8, 0.9))))]
            )
            chosen |= set(rng.sample(ids, rng.randint(0, 3)))
        members[
            f"official-industry-{hashlib.sha1(str(g).encode()).hexdigest()[:16]}"
        ] = (
            chosen | {10_000 + g}  # never in the universe
        )
    return returns, members, rng.uniform(-0.2, 0.4)


@pytest.mark.parametrize("seed", range(300))
def test_the_ranking_is_the_products(seed):
    returns, members, index_return = _world(seed)
    day = date(2014, 3, 3) + timedelta(days=seed)
    mine, ranked = tool.rank_groups(returns, members, index_return)
    theirs, their_ranked = product.rank_groups(returns, members, index_return)
    assert ranked == their_ranked
    assert [astuple(g) for g in mine] == [astuple(g) for g in theirs]
    assert [
        astuple(i) for i in tool.rank_items(day, returns, members, mine, index_return)
    ] == [
        astuple(i)
        for i in product.rank_items(day, returns, members, theirs, index_return)
    ]


def test_the_dedup_and_the_top_third_are_exercised():
    """The fixture above reaches the rules a changed parameter would move."""

    skipped = short = 0
    for seed in range(300):
        returns, members, index_return = _world(seed)
        chosen, ranked = tool.rank_groups(returns, members, index_return)
        skipped += len(chosen) < min(ranked, tool.GROUP_COUNT)
        short += 0 < ranked < tool.GROUP_COUNT
    assert skipped > 10 and short > 10


def test_an_80_percent_overlap_is_skipped_and_ties_go_by_the_group_key():
    a, b, c = "official-industry-a", "official-industry-b", "official-industry-c"
    returns = {i: 1.0 for i in range(1, 11)} | {i: 0.5 for i in range(11, 16)}
    members = {
        b: set(range(1, 6)),
        a: set(range(1, 6)),  # tie with b: a first, then b fully covered
        c: {1, 2, 3, 4, 11},  # 80 % covered: skipped
    }
    chosen, ranked = tool.rank_groups(returns, members, 0.0)
    assert ranked == 3 and [g.group_id for g in chosen] == [a]
    theirs = product.rank_groups(returns, members, 0.0)[0]
    assert [astuple(g) for g in chosen] == [astuple(g) for g in theirs]


# --- the 240-session return, against app.mainstream.universe_returns -----------------

SESSIONS = 330
STOCKS = list(range(1, 35))
LOW_VOLUME = 35
DELISTED = {36: 280}
SUSPENDED = (5, 299)  # (id, session): suspended on that day
SPLIT = (4, 150)  # 2-for-1 on that session
DIVIDEND = (3, 200)  # cash 2.0, reference price given
NO_TAIEX = 260
INDEX_ID = 90


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    """A persistent drift by id (high ids rise faster) and a ±0.8 % noise."""

    drift = (i - 12) * 0.0002
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + drift + 0.016 * noise(i, t)
        if (i, t) == (SPLIT[0], SPLIT[1]):
            level /= 2.0
        if (i, t) == (DIVIDEND[0], DIVIDEND[1]):
            level -= 2.0
        out.append(round(level, 4))
    return out


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ids = [*STOCKS, LOW_VOLUME, *DELISTED]
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"{1000 + i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "delisted" if i in DELISTED else "active",
                }
                for i in ids
            ]
            + [
                {
                    "id": INDEX_ID,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars = []
        for i in ids:
            prices = closes(i)
            volume = 500_000 if i == LOW_VOLUME else 2_000_000 + 10_000 * i
            for t, day in enumerate(days):
                if t > DELISTED.get(i, SESSIONS):
                    break
                close = prices[t]
                open_ = (prices[t - 1] if t else close) * (1 + 0.004 * noise(i, t, "o"))
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(open_, 4),
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": volume,
                        "turnover": close * volume,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": (i, t) == SUSPENDED,
                    }
                )
        for t, day in enumerate(days):
            if t == NO_TAIEX:
                continue
            level = 8000.0 + 3 * t
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "adj_close": level,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(
            insert(CorporateAction),
            [
                {
                    "instrument_id": SPLIT[0],
                    "action_date": days[SPLIT[1]],
                    "action_type": "split",
                    "split_ratio": 2.0,
                    "source": "test",
                },
                {
                    "instrument_id": DIVIDEND[0],
                    "action_date": days[DIVIDEND[1]],
                    "action_type": "dividend",
                    "cash_dividend": 2.0,
                    "reference_price": closes(DIVIDEND[0])[DIVIDEND[1] - 1] - 2.0,
                    "source": "test",
                },
            ],
        )
        db.commit()
    engine.dispose()
    return path


# Members: (exchange, code, ids).  TWSE and TPEx 24 are one group
# (Semiconductor); TWSE 37 is retroactive in 2013; TPEx 34 is E-commerce; stock
# 32 moves from TPEx 20 to TPEx 22 in the snapshot after session 270.
GROUPS = (
    ("TWSE", "24", (1, 3, 5, 7, 9, 11, 13)),
    ("TPEx", "24", (2, 4, 6)),
    ("TWSE", "28", (15, 17, 19, 21, 23, LOW_VOLUME, 36)),
    ("TWSE", "37", (25, 27, 29, 31, 33)),
    ("TPEx", "22", (8, 10, 12, 14, 16, 18)),
    ("TPEx", "34", (20, 22, 24, 26, 28)),
    ("TPEx", "20", (30, 32, 34)),
)
MOVED, MOVED_AFTER = 32, 270


def snapshot_days() -> list[date]:
    """The last session of each month."""

    days = trading_days()
    return [
        d
        for k, d in enumerate(days)
        if k + 1 == len(days) or days[k + 1].month != d.month
    ]


def member_rows() -> list[list]:
    days = trading_days()
    rows = []
    for day in snapshot_days():
        for exchange, listed, ids in GROUPS:
            for i in ids:
                code = "22" if i == MOVED and day > days[MOVED_AFTER] else listed
                label = im.GROUP_LABELS[exchange][code]
                rows.append(
                    [
                        day.isoformat(),
                        exchange,
                        code,
                        "",
                        label,
                        im.group_id(label),
                        f"{1000 + i}",
                        f"N{i}",
                        im.retroactive(exchange, code, day.isoformat()),
                    ]
                )
    rows.sort()
    return rows


def write_members(folder: Path) -> Path:
    target = folder.joinpath(*tool.MEMBERS_DIR, tool.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(member_rows(), "2013-01", "2014-04"))
    return target


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("mainstream")
    write_members(folder)
    return build(folder / "stock.db")


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    """research_report.load_actions points these at the copy for app.config."""

    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def context(fixture_db, tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    return one_process(
        lambda: tool.load(
            fixture_db,
            tool.members_path(fixture_db),
            date(1990, 1, 1),
            trading_days()[-1],
            raw,
        )
    )


@pytest.mark.parametrize("t", [240, 241, 260, 280, 281, 299, 329])
def test_the_240_session_return_is_the_products(fixture_db, context, t):
    """Same returns as ``app.mainstream.universe_returns``: the split and the
    cash dividend in the window (the three edges in docs are not in it), the
    low-volume, suspended, too-short and delisted stocks left out alike."""

    day = trading_days()[t]
    engine = create_engine(f"sqlite:///{fixture_db}")
    try:
        with Session(engine) as db:
            theirs = product.universe_returns(db, day)
    finally:
        engine.dispose()
    mine = tool.window_returns(lib.universe(context.panel, day, tool.MIN_LOTS))
    assert sorted(mine) == sorted(theirs)
    for instrument_id, value in theirs.items():
        assert mine[instrument_id] == pytest.approx(value, rel=1e-12, abs=1e-12)
    if t == 299:
        assert SUSPENDED[0] not in mine and LOW_VOLUME not in mine
        assert {SPLIT[0], DIVIDEND[0]} <= set(mine)
    if t == 240:
        assert 36 in mine and len(mine) == len(STOCKS) + 1  # 35 is not liquid
    if t == 281:
        assert 36 not in mine


def test_the_split_and_the_dividend_are_on_the_holders_basis(context):
    days = trading_days()
    item = context.panel.series[SPLIT[0]]
    at = item.position[days[299]]
    raw = closes(SPLIT[0])
    assert tool.MOMENTUM(item, at) == pytest.approx(raw[299] / (raw[59] / 2.0) - 1.0)


# --- the members on T ---------------------------------------------------------------


def _groups(context, t, **policy):
    members, retro = tool.group_members(context, trading_days()[t], **policy)
    by_label = {
        label: members.get(im.group_id(label), set())
        for label in ("Semiconductor", "Other", "Biotechnology", "Sports and Leisure")
    }
    return by_label, retro


def test_t_takes_the_latest_snapshot_on_or_before_it(context):
    days = trading_days()
    snaps = snapshot_days()
    move = next(d for d in snaps if d > days[MOVED_AFTER])
    t_move = days.index(move)
    assert tool.snapshot_on(context, days[0]) is None  # before the first
    assert tool.snapshot_on(context, move) == move  # T = D: public that evening
    assert tool.snapshot_on(context, days[t_move - 1]) < move
    before, _ = _groups(context, t_move - 1)
    on, _ = _groups(context, t_move)
    assert MOVED in before["Other"] and MOVED not in before["Biotechnology"]
    assert MOVED in on["Biotechnology"] and MOVED not in on["Other"]


def test_both_markets_make_one_group_of_a_label(context):
    groups, _ = _groups(context, 299)
    assert groups["Semiconductor"] == {1, 2, 3, 4, 5, 6, 7, 9, 11, 13}


def test_the_retroactive_rows_follow_the_ac1_decision(context):
    sports = {25, 27, 29, 31, 33}
    kept, retro = _groups(context, 299, retroactive="keep")
    dropped, retro_dropped = _groups(context, 299, retroactive="exclude")
    assert kept["Sports and Leisure"] == sports and retro == sports
    assert dropped["Sports and Leisure"] == set() and retro_dropped == sports
    tpex, _ = _groups(context, 299, exchanges=("TPEx",))
    assert tpex["Semiconductor"] == {2, 4, 6} and tpex["Sports and Leisure"] == set()
    # the module's decision
    default, _ = _groups(context, 299)
    assert default["Sports and Leisure"] == (
        sports
        if tool.RETROACTIVE == "keep" and "TWSE" in tool.SOURCE_EXCHANGES
        else set()
    )


def test_a_retroactive_row_from_2023_07_03_is_not_retroactive():
    sports = im.group_id("Sports and Leisure")
    other = im.group_id("Other")
    for day, flag in (("2023-06-30", True), ("2023-07-03", False)):
        assert im.retroactive("TWSE", "37", day) is flag
        member = tool.Member("TWSE", "37", "Sports and Leisure", sports, "9921", flag)
        snapshot = date.fromisoformat(day)
        assert tool.group_of(member, snapshot, retroactive="exclude") == (
            None if flag else sports
        )
        assert tool.group_of(member, snapshot, retroactive="keep") == sports
        # 9921 巨大 was 其他 before 2023-07-03 (TWSE's 2023 list)
        assert tool.group_of(member, snapshot, retroactive="remap_2023") == (
            other if flag else sports
        )


def test_the_2023_list_puts_the_47_back_before_2023_07_03():
    remap = tool.REMAP_2023
    assert len(remap) == 47
    new = [code for code, _old in remap.values()]
    assert [new.count(c) for c in ("35", "36", "37", "38")] == [12, 4, 15, 11]
    assert sum(1 for code in new if code not in ("35", "36", "37", "38")) == 5
    assert all(old in im.GROUP_LABELS["TWSE"] for _new, old in remap.values())
    before, after = date(2023, 6, 30), date(2023, 7, 3)
    semi, food = im.group_id("Semiconductor"), im.group_id("Food")
    moved = tool.Member("TWSE", "02", "Food", food, "3054", False)  # 半導體 -> 食品
    assert tool.group_of(moved, before, retroactive="remap_2023") == semi
    assert tool.group_of(moved, after, retroactive="remap_2023") == food
    # a row no longer under its 2023 code (moved again later) is left alone
    again = tool.Member("TWSE", "20", "Other", im.group_id("Other"), "3054", False)
    assert tool.group_of(again, before, retroactive="remap_2023") == im.group_id(
        "Other"
    )
    tpex = tool.Member("TPEx", "02", "Food", food, "3054", False)
    assert tool.group_of(tpex, before, retroactive="remap_2023") == food


def test_the_excluded_stocks_stay_in_the_population(context):
    d = tool.signal_day(context, 299, retroactive="exclude")
    assert {25, 27, 29, 31, 33} <= set(d.universe)
    assert not {25, 27, 29, 31, 33} & set(d.picks)
    assert d.retro == 5


def test_no_taiex_close_picks_nothing(context):
    d = tool.signal_day(context, NO_TAIEX)
    assert d.universe and not d.picks and not d.taiex and d.ranked > 0
    assert tool.taiex_return(context, trading_days()[239]) is None  # 240 closes
    assert tool.taiex_return(context, trading_days()[240]) == pytest.approx(
        (8000.0 + 3 * 240) / 8000.0 - 1.0
    )


def test_the_member_table_must_be_779s(fixture_db, tmp_path):
    assert (
        tool.members_problems(tool.members_path(fixture_db)) != []
    )  # not the real one
    other = tmp_path / "x.json"
    assert "does not exist" in tool.members_problems(other)[0]


# --- the runs on a compressed calendar ------------------------------------------------


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[299]),
            "validation": (days[300], days[329]),
            "used": (days[330 - 1] + timedelta(days=1), days[329] + timedelta(days=30)),
        },
    )
    floors = {"exploration": 40, "validation": 20}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("date", days[250])}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(tool, "MEMBERS_SHA256", ex.file_sha256(tool.members_path(db)))
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    write_members(folder)
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "M1,M2") -> int:
    chosen = (
        []
        if hypotheses is None or "--coverage-only" in extra
        else ["--hypotheses", hypotheses]
    )
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "exploration",
                "--min-free-gb",
                "0",
                *chosen,
                *extra,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path, sha: str | None = None, url=URL) -> int:
    sha = sha if sha is not None else ex.file_sha256(report)
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "validation",
                "--min-free-gb",
                "0",
                "--exploration-report",
                str(report),
                "--exploration-sha256",
                sha,
                "--exploration-url",
                url,
            ]
        )  # fmt: skip
    )


@pytest.fixture
def explored(fixture_db, tmp_path, monkeypatch):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path, db)
    out = tmp_path / "exploration"
    assert explore(db, out) == 0
    return db, out


VOLATILE_LINES = (
    "explore.json 的 sha256",
    "- 耗時 ",
    "- 重現：",
    "- 副本：",
    "- 探索段報告：",
)


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        for key in tool.VOLATILE_KEYS:
            data.pop(key, None)
        data.get("copy", {}).pop("mtime", None)
        data.pop("members_sha256", None)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.suffix == ".md":
        return (
            "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith(VOLATILE_LINES)
                and not line.startswith("- 族群來源")
            )
            + "\n"
        )
    return text


def outputs(out: Path) -> dict[str, str]:
    return {
        path.relative_to(out).as_posix(): normalized(path)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and not path.relative_to(out).as_posix().startswith("raw/")
        and path.name != "ledger-entries.json"
    }


def check_golden(out: Path, name: str) -> None:
    folder = GOLDEN / name
    actual = outputs(out)
    if os.environ.get("MAINSTREAM_GOLDEN_UPDATE") == "1":
        shutil.rmtree(folder, ignore_errors=True)
        for relative, text in actual.items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    expected = {
        path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
    assert sorted(actual) == sorted(expected)
    for relative in expected:
        assert actual[relative] == expected[relative], relative


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_exploration_output_is_frozen(explored):
    _db, out = explored
    check_golden(out, "exploration")
    for name in REGISTERED:
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "groups.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "mainstream_research",
        "813",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (3, 2, 15)
    assert report["read_until"] == trading_days()[299].isoformat()
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [(e["hypothesis"], e["tool"], e["segment"]) for e in entries] == [
        ("M1", "mainstream_research", "exploration"),
        ("M2", "mainstream_research", "exploration"),
    ]


def test_m1_and_m2_pick_the_same_names(explored):
    _db, out = explored
    one = (out / "M1" / "picks.csv").read_text(encoding="utf-8")
    assert one == (out / "M2" / "picks.csv").read_text(encoding="utf-8")
    assert one.count("\n") > 40
    rows = (out / "M1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert not any(row.startswith(trading_days()[NO_TAIEX].isoformat()) for row in rows)


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="M2") == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert any("M2 already in" in line for line in refused)
    assert not (out.parent / "again").exists()


def test_the_exploration_ledger_of_another_tool_does_not_block(
    fixture_db, tmp_path, monkeypatch
):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path, db)
    ex.write_ledger(
        db.parent / ex.LEDGER_NAME,
        [{"hypothesis": "X1", "segment": "exploration", "version": 2}],
    )
    problems, names = ex.exploration_problems(
        db, "M1,M2", tool.HYPOTHESES, tool.VERSION
    )
    assert problems == [] and names == ["M1", "M2"]


def test_the_validation_runs_once_after_the_exploration(explored, tmp_path, capsys):
    """M1 marked passed in a report of this tool (its own sha256): the
    validation runs it once, writes the ledger first, and refuses a second."""

    db, out = explored
    data = read_json(out / "explore.json")
    data["hypotheses"]["M1"]["verdict"] = ex.EXPLORATION_PASSED
    data["hypotheses"]["M2"]["verdict"] = ex.EXPLORATION_FAILED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("M1", "mainstream_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["M1"]
    assert validation["read_until"] == trading_days()[329].isoformat()
    capsys.readouterr()
    assert validate(db, tmp_path / "validation-2", report) == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert any("the validation runs once" in line for line in refused)
    assert not (tmp_path / "validation-2").exists()


def test_the_validation_refuses_another_tools_report(explored, tmp_path, capsys):
    db, out = explored
    report = tmp_path / "other.json"
    data = read_json(out / "explore.json")
    data["design"] = "703"
    report.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert "the report is not an exploration report of this tool" in refused


def test_coverage_only_computes_no_return(fixture_db, tmp_path, monkeypatch):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path, db)
    out = tmp_path / "coverage"
    assert explore(db, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "return_240", "strength", "verdict"):
        assert word not in text
    years = body["coverage"]
    assert sum(row["taiex_missing"] for row in years.values()) == 1
    assert sum(row["days"] for row in years.values()) == 49
    assert not ex.read_ledger(db.parent / ex.LEDGER_NAME)
    check_golden(out, "coverage")


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "M1"]
        )  # fmt: skip


def test_a_wrong_member_table_is_refused_before_reading(
    fixture_db, tmp_path, monkeypatch, capsys
):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path, db)
    monkeypatch.setattr(tool, "MEMBERS_SHA256", "0" * 64)
    out = tmp_path / "x"
    capsys.readouterr()
    assert explore(db, out) == 2
    refused = json.loads(capsys.readouterr().out)["refused"]
    assert any("not the member table" in line for line in refused)
    assert not out.exists()
