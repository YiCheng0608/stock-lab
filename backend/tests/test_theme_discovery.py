"""新題材發現 (Issue #1018): clusters, AI proposals with verified evidence,
theme candidates that are never scored.

- AC-1: ``app.theme_clusters`` stores the date's clusters (date, thresholds,
  clusters, members, correlations) and a rerun of the date gives the same
  rows; the clustering equals the evaluation's ``cluster.py`` loop (every
  link recomputed from the pairs).
- AC-2: ``worker.theme_discovery`` with a fake ``claude -p`` answer and fake
  MOPS pages: the run records the model and prompt version, a member whose
  quote is not on its page is not written, an answer that does not verify
  writes nothing; no real AI is called.
- AC-3: a ``theme_candidate`` is never scored or ranked, and neither the
  today list's groups nor ``mainstream_v1`` reads it as a theme.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, inspect, select
from sqlalchemy.orm import Session, sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import mainstream
from app import migrations
from app.db import enable_sqlite_foreign_keys
from app.main import app as api_app
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import (
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    ThemeClusterMember,
    ThemeClusterRun,
    RawPayload,
    ThemeGroup,
)
from app.theme_clusters import (
    DEFAULT_CONFIG,
    THEME_CLUSTER_VERSION,
    ClusterConfig,
    Screened,
    ThemeClusterDataError,
    cluster,
    correlation,
    store_clusters,
)
from app.theme_table import (
    THEME_CANDIDATE_GROUP_TYPE,
    THEME_CANDIDATE_NAME_STATUS,
    ThemeTableError,
    write_theme_candidate,
)
from test_daily_schedule import Steps, runs
from worker import sources, theme_discovery
from worker.candidates import _group_inputs
from worker.news_llm import CliResult
from worker.theme_evidence import PageStore

REAL_STEP = schedule_runs._theme_discovery_step
SESSIONS = 45
INDEX_ID = 100


def weekdays(last: date, count: int) -> list[date]:
    out, day = [], last
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return out[::-1]


DAYS = weekdays(date(2025, 5, 9), SESSIONS)
T = DAYS[-1]
# Two themes moving together, a third pair, a lone riser and stocks the screen
# drops for one reason each.
GROUP_A = (1, 2, 3, 4)
GROUP_B = (5, 6, 7)
PAIR = (13, 14)
LONE = 8
THIN = 9  # under 1,000 lots a day
FLAT_VOLUME = 10  # no rise in trading value
GAP = 11  # no bar on one session of the window
ETF = 12
STOCKS = (*GROUP_A, *GROUP_B, LONE, THIN, FLAT_VOLUME, GAP, ETF, *PAIR)
SCREENED = {*GROUP_A, *GROUP_B, LONE, *PAIR}


def noise(key: str, t: int) -> float:
    return hashlib.sha256(f"{key}:{t}".encode()).digest()[0] / 255.0 - 0.5


def _factor(i: int) -> str:
    if i in GROUP_A:
        return "A"
    if i in GROUP_B:
        return "B"
    if i in PAIR:
        return "P"
    return f"own{i}"


def _bars(i: int) -> list[dict]:
    level, rows = 50.0 + i, []
    for t, day in enumerate(DAYS):
        drift = 0.012 if i == LONE else 0.009
        level *= 1 + drift + 0.03 * noise(_factor(i), t) + 0.004 * noise(f"s{i}", t)
        lots = 700 if i == THIN else 2000
        if t >= SESSIONS - 5 and i != FLAT_VOLUME:
            lots *= 1.6
        if i == GAP and t == SESSIONS - 10:
            continue
        volume = lots * 1000
        rows.append(
            {
                "instrument_id": i,
                "trading_date": day,
                "open": level,
                "high": level,
                "low": level,
                "close": round(level, 4),
                "adj_close": round(level, 4),
                "volume": volume,
                "turnover": round(level * volume, 2),
                "source": "test",
            }
        )
    return rows


def _index_bars() -> list[dict]:
    level, rows = 20000.0, []
    for t, day in enumerate(DAYS):
        level *= 1 + 0.004 * noise("index", t)
        rows.append(
            {
                "instrument_id": INDEX_ID,
                "trading_date": day,
                "open": level,
                "high": level,
                "low": level,
                "close": round(level, 2),
                "adj_close": round(level, 2),
                "volume": 0,
                "source": "twse_index",
            }
        )
    return rows


def _instruments() -> list[dict]:
    rows = [
        {
            "id": i,
            "market": "TW",
            "exchange": "TWSE" if i % 2 else "TPEx",
            "symbol": f"{1000 + i}",
            "name": f"公司{i}",
            "instrument_type": "etf" if i == ETF else "stock",
            "status": "active",
        }
        for i in STOCKS
    ]
    rows.append(
        {
            "id": INDEX_ID,
            "market": "TW",
            "exchange": "TWSE",
            "symbol": "TAIEX",
            "name": "加權指數",
            "instrument_type": "index",
            "status": "active",
        }
    )
    return rows


@pytest.fixture
def make(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'discovery.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    with Session(engine) as db:
        db.execute(insert(Instrument), _instruments())
        db.execute(
            insert(MarketBar), [row for i in STOCKS for row in _bars(i)] + _index_bars()
        )
        db.commit()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


def _symbol(i: int) -> str:
    return f"{'TWSE' if i % 2 else 'TPEx'}:{1000 + i}"


def _rows(factory, day=T):
    with factory() as db:
        run = db.scalar(
            select(ThemeClusterRun).where(ThemeClusterRun.trading_date == day)
        )
        members = db.scalars(
            select(ThemeClusterMember)
            .where(ThemeClusterMember.theme_cluster_run_id == run.id)
            .order_by(ThemeClusterMember.cluster_no, ThemeClusterMember.instrument_id)
        ).all()
        shape = [
            (
                m.cluster_no,
                m.instrument_id,
                m.cluster_size,
                m.cluster_mean_corr,
                m.member_mean_corr,
                m.excess_return_20d,
                m.amount_ratio_5_20,
                m.average_lots_20d,
                m.trading_date,
                m.version,
            )
            for m in members
        ]
        return run, shape


# --- AC-1: the clusters ---------------------------------------------------


def test_the_day_is_stored_with_its_thresholds_clusters_and_correlations(make):
    with make() as db:
        run = store_clusters(db, T)
    run, shape = _rows(make)
    assert (run.trading_date, run.version, run.status) == (
        T,
        THEME_CLUSTER_VERSION,
        "computed",
    )
    assert run.screened_count == len(SCREENED)
    assert run.cluster_count == 2
    assert run.config_json == {
        "version": THEME_CLUSTER_VERSION,
        "index": "TWSE:TAIEX",
        "history_days": 41,
        "liquidity_days": 20,
        "min_average_lots": 1000.0,
        "excess_days": 20,
        "min_excess_return": 0.10,
        "amount_recent_days": 5,
        "amount_base_days": 20,
        "min_amount_ratio": 1.3,
        "correlation_days": 40,
        "link_threshold": 0.45,
        "min_cluster_size": 3,
    }
    clusters: dict[int, set[int]] = {}
    for (
        number,
        instrument_id,
        size,
        mean_corr,
        member_corr,
        excess,
        ratio,
        lots,
        *_,
    ) in shape:
        clusters.setdefault(number, set()).add(instrument_id)
        assert mean_corr >= 0.45 and member_corr >= 0.45
        assert excess >= 0.10 and ratio >= 1.3 and lots >= 1000
        assert size == len([row for row in shape if row[0] == number])
    # The pair is screened but too small; the lone riser joins nothing.
    assert clusters == {1: set(GROUP_A), 2: set(GROUP_B)}


def test_a_rerun_of_the_day_gives_the_same_rows(make):
    with make() as db:
        store_clusters(db, T)
    _run, first = _rows(make)
    with make() as db:
        store_clusters(db, T)
    _run, second = _rows(make)
    assert second == first
    with make() as db:
        assert db.scalar(select(func.count()).select_from(ThemeClusterRun)) == 1
        assert db.scalar(select(func.count()).select_from(ThemeClusterMember)) == len(
            first
        )
    # Another date is its own run, the first one is kept.
    with make() as db:
        store_clusters(db, DAYS[-2])
        assert db.scalar(select(func.count()).select_from(ThemeClusterRun)) == 2
    assert _rows(make)[1] == first


def test_the_thresholds_are_settings(make):
    config = ClusterConfig(min_cluster_size=2)
    with make() as db:
        run = store_clusters(db, T, config)
    run, shape = _rows(make)
    assert run.config_json["min_cluster_size"] == 2
    assert {row[1] for row in shape if row[0] == 3} == set(PAIR)
    strict = ClusterConfig(min_excess_return=5.0)
    with make() as db:
        run = store_clusters(db, T, strict)
    assert (run.status, run.screened_count, run.cluster_count) == ("zero", 0, 0)


def test_a_day_without_a_taiex_bar_is_not_clustered(make, capsys):
    saturday = T + timedelta(days=1)
    with make() as db, pytest.raises(ThemeClusterDataError):
        store_clusters(db, saturday)
    result = theme_discovery.run_theme_discovery(saturday, ai=False)
    assert result["status"] == "failed" and "TAIEX" in result["error"]
    assert "warning: theme_discovery" in capsys.readouterr().err


def _reference_clusters(items: list[Screened], threshold: float) -> list[set[int]]:
    """The evaluation's cluster.py loop: every link from the pairs again."""

    ids = [item.instrument_id for item in items]
    series = {item.instrument_id: item.excess_returns for item in items}
    pairs = {
        (a, b): correlation(series[a], series[b]) for a in ids for b in ids if a < b
    }
    groups = [{i} for i in ids]

    def link(x, y):
        return sum(pairs[(min(a, b), max(a, b))] for a in x for b in y) / (
            len(x) * len(y)
        )

    while True:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                value = link(groups[i], groups[j])
                if value >= threshold and (not best or value > best[0]):
                    best = (value, i, j)
        if not best:
            break
        _value, i, j = best
        groups[i] |= groups[j]
        groups.pop(j)
    return sorted((g for g in groups if len(g) >= 3), key=lambda g: (-len(g), min(g)))


def test_the_clusters_equal_the_evaluation_loop():
    rng = random.Random(1018)
    factors = [[rng.gauss(0, 1) for _ in range(40)] for _ in range(6)]
    items = []
    for i in range(60):
        weight = rng.random()
        factor = factors[i % 6]
        items.append(
            Screened(
                instrument_id=i,
                excess_return_20d=0.2,
                amount_ratio_5_20=1.5,
                average_lots_20d=2000.0,
                excess_returns=tuple(
                    weight * f + rng.gauss(0, 1) * (1 - weight) for f in factor
                ),
            )
        )
    found = [set(c.instrument_ids) for c in cluster(items, DEFAULT_CONFIG)]
    assert found == _reference_clusters(items, DEFAULT_CONFIG.link_threshold)
    assert len(found) >= 3


# --- AC-2: the AI proposal --------------------------------------------------

KEYWORD = "矽晶圓"


def _page(business: str) -> str:
    return (
        "<html><body><table><tr><th>公司名稱</th><td>某公司</td></tr>"
        f"<tr><th>主要經營業務</th><td>{business}</td></tr>"
        "<tr><th>公司成立日期</th><td>1990/01/01</td></tr></table></body></html>"
    )


BUSINESS = {i: f"1.{KEYWORD}之製造及銷售。2.其他電子零組件{i}。" for i in GROUP_A}
BUSINESS.update({i: f"1.被動元件之製造{i}。" for i in GROUP_B})


def _pages(fetched: list[str]) -> PageStore:
    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        symbol = request.url.params["co_id"]
        instrument_id = int(symbol) - 1000
        if instrument_id not in BUSINESS:
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=_page(BUSINESS[instrument_id]).encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    return PageStore(
        delay=0, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _answer(members, *, is_theme=True, name="矽晶圓", candidate_id="silicon-wafer"):
    return {
        "is_theme": is_theme,
        "reason": "成員主要經營業務都是矽晶圓",
        "id": candidate_id if is_theme else "",
        "name": name if is_theme else "",
        "description": "矽晶圓材料與製造" if is_theme else "",
        "keywords": [KEYWORD] if is_theme else [],
        "members": members,
    }


def _member(i: int, quote: str | None = None) -> dict:
    return {
        "symbol": _symbol(i),
        "relation": "core_business",
        "relevance": "high",
        "quote": quote if quote is not None else f"{KEYWORD}之製造及銷售",
    }


class FakeClaude:
    """Scripted ``claude -p`` answers; records every prompt."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.argv: list[list[str]] = []

    def __call__(self, prompt, argv):
        self.prompts.append(prompt)
        self.argv.append(list(argv))
        answer = self.answers.pop(0)
        if isinstance(answer, CliResult):
            return answer
        envelope = {
            "type": "result",
            "is_error": False,
            "structured_output": answer,
            "modelUsage": {
                "claude-sonnet-test": {"inputTokens": 100, "outputTokens": 20}
            },
        }
        return CliResult(returncode=0, stdout=json.dumps(envelope), stderr="")


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(theme_discovery, "preflight", lambda: (["claude"], None))


def _discover(make, claude, fetched=None, **kwargs):
    with make() as db:
        return theme_discovery.discover(
            db,
            T,
            runner=claude,
            pages=_pages(fetched if fetched is not None else []),
            run_date=T,
            **kwargs,
        )


def _candidates(make):
    with make() as db:
        groups = db.scalars(
            select(ThemeGroup).where(
                ThemeGroup.group_type == THEME_CANDIDATE_GROUP_TYPE
            )
        ).all()
        members = db.scalars(
            select(GroupMembership).order_by(GroupMembership.instrument_id)
        ).all()
        return groups, members


def test_the_prompt_version_is_pinned():
    assert theme_discovery.prompt_sha256() == theme_discovery.PROMPT_SHA256
    assert theme_discovery.PROMPT_PATH.name == "theme_discovery_v1.md"


def test_a_verified_proposal_is_written_as_an_inactive_candidate(make, cli):
    # Member 4's quote is not on its page: it is not written.
    claude = FakeClaude(
        _answer([_member(1), _member(2), _member(3), _member(4, "矽晶圓之代工")]),
        _answer([], is_theme=False),
    )
    fetched: list[str] = []
    result = _discover(make, claude, fetched)
    assert result["ai"]["status"] == "success" and result["ai"]["calls"] == 2
    first = result["ai"]["proposals"][0]
    assert first["status"] == "written"
    assert first["verified"] == [_symbol(i) for i in (1, 2, 3)]
    assert first["failed_members"] == [
        {
            "symbol": _symbol(4),
            "errors": ["evidence[0].quote: not found in 主要經營業務"],
        }
    ]
    assert result["ai"]["proposals"][1]["status"] == "not_theme"
    # The model gets the MOPS 主要經營業務 text of each member and no tools.
    payload = json.loads(
        claude.prompts[0].split("<cluster>\n")[1].split("</cluster>")[0]
    )
    business = {m["symbol"]: m["main_business"] for m in payload["members"]}
    assert business[_symbol(1)] == f"1.{KEYWORD}之製造及銷售。2.其他電子零組件1。"
    assert claude.argv[0][claude.argv[0].index("--tools") + 1] == ""
    assert claude.argv[0][claude.argv[0].index("--model") + 1] == theme_discovery.MODEL
    assert all("t05st03" in url for url in fetched)
    groups, members = _candidates(make)
    assert [(g.id, g.active, g.name_status) for g in groups] == [
        ("candidate-silicon-wafer", False, THEME_CANDIDATE_NAME_STATUS)
    ]
    group = groups[0]
    assert (group.display_name_zh, group.display_category) == ("矽晶圓", "候選題材")
    source = json.loads(group.source)
    assert source["keywords"] == [KEYWORD]
    assert source["prompt_version"] == "theme_discovery_v1"
    assert source["model"] == "claude-sonnet-test"
    assert [(m.instrument_id, m.role, m.valid_from, m.valid_to) for m in members] == [
        (i, "candidate", T, None) for i in (1, 2, 3)
    ]
    evidence = json.loads(members[0].source)
    assert evidence["quote"] == f"{KEYWORD}之製造及銷售"
    # No URL in the 500-character source: it is rebuilt from the symbol.
    assert evidence["evidence"] == "mops_t05st03" and "url" not in evidence
    assert "co_id=1001" in theme_discovery.mops_profile_url("1001")
    assert len(members[0].source) <= 500
    assert evidence["model"] == "claude-sonnet-test"
    assert evidence["prompt_version"] == "theme_discovery_v1"
    with make() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == "theme_discovery")
        )
        meta = run.metadata_json
    assert run.status == "success" and run.records == 3
    assert meta["prompt_version"] == "theme_discovery_v1"
    assert meta["prompt_sha256"] == theme_discovery.PROMPT_SHA256
    assert meta["model"] == theme_discovery.MODEL
    assert meta["calls"] == 2
    assert meta["proposals"][0]["model"] == "claude-sonnet-test"
    assert meta["usage_total"]["input_tokens"] == 200


@pytest.mark.parametrize(
    "members",
    [
        # Two of three verify: fewer than MIN_VERIFIED_MEMBERS.
        [_member(1), _member(2), _member(3, "被動元件")],
        # The quote is on the page but has no theme keyword.
        [_member(i, "其他電子零組件") for i in (1, 2, 3)],
    ],
)
def test_a_proposal_that_does_not_verify_writes_nothing(make, cli, members):
    claude = FakeClaude(_answer(members), _answer([], is_theme=False))
    result = _discover(make, claude)
    assert result["ai"]["proposals"][0]["status"] == "rejected"
    assert result["ai"]["proposals"][0]["reason"] == "too_few_verified_members"
    assert _candidates(make) == ([], [])


@pytest.mark.parametrize(
    "answer",
    [
        CliResult(returncode=0, stdout="not json", stderr=""),
        # A member outside the cluster.
        _answer([_member(1), _member(2), _member(5)]),
        # The name may not contain ETF.
        _answer([_member(i) for i in (1, 2, 3)], name="矽晶圓ETF"),
        _answer([_member(i) for i in (1, 2, 3)], candidate_id="Silicon Wafer"),
        # A one-character keyword would match almost any 主要經營業務.
        dict(_answer([_member(i) for i in (1, 2, 3)]), keywords=["矽"]),
    ],
)
def test_an_invalid_answer_writes_nothing(make, cli, answer):
    claude = FakeClaude(answer, _answer([], is_theme=False))
    result = _discover(make, claude)
    assert result["ai"]["proposals"][0]["status"] == "failed"
    assert _candidates(make) == ([], [])
    with make() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == "theme_discovery")
        )
    assert run.status == "failed" and "cluster 1" in run.error


def test_a_proposal_named_like_an_existing_theme_is_rejected(make, cli):
    with make() as db:
        db.add(
            ThemeGroup(
                id="theme-wafer",
                name="矽晶圓",
                group_type="theme",
                active=True,
                display_name_zh="矽晶圓",
                name_status="verified",
            )
        )
        db.commit()
    claude = FakeClaude(
        _answer([_member(i) for i in (1, 2, 3)]), _answer([], is_theme=False)
    )
    result = _discover(make, claude)
    assert result["ai"]["proposals"][0]["reason"] == "existing_theme"
    assert _candidates(make)[0] == []


def test_known_clusters_are_not_sent_and_calls_are_capped_per_day(make, cli):
    with make() as db:
        db.add(ThemeGroup(id="theme-b", name="B", group_type="theme", active=True))
        db.flush()
        for i in GROUP_B[:2]:
            db.add(
                GroupMembership(
                    group_id="theme-b", instrument_id=i, valid_from=DAYS[0], source="t"
                )
            )
        db.commit()
    claude = FakeClaude(_answer([_member(i) for i in (1, 2, 3, 4)]))
    result = _discover(make, claude)
    # Two of the three in cluster 2 are in one theme: not sent.
    assert [d["selected"] for d in result["selection"]] == [True, False]
    assert result["selection"][1]["reason"] == "known_theme"
    assert len(claude.prompts) == 1
    # Rerun: cluster 1 is now a candidate, so nothing is sent again.
    again = FakeClaude()
    result = _discover(make, again)
    assert result["selection"][0]["reason"] == "known_theme"
    assert again.prompts == [] and result["ai"]["calls"] == 0
    # The daily limit counts the calls of every run of the day.
    with make() as db:
        for group in db.scalars(select(GroupMembership)).all():
            db.delete(group)
        db.commit()
    limited = FakeClaude(_answer([], is_theme=False))
    result = _discover(make, limited, call_limit=2)
    assert len(limited.prompts) == 1
    assert [s["reason"] for s in result["ai"]["skipped_clusters"]] == [
        "daily_call_limit"
    ]


def test_without_the_cli_the_clusters_are_kept_and_nothing_is_written(
    make, monkeypatch
):
    monkeypatch.setattr(
        theme_discovery, "preflight", lambda: (None, "cli_not_found: claude")
    )
    result = theme_discovery.run_theme_discovery(T)
    assert result["status"] == "partial" and result["records"] == 2
    assert result["ai"]["reason"] == "cli_not_found: claude"
    assert _candidates(make) == ([], [])


def test_no_ai_replays_the_clusters_only(make, monkeypatch):
    def refuse():
        raise AssertionError("no AI on a replay")

    monkeypatch.setattr(theme_discovery, "preflight", refuse)
    result = theme_discovery.run_theme_discovery(T, ai=False)
    assert result["status"] == "success" and result["ai"]["reason"] == "ai_disabled"
    assert [c["size"] for c in result["clusters"]] == [4, 3]


def test_the_daily_runs_the_step_without_changing_the_run(make, monkeypatch):
    monkeypatch.setattr(
        theme_discovery, "preflight", lambda: (None, "cli_not_found: claude")
    )
    steps = Steps(monkeypatch)
    monkeypatch.setattr(schedule_runs, "_theme_discovery_step", REAL_STEP)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert steps.calls[-2:] == ["candidate_notes", "period_backfill"]
    rows, by_run = runs(make)
    step = by_run[rows[0].id]["theme_discovery"]
    assert (step.status, step.records, step.sequence) == ("partial", 2, 13)
    assert rows[0].status == "success" and rows[0].error is None
    assert "theme_discovery" in schedule_runs.NON_BLOCKING_STEPS


def test_a_failing_step_stays_on_its_row(make, monkeypatch):
    Steps(monkeypatch, theme_discovery={"status": "failed", "error": "fixture"})
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    rows, by_run = runs(make)
    assert by_run[rows[0].id]["theme_discovery"].status == "failed"
    assert rows[0].status == "success"


def test_the_writer_never_backdates_or_takes_another_groups_id(make):
    provenance = {"model": "m", "prompt_version": "theme_discovery_v1"}
    member = {
        "instrument_id": 1,
        "relation": "core_business",
        "relevance": "high",
        "url": "https://example.com/1",
        "quote": "q",
    }
    with make() as db:
        kwargs = dict(
            candidate_id="x",
            name="X",
            description="d",
            keywords=["x"],
            provenance=provenance,
        )
        write_theme_candidate(db, members=[member], valid_from=T, **kwargs)
        later = write_theme_candidate(
            db,
            members=[member, dict(member, instrument_id=2)],
            valid_from=T + timedelta(days=3),
            **kwargs,
        )
        assert later == {"group_id": "candidate-x", "created": False, "added": [2]}
        db.add(ThemeGroup(id="candidate-y", name="Y", group_type="theme"))
        db.flush()
        with pytest.raises(ThemeTableError):
            write_theme_candidate(
                db, members=[member], valid_from=T, **dict(kwargs, candidate_id="y")
            )
        rows = db.scalars(
            select(GroupMembership).where(GroupMembership.group_id == "candidate-x")
        ).all()
        assert sorted((r.instrument_id, r.valid_from) for r in rows) == [
            (1, T),
            (2, T + timedelta(days=3)),
        ]


# --- AC-3: never scored, ranked or a theme source ------------------------------


def test_a_candidate_is_never_scored_ranked_or_read_as_a_theme(tmp_path):
    from test_themes import SCORE_DATE, _board_fixture, _scores

    engine = create_engine(f"sqlite:///{(tmp_path / 'board.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        stocks, dates = _board_fixture(db)
        written = write_theme_candidate(
            db,
            candidate_id="fresh",
            name="新題材",
            description="d",
            keywords=["k"],
            members=[
                {
                    "instrument_id": stock.id,
                    "relation": "core_business",
                    "relevance": "high",
                    "url": "https://example.com",
                    "quote": "k",
                }
                for stock in stocks[0:5]
            ],
            valid_from=dates[0],
            provenance={"model": "m", "prompt_version": "theme_discovery_v1"},
        )
        group_id = written["group_id"]
        # Even when activated by mistake it is not scored or ranked.
        db.get(ThemeGroup, group_id).active = True
        pipeline._calculate_group_scores(db, SCORE_DATE)
        db.flush()
        scores = _scores(db)
        assert group_id not in scores
        assert "theme-top" in scores  # the board itself was computed
        assert pipeline._group_board(db.get(ThemeGroup, group_id)) is None
        # The today list's group input (a stock's themes) skips it.
        groups, _summary = _group_inputs(db, SCORE_DATE)
        assert all(
            item["group_id"] != group_id for items in groups.values() for item in items
        )
        # Nor does mainstream_v1 read it as a group.
        assert group_id not in mainstream.group_members(db, SCORE_DATE)
        # Nor does the strategy group confirmation.
        for stock in stocks[0:5]:
            best = pipeline._best_group_for_signal(db, stock.id, SCORE_DATE)
            assert best is None or best.group_id != group_id
    engine.dispose()


def test_a_refused_write_keeps_the_calls_raw(make, cli):
    # The candidate id is taken by a group of another type: the writer refuses.
    with make() as db:
        db.add(ThemeGroup(id="candidate-silicon-wafer", name="其他", group_type="theme"))
        db.commit()
    claude = FakeClaude(
        _answer([_member(i) for i in (1, 2, 3)]), _answer([], is_theme=False)
    )
    result = _discover(make, claude)
    with make() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == "theme_discovery")
        )
        outcome = run.metadata_json["proposals"][0]
        assert (outcome["status"], outcome["reason"]) == ("rejected", "write_refused")
        raw = db.get(RawPayload, outcome["raw_payload_id"])
        assert raw is not None and raw.source == "theme_discovery"
        # The second cluster's raw is its own row, not the first one's id again.
        second = run.metadata_json["proposals"][1]["raw_payload_id"]
        assert second != outcome["raw_payload_id"]
        assert db.scalar(select(func.count()).select_from(RawPayload)) == 2
    assert result["ai"]["proposals"][0]["reason"] == "write_refused"
    assert _candidates(make)[1] == []


def test_a_candidate_is_not_a_group_on_the_stock_page(make, monkeypatch):
    with make() as db:
        write_theme_candidate(
            db,
            candidate_id="fresh",
            name="新題材",
            description="d",
            keywords=["kw"],
            members=[
                {
                    "instrument_id": 1,
                    "relation": "core_business",
                    "relevance": "high",
                    "evidence": "mops_t05st03",
                    "quote": "kw",
                }
            ],
            valid_from=DAYS[0],
            provenance={"model": "m", "prompt_version": "theme_discovery_v1"},
        )
        db.add(ThemeGroup(id="ind-x", name="產業X", group_type="official_industry"))
        db.flush()
        db.add(
            GroupMembership(
                group_id="ind-x", instrument_id=1, valid_from=DAYS[0], source="t"
            )
        )
        db.commit()

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    api_app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(api_app, base_url="http://127.0.0.1:8000") as client:
            detail = client.get(f"/api/stocks/TWSE/{1001}").json()
    finally:
        api_app.dependency_overrides.pop(api_module.get_db, None)
    ids = [group.get("group_id") or group.get("id") for group in detail["groups"]]
    assert "ind-x" in ids
    assert "candidate-fresh" not in ids


def test_the_cluster_config_needs_a_pair():
    with pytest.raises(ValueError):
        ClusterConfig(min_cluster_size=1)


def _alembic_config(engine):
    from alembic.config import Config

    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    return config


CLUSTER_TABLES = {"theme_cluster_runs", "theme_cluster_members"}
CLUSTER_INDEXES = {
    "ix_theme_cluster_runs_trading_date",
    "ix_theme_cluster_members_theme_cluster_run_id",
    "ix_theme_cluster_members_trading_date",
    "ix_theme_cluster_members_instrument_id",
}


def _schema(engine):
    names = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        version = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        fk = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    return names, indexes, version, fk


def test_the_migration_goes_down_and_up_again(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command

    revision = next(name for name in REVISIONS if name.endswith("_theme_clusters"))
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    engine = create_engine(f"sqlite:///{(tmp_path / 'down.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, revision)
        with Session(engine) as db:
            db.execute(insert(Instrument), _instruments()[:1])
            db.add(
                ThemeClusterRun(
                    id=1,
                    trading_date=T,
                    version=THEME_CLUSTER_VERSION,
                    status="computed",
                    screened_count=3,
                    cluster_count=1,
                    config_json={},
                )
            )
            db.flush()
            db.add(
                ThemeClusterMember(
                    theme_cluster_run_id=1,
                    trading_date=T,
                    instrument_id=1,
                    version=THEME_CLUSTER_VERSION,
                    cluster_no=1,
                    cluster_size=3,
                    cluster_mean_corr=0.6,
                    member_mean_corr=0.6,
                    excess_return_20d=0.2,
                    amount_ratio_5_20=1.5,
                    average_lots_20d=2000.0,
                )
            )
            db.commit()
        names, indexes, version, _fk = _schema(engine)
        assert CLUSTER_TABLES <= names and CLUSTER_INDEXES <= indexes
        assert version == [(revision,)]

        command.downgrade(config, previous)
        names, indexes, version, fk = _schema(engine)
        assert not CLUSTER_TABLES & names and not CLUSTER_INDEXES & indexes
        assert version == [(previous,)] and fk == []

        command.upgrade(config, revision)
        names, indexes, version, fk = _schema(engine)
        assert CLUSTER_TABLES <= names and CLUSTER_INDEXES <= indexes
        assert version == [(revision,)] and fk == []
    finally:
        engine.dispose()
