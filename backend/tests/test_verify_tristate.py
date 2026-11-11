"""Issue #251: page_checks on the 2026-10-24 real-data run (pr-assets/245/20261024-1945).

That run reported 21 of 38 checks as 失敗 although 18 of them could not run: a
holiday's skipped official run left ``dashboard.as_of`` and the board date null
while the DB had 2026-10-22 data.  It also passed checks it should not have: an
empty group board (G3), the empty 關注標的 next to 20 candidates (T9), and T6's
U+00A0 failure hid under the #233 entry of ``KNOWN_FAILURES``.  The stocks page
was 9 times 無法判定 because E/S came only from the empty board.  Each test
replays one of these with the run's values.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess

import pytest
from test_verify_checks import FakeRun, page_checks

DAY = "2026-10-22"
FACTS = {
    "market_latest_trading_date": DAY,
    "group_scores_latest_trading_date": DAY,
    "candidate_run_latest_trading_date": DAY,
    "candidate_count_latest": 20,
}
NO_RUN = "尚無成功的官方資料擷取，無法提供族群榜。"
EMPTY_BOARD = {
    "meta": {
        "trading_date": None,
        "total": 0,
        "empty_reason": "no_official_run",
        "empty_message": NO_RUN,
    },
    "items": [],
}
ACTIONS_EMPTY = "目前沒有資料完整的可執行條件；請查看缺少資料與補齊優先級"
# as_of null: the latest official run was the 10/23 holiday's skipped one (#249).
DASHBOARD = {
    "as_of": None,
    "market": {"source_label": "TWSE／TPEx 官方資料"},
    "groups": [{"rank": 1, "trading_date": DAY}, {"rank": None, "trading_date": None}],
    "news": [],
    "actions": [],
    "candidates": [],
    "empty_states": {"actions": ACTIONS_EMPTY},
}
CANDIDATES = {
    "status": "success",
    "trading_date": DAY,
    "candidate_count": 20,
    "items": [
        {"rank": n, "instrument": {"exchange": "TWSE", "symbol": f"23{n:02d}"}}
        for n in range(1, 21)
    ],
}
TODAY_PAGE = (
    "資料日期未提供\n今日\n資料截至\n資料日期未提供\n"
    f"熱門族群\n產業榜\n資料日期未提供\n{NO_RUN}\n"
    "今日名單\n資料 2026/10/22\n20 檔\n"
)


def _run(tmp_path, payloads=None, pages=None, facts=None):
    base = {
        "dashboard": DASHBOARD,
        "dashboard?include=groups": DASHBOARD,
        "themes?board=industry&limit=5": EMPTY_BOARD,
        "themes?board=industry&limit=100": EMPTY_BOARD,
        "candidates": CANDIDATES,
    }
    return FakeRun(
        tmp_path,
        {**base, **(payloads or {})},
        {"today-1280": TODAY_PAGE, **(pages or {})},
        {**FACTS, **(facts or {})},
    )


def _only(monkeypatch, page, *codes):
    checks = {code: page_checks.CHECKS[page][code] for code in codes}
    monkeypatch.setitem(page_checks.CHECKS, page, checks)


def _statuses(results):
    return {r.label: r.status for r in results}


# ---- three states and upstream ----


def test_a_missing_date_fails_once_and_its_users_are_undetermined(
    tmp_path, monkeypatch
):
    _only(monkeypatch, "today", "T2", "T3", "T4", "T5")
    results = page_checks.run_page(_run(tmp_path), "today", [])
    # Before #251: T2～T5 all 失敗 with 「無法判定：dashboard.json 沒有 as_of」 etc.
    assert _statuses(results) == {
        "T2": "失敗",
        "T3": "無法判定",
        "T4": "失敗",
        "T5": "無法判定",
    }
    t2, t3, t4, t5 = results
    assert "DB market_bars 最新 2026-10-22" in t2.detail
    assert "DB group_daily_scores 最新 2026-10-22" in t4.detail
    assert t3.detail.startswith("無法判定（上游 T2）") and t3.upstream == "T2"
    assert t5.detail.startswith("無法判定（上游 T4）") and t5.upstream == "T4"
    assert [r.code for r in results if r.failed] == ["T2", "T4"]


def test_a_page_whose_checks_could_not_run_is_undetermined(tmp_path, monkeypatch):
    _only(monkeypatch, "themes", "G5", "G6", "G7")
    results = page_checks.run_page(_run(tmp_path), "themes", [])
    assert _statuses(results) == dict.fromkeys(("G5", "G6", "G7"), "無法判定")
    assert all(r.detail.startswith("無法判定（上游 T5）") for r in results)
    assert not any(r.failed for r in results)
    summary = page_checks.summary_markdown(results, ["themes"], "## head")
    assert "### 族群 `/themes`：無法判定" in summary


def test_the_upstream_of_a_downstream_check_is_the_root(tmp_path, monkeypatch):
    # T5 waits on T4, so G5 using T names T4, where the failure is counted.
    _only(monkeypatch, "today", "T4", "T5")
    run = _run(tmp_path)
    page_checks.run_page(run, "today", [])
    _only(monkeypatch, "themes", "G5")
    (g5,) = page_checks.run_page(run, "themes", [])
    assert g5.status == "無法判定" and g5.upstream == "T4"


def test_a_failure_after_a_failed_check_of_the_same_rows_is_undetermined(
    tmp_path, monkeypatch
):
    # T7 and T8 count the same 來源 rows: one missing row is one failure.
    payloads = {
        "candidates": {
            **CANDIDATES,
            "candidate_count": 1,
            "items": [{"rank": 1, "instrument": {"symbol": "2301"}, "components": {}}],
        }
    }
    # The row is there (#276 table) but its detail lost the 來源 line.
    pages = {"today-1280": "今日名單\n資料 2026/10/22\n1 檔\n#1 2301 光寶科\n"}
    _only(monkeypatch, "today", "T7", "T8")
    t7, t8 = page_checks.run_page(_run(tmp_path, payloads, pages), "today", [])
    assert (t7.status, t8.status) == ("失敗", "無法判定")
    assert t8.detail.startswith("無法判定（上游 T7）：`來源：` 行 0，items 1")


# ---- KNOWN_FAILURES matches the message ----


def _t12_run(tmp_path):
    # The home page lost its hot groups card: a failure other than the registered one.
    return _run(
        tmp_path,
        {"dashboard": DASHBOARD},
        {"today-1280": "今日名單\n資料 2026/10/22\n"},
    )


def test_a_different_failure_of_a_known_check_fails(tmp_path, monkeypatch):
    issue = "https://github.com/YiCheng0608/stock-lab/issues/233"
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("today", "T12"),
        page_checks.Known(issue, "首頁仍有整行 `重點新聞`", "2026-11-20"),
    )
    _only(monkeypatch, "today", "T12")
    (t12,) = page_checks.run_page(_t12_run(tmp_path), "today", [])
    # Before #251 this was 失敗（已知） and did not fail the run.
    assert (t12.status, t12.failed, t12.known) == ("失敗", True, None)
    assert "缺整行 `熱門族群`" in t12.detail
    assert "不是已知失敗" in t12.detail and issue in t12.detail


def test_the_known_failure_itself_stays_known(tmp_path, monkeypatch):
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("today", "T12"),
        page_checks.Known("#233", "缺整行 `熱門族群`", "2026-11-20"),
    )
    _only(monkeypatch, "today", "T12")
    (t12,) = page_checks.run_page(_t12_run(tmp_path), "today", [])
    assert (t12.status, t12.failed, t12.known) == ("失敗（已知）", False, "#233")


# ---- an empty state is checked against the DB and the other APIs ----


def test_an_empty_board_fails_when_the_db_has_scores(tmp_path):
    board = {**EMPTY_BOARD, "meta": {**EMPTY_BOARD["meta"], "trading_date": DAY}}
    run = _run(
        tmp_path,
        {"themes?board=industry&limit=100": board},
        {
            "themes-1280": f"產業榜 · 共 0 個族群\n資料 2026/10/22\n{NO_RUN}\n",
            "themes-390": f"{NO_RUN}\n",
        },
    )
    # Before #251 G3 passed: 「items 空，顯示 `尚無成功的官方資料擷取…`」.
    with pytest.raises(page_checks.Fail) as error:
        page_checks.g3(run)
    assert "DB group_daily_scores 2026-10-22 有名次" in str(error.value)
    assert "dashboard.groups 有 1 個 2026-10-22 有名次的族群" in str(error.value)


def test_an_empty_board_passes_when_nothing_has_scores(tmp_path):
    run = _run(
        tmp_path,
        {"dashboard?include=groups": {**DASHBOARD, "groups": []}},
        {
            "themes-1280": f"產業榜 · 共 0 個族群\n{NO_RUN}\n",
            "themes-390": f"{NO_RUN}\n",
        },
        {"group_scores_latest_trading_date": None},
    )
    assert NO_RUN in page_checks.g3(run)


def test_the_home_page_keeps_one_list(tmp_path):
    # #493: 關注標的 moved to 我的追蹤; the home page passes without it.
    assert "首頁沒有 `關注標的`" in page_checks.t9(_run(tmp_path))


@pytest.mark.parametrize(
    "line", ["關注標的", "查看個股詳情 →", "查看行動中心 →", "明日候選"]
)
def test_the_home_page_fails_when_the_old_sections_come_back(tmp_path, line):
    # The pre-#493 home page: a 關注標的 grid of 查看個股詳情 → cards and a 明日候選 title.
    run = _run(tmp_path, {}, {"today-1280": TODAY_PAGE + f"{line}\n{ACTIONS_EMPTY}\n"})
    with pytest.raises(page_checks.Fail, match=f"首頁仍有整行 `{line}`"):
        page_checks.t9(run)


def test_zero_candidates_fail_when_the_db_has_them(tmp_path):
    payloads = {"candidates": {**CANDIDATES, "candidate_count": 0, "items": []}}
    run = _run(tmp_path, payloads, {"today-1280": "今日名單\n當日零候選\n"})
    with pytest.raises(page_checks.Fail, match="DB candidate_runs 2026-10-22 有 20 檔"):
        page_checks.t7(run)


class CopyRun(FakeRun):
    """Reads its facts with db_facts.py from a DB file, as the real run does."""

    facts = page_checks.Run.facts


def test_a_copy_without_a_current_version_run_runs_to_the_end(tmp_path, monkeypatch):
    # #307: the #306 copy had only candidate_score_v1 runs, and the first
    # run.facts() raised TypeError, so no check of any page had a result.
    db = tmp_path / "stock.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE candidate_runs (id INTEGER PRIMARY KEY, trading_date TEXT,"
            " score_version TEXT, candidate_count INTEGER)"
        )
        conn.execute(
            "INSERT INTO candidate_runs VALUES (1, ?, 'candidate_score_v1', 20)", (DAY,)
        )
    conn.close()
    payloads = {
        "candidates": {"status": "not_computed", "trading_date": None, "items": []},
        "actions?limit=20": {
            "items": [],
            "meta": {"data_as_of": DAY},
            "summary": {"tiers": [{"tier": 1, "label": "今日候選", "shown": 0}]},
        },
        "actions?tier=0&limit=100": {"items": []},
    }
    pages = {
        "today-1280": "今日名單\n尚無候選清單\n",
        "actions-1280": "第 1 級\n今日候選\n顯示 0／0 檔\n",
    }
    run = CopyRun(tmp_path, payloads, pages)
    run.db = db
    _only(monkeypatch, "today", "T7")
    _only(monkeypatch, "actions", "A8")
    t7, a8 = [
        *page_checks.run_page(run, "today", []),
        *page_checks.run_page(run, "actions", []),
    ]
    assert (t7.status, a8.status) == ("通過", "通過")
    assert "DB 也沒有當日候選" in t7.detail
    assert "沒有今日候選列" in a8.detail
    facts = json.loads((tmp_path / "out" / "facts.json").read_text(encoding="utf-8"))
    assert (
        facts["candidate_run_latest_trading_date"],
        facts["candidate_count_latest"],
    ) == (None, None)


def test_actions_without_cards_fail_when_the_api_has_items(tmp_path):
    payloads = {
        "actions?limit=20": {"items": [{}, {}, {}], "meta": {"data_as_of": DAY}}
    }
    page = "我的庫存\n尚未建立庫存。\n第 1 級\n今日候選\n顯示 3／3 檔\n"
    run = _run(tmp_path, payloads, {"actions-1280": page})
    with pytest.raises(
        page_checks.Fail, match="actions.json items 3，頁面沒有任何行動列"
    ):
        page_checks.a4(run)
    # A5 looks for what must be absent; a page without rows proves nothing.
    with pytest.raises(page_checks.Undetermined, match="頁面沒有行動列"):
        page_checks.a5(run)


# ---- E/S falls back when the board is empty ----


def test_the_stock_comes_from_the_candidates_when_the_board_is_empty(tmp_path):
    run = _run(tmp_path)
    # Before #251 there was no stock and all of S1～S9 were 無法判定 (counted 失敗).
    assert page_checks.stocks_for(run, None) == [page_checks.Stock("TWSE", "2301")]
    assert run.picked.startswith("今日名單 #1（略過 今日榜：")


def test_the_stock_comes_from_the_list_without_candidates(tmp_path):
    listed = {"items": [{"instrument": {"exchange": "TWSE", "symbol": "0050"}}]}
    run = _run(
        tmp_path,
        {
            "candidates": {**CANDIDATES, "items": []},
            "stocks?page=1&page_size=30": listed,
        },
    )
    assert run.stock() == page_checks.Stock("TWSE", "0050")
    assert run.picked.startswith("市場列表第一筆（略過 今日榜：")
    assert "今日名單：candidates.json 的 items 為空" in run.picked


def test_stocks_checks_that_need_no_stock_run_without_one(tmp_path, monkeypatch):
    listed = {"items": [], "meta": {"total": 0}}
    header = "代號\t名稱\t交易所\t類型\t最近收盤（元）\t目前研究動作"
    run = _run(
        tmp_path,
        {
            "candidates": {**CANDIDATES, "items": []},
            "stocks?page=1&page_size=30": listed,
        },
        {"stocks-1280": f"{header}\n沒有符合條件的標的。\n第 1／1 頁 · 共 0 筆\n"},
    )
    _only(monkeypatch, "stocks", "S1", "S2", "S3")
    s1, s2, s3 = page_checks.run_page(run, "stocks", page_checks.stocks_for(run, None))
    assert (s1.status, s2.status, s3.status) == ("通過", "通過", "無法判定")
    assert "只驗 /stocks" in s1.detail
    assert (
        "沒有可用的個股" in s3.detail
        and "市場列表：stocks.json 的 items 為空" in s3.detail
    )


# ---- the run ----


def test_undetermined_fails_only_a_fixture_run():
    results = [
        page_checks.Result("today", "T1", "通過", ""),
        page_checks.Result("today", "T2", "無法判定", "/api/dashboard 回 500"),
    ]
    assert page_checks.blocking(results, fixture=False) == []
    assert page_checks.blocking(results, fixture=True) == results[1:]


HEAD_SHA = "61714f5" + "0" * 33
RELEASE_SHA = "8a2b3c4" + "0" * 33


def _git(status="", release=HEAD_SHA):
    def git(*args, check=True):
        if args[0] == "status":
            out = status
        elif args[:2] == ("rev-parse", "HEAD"):
            out = HEAD_SHA + "\n"
        elif args[0] == "rev-parse" and args[-1] == page_checks.G7_REF:
            out = release + "\n"
        else:
            out = ""
        return subprocess.CompletedProcess(args, 0, out, "")

    return git


def test_g7_needs_the_committed_release_branch(monkeypatch):
    """#288: G7 evidence is the program the schedule runs, origin/release/v1."""
    monkeypatch.setattr(page_checks, "git", _git())
    assert page_checks.g7_problems() == []
    monkeypatch.setattr(
        page_checks,
        "git",
        _git(" M tools/verify/page_checks.py\n", release=RELEASE_SHA),
    )
    assert page_checks.g7_problems() == [
        "工作樹有未 commit 的檔：tools/verify/page_checks.py",
        "HEAD 61714f5 不是 origin/release/v1（8a2b3c4）："
        "先 git fetch origin release/v1，從它建 worktree",
    ]


def test_manual_samples_follow_the_written_rules(tmp_path):
    ai = {"status": "done", "inference": True, "summary": "摘要"}
    listed = [
        {"id": "1", "published_at": "2026-10-22T01:00:00+00:00", "ai": ai},
        {"id": "2", "published_at": "2026-10-22T02:00:00+00:00", "ai": None},
        {
            "id": "3",
            "published_at": "2026-10-21T15:59:00+00:00",
            "ai": ai,
        },  # 10/21 23:59
        {
            "id": "4",
            "published_at": "2026-10-21T16:00:00",
            "ai": ai,
        },  # naive UTC: 10/22
    ] + [
        {"id": str(n), "published_at": "2026-10-22T03:00:00+00:00", "ai": ai}
        for n in range(5, 12)
    ]
    payloads = {
        "dashboard": {**DASHBOARD, "as_of": f"{DAY}T00:00:00"},
        "news?category=domestic&limit=100": {"items": listed},
        **{f"news/{item['id']}": {"id": item["id"], "ai": ai} for item in listed},
    }
    run = _run(tmp_path, payloads)
    rows = page_checks.write_samples(run, ["today", "news"])
    assert [(page, code) for page, code, _ in rows] == [
        ("today", "T10"),
        ("news", "N7"),
        ("news", "N8"),
    ]

    n7 = json.loads(
        (tmp_path / "out" / "manual" / "N7.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in n7["items"]] == ["1", "4", "5", "6", "7"]
    t10 = json.loads(
        (tmp_path / "out" / "manual" / "T10.json").read_text(encoding="utf-8")
    )
    assert [item["rank"] for item in t10["items"]] == [1, 2, 3]


def test_the_news_sample_pages_back_to_the_data_date(tmp_path):
    # 2026-10-24 23:47: the newest 100 domestic news were all after D (10/22), so
    # the first page alone gave 0 samples.
    ai = {"status": "done", "inference": True}
    later = [
        {"id": str(n), "published_at": "2026-10-24T01:00:00+00:00", "ai": ai}
        for n in range(100, 200)
    ]
    on_d = [
        {"id": "1", "published_at": "2026-10-22T05:00:00+00:00", "ai": ai},
        {"id": "2", "published_at": "2026-10-21T05:00:00+00:00", "ai": ai},
    ]
    cursor = "eyJpZCI6Mn0+/="
    payloads = {
        "dashboard": {**DASHBOARD, "as_of": DAY},
        "news?category=domestic&limit=100": {
            "items": later,
            "meta": {"has_more": True, "next_cursor": cursor},
        },
        "news?category=domestic&limit=100&cursor=eyJpZCI6Mn0%2B/%3D": {
            "items": on_d,
            "meta": {"has_more": True, "next_cursor": "never-read"},
        },
        "news/1": {"id": "1", "ai": ai},
    }
    sample = page_checks.news_sample(_run(tmp_path, payloads))
    assert [item["id"] for item in sample["items"]] == ["1"]


def _action_item(symbol, tier, rank=None):
    return {
        "instrument": {
            "exchange": "TWSE",
            "symbol": symbol,
            "instrument_type": "stock",
        },
        "tier": tier,
        "candidate": {"rank": rank, "total_score": 0.5} if rank else None,
    }


def test_a_held_candidate_is_not_missing_from_todays_candidates(tmp_path):
    """#301 review M1: holding the rank-2 candidate moves it to tier 0."""

    held = _action_item("2302", 0)
    rows = [_action_item(f"23{n:02d}", 1, n) for n in range(1, 21) if n != 2]
    tiers = [
        {"tier": 0, "label": "持倉風險", "shown": 1},
        {"tier": 1, "label": "今日候選", "shown": 19},
    ]
    payloads = {
        # The first page: the holding, then 19 of the 20 candidates.
        "actions?limit=20": {
            "items": [held, *rows],
            "meta": {"data_as_of": DAY},
            "summary": {"tiers": tiers},
        },
        "actions?tier=0&limit=100": {"items": [held]},
    }
    page = (
        "第 0 級\n持倉風險\n顯示 1／1 檔\n第 1 級\n今日候選\n顯示 19／19 檔\n"
        + "".join(f"#{n}\t23{n:02d} 名稱\n" for n in range(1, 21) if n != 2)
    )
    run = _run(tmp_path, payloads, {"actions-1280": page})
    assert "去掉持倉" in page_checks.a8(run)


def test_a_tier_without_rows_on_the_first_page_shows_its_first_rows(tmp_path):
    """#301 review M2: tier 2 loads its first five rows when tier 1 fills page 1."""

    rows = [_action_item(f"23{n:02d}", 1, n) for n in range(1, 21)]
    preview = [_action_item(f"24{n:02d}", 2) for n in range(1, 6)]
    tiers = [
        {"tier": 1, "label": "今日候選", "shown": 20},
        {"tier": 2, "label": "其他成立條件", "shown": 50},
    ]
    payloads = {
        "actions?limit=20": {
            "items": rows,
            "meta": {"data_as_of": DAY},
            "summary": {"tiers": tiers},
        },
        "actions?tier=2&limit=5": {"items": preview},
    }
    row = "\t2026/10/22\t策略總表 →\n"
    page = (
        "第 1 級\n今日候選\n顯示 20／20 檔\n"
        + "".join(f"#{n}\t23{n:02d} 名稱{row}" for n in range(1, 21))
        + "第 2 級\n其他成立條件\n顯示 5／50 檔\n"
        + "".join(f"24{n:02d} 名稱{row}" for n in range(1, 6))
        + "顯示更多（還有 45 檔）\n"
    )
    run = _run(tmp_path, payloads, {"actions-1280": page})
    assert "其他成立條件 `顯示 5／50 檔`" in page_checks.a3(run)
    assert page_checks.a4(run).startswith("25 列")
    # The first page alone is not what the page shows: an empty tier 2 fails.
    empty = page.replace("顯示 5／50 檔", "顯示 0／50 檔")
    with pytest.raises(page_checks.Fail, match="顯示 5／50 檔"):
        page_checks.a3(_run(tmp_path, payloads, {"actions-1280": empty}))


# ---- #609: the API's 5xx on a busy host is 無法判定（環境）, not a page failure ----

# #606 (pr-assets/606/20261110-1304): four browsers next to a container at 100% CPU
# exhausted the API's pool; the shots saw 500/504 and G1/S1/A1 failed, although every
# URL answered 200 when called alone and a --jobs 1 rerun passed all 60 checks.
BUSY = "504 http://web:8080/api/dashboard"
TODAY_DATED = "今日\n資料 2026/10/22\n今日名單\n"


class ShotRun(page_checks.Run):
    """The real screenshot and API logic, with screenshot.cjs and HTTP replaced.

    ``shots[name]`` lists, per screenshot.cjs call, the extra fields of each width's
    JSON line (default: ready, no errors); ``statuses[path]`` is what a direct GET gets.
    """

    def __init__(self, tmp_path, shots=None, statuses=None, pages=None):
        super().__init__(
            "http://api",
            "http://web:8080",
            tmp_path / "db",
            tmp_path / "out",
            now=page_checks.datetime(2026, 10, 24, 12, tzinfo=page_checks.TAIPEI),
        )
        self.script = {name: list(calls) for name, calls in (shots or {}).items()}
        self.statuses = statuses or {}
        self.pages = pages or {}
        self.calls: list[str] = []
        self.fetched: list[str] = []

    def screenshot_cjs(self, command, **_kwargs):
        """Stands in for ``subprocess.run`` of screenshot.cjs."""

        name = command[command.index("--name") + 1]
        widths = [int(w) for w in command[command.index("--widths") + 1].split(",")]
        self.calls.append(name)
        calls = self.script.get(name) or [{}]
        extra = calls.pop(0) if len(calls) > 1 else calls[0]
        lines = []
        for width in widths:
            txt = self.out / "shots" / f"{name}-{width}.txt"
            txt.write_text(self.pages.get(f"{name}-{width}", ""), encoding="utf-8")
            meta = {"width": width, "ready": True, "txt": str(txt), "httpErrors": []}
            meta.update(extra.get(width, extra.get("*", {})))
            meta.setdefault("httpErrorCount", len(meta["httpErrors"]))
            lines.append(json.dumps(meta))
        return subprocess.CompletedProcess(command, 0, "\n".join(lines) + "\n", "")

    def _fetch(self, path):
        self.fetched.append(path)
        status = self.statuses.get(path, 200)
        payload = {"as_of": "2026-10-22T18:00:00+08:00"} if path == "dashboard" else {}
        return status, payload if status == 200 else "Internal Server Error"

    def facts(self, stock=None):
        return {"market_latest_trading_date": "2026-10-22"}


def _busy(**more):
    return {"*": {"ready": False, "httpErrors": [BUSY], **more}}


def _today(run, monkeypatch, *codes):
    _only(monkeypatch, "today", *codes)
    monkeypatch.setattr(page_checks.subprocess, "run", run.screenshot_cjs)
    page_checks.prefetch(run, ["today"], [], jobs=1)
    return {r.code: r for r in page_checks.run_page(run, "today", [])}


def test_a_5xx_that_answers_200_alone_is_undetermined_not_failed(tmp_path, monkeypatch):
    # AC-2: still 504 after the serial retake, 200 to a direct GET -> the host was busy.
    run = ShotRun(tmp_path, {"today": [_busy(), _busy()]}, pages={})
    results = _today(run, monkeypatch, "T1", "T2")
    t1, t2 = results["T1"], results["T2"]
    # Before #609: T1 失敗 with 「today-1280 未 ready；today-1280 httpErrors [...]」.
    assert (t1.status, t1.failed) == ("無法判定", False), t1.detail
    assert t1.environment
    assert t1.detail.startswith("無法判定（環境）：today-1280 未 ready")
    assert BUSY in t1.detail and "直接 GET 回 200" in t1.detail
    assert (t2.status, t2.environment) == ("無法判定", True)
    assert "504 /api/dashboard，直接 GET 回 200" in t2.detail
    # The parallel pass (its usual not-ready retry) and one serial retake, then one direct GET.
    assert run.calls.count("today") == 3 and run.fetched == ["dashboard"]
    env = run.environment(1, list(results.values()))
    assert (env["hits"], env["screenshot_hits"], env["api_hits"]) == (4, 4, 0)
    assert env["retaken"] == ["today"] and env["recovered"] == []
    assert env["rechecked"] == {"dashboard": 200}
    assert env["urls"] == [{"path": "dashboard", "status": 504, "count": 4}]
    assert env["checks"] == ["today T1", "today T2"]
    # The overall result keeps the 無法判定 behaviour: a fixture run still fails on it.
    assert page_checks.blocking(list(results.values()), fixture=False) == []
    assert page_checks.blocking(list(results.values()), fixture=True) == [t1, t2]


def test_a_5xx_that_stays_5xx_alone_still_fails(tmp_path, monkeypatch):
    # AC-2 counter-example: the direct GET is 500 too, so the API is broken.
    run = ShotRun(tmp_path, {"today": [_busy()]}, {"dashboard": 500})
    results = _today(run, monkeypatch, "T1", "T2")
    assert results["T1"].status == "失敗" and not results["T1"].environment
    assert results["T1"].detail.startswith("today-1280 未 ready")
    assert (results["T2"].status, results["T2"].environment) == ("無法判定", False)
    assert run.environment(1, list(results.values()))["rechecked"] == {"dashboard": 500}


def test_a_busy_shot_with_a_console_error_still_fails(tmp_path, monkeypatch):
    # AC-2 counter-example: another problem on the same shot is the page's own.
    run = ShotRun(tmp_path, {"today": [_busy(consoleErrors=["TypeError: x is null"])]})
    (t1,) = _today(run, monkeypatch, "T1").values()
    assert t1.status == "失敗" and not t1.environment
    assert "consoleErrors ['TypeError: x is null']" in t1.detail
    assert BUSY in t1.detail


@pytest.mark.parametrize(
    "error",
    [
        "404 http://web:8080/api/stocks/TWSE/0000",  # an /api/ 4xx
        "502 http://web:8080/assets/index.js",  # a 5xx that is not /api/
    ],
)
def test_a_4xx_or_non_api_error_on_a_busy_shot_still_fails(
    tmp_path, monkeypatch, error
):
    run = ShotRun(tmp_path, {"today": [_busy(httpErrors=[BUSY, error])]})
    (t1,) = _today(run, monkeypatch, "T1").values()
    assert t1.status == "失敗" and not t1.environment
    assert f"httpErrors ['{error}']" in t1.detail


def test_a_cut_http_error_list_is_not_environment(tmp_path, monkeypatch):
    # #609 review: screenshot.cjs lists at most 50; the 51st could be a 404 or a broken URL.
    run = ShotRun(tmp_path, {"today": [_busy(httpErrorCount=51)]})
    (t1,) = _today(run, monkeypatch, "T1").values()
    assert t1.status == "失敗" and not t1.environment
    assert "httpErrors 共 51 筆，清單只列 1 筆（截斷，不認定環境）" in t1.detail


def test_the_fixture_database_neither_retakes_nor_excuses_a_5xx(tmp_path, monkeypatch):
    # #609 review: no other container competes in CI, so a 5xx there is a signal.
    run = ShotRun(tmp_path, {"today": [_busy(), _busy(), {}]})
    run.env_checks = False
    results = _today(run, monkeypatch, "T1", "T2")
    assert results["T1"].status == "失敗" and not results["T1"].environment
    assert results["T1"].detail.startswith("today-1280 未 ready；today-1280 httpErrors")
    assert results["T2"].status == "無法判定" and not results["T2"].environment
    # Only the usual not-ready retry of the parallel pass; no retake, no direct GET.
    assert run.calls.count("today") == 2 and run.fetched == []
    assert run.environment(4, list(results.values()))["hits"] == 0
    run = ShotRun(tmp_path, statuses={"dashboard": 500})
    run.env_checks = False
    with pytest.raises(page_checks.Undetermined) as error:
        run.dashboard()
    assert not isinstance(error.value, page_checks.Environment)


def test_a_recovered_retake_keeps_the_first_takes_other_problems(tmp_path, monkeypatch):
    console = _busy(consoleErrors=["TypeError: x is null"])
    run = ShotRun(tmp_path, {"today": [console, console, {}]})
    results = list(_today(run, monkeypatch, "T1").values())
    assert results[0].status == "通過"
    env = run.environment(1, results)
    assert env["replaced_problems"] == {
        "today": [
            "today-1280 consoleErrors ['TypeError: x is null']",
            "today-390 consoleErrors ['TypeError: x is null']",
        ]
    }
    summary = page_checks.summary_markdown(results, ["today"], "## h", environment=env)
    assert "- 重截後恢復的 `today` 第一次截圖另有：today-1280 consoleErrors" in summary


def test_a_retake_without_5xx_is_judged_as_usual(tmp_path, monkeypatch):
    # Retaken serially once: the clean shot is used, so the page's own text decides.
    run = ShotRun(
        tmp_path,
        {"today": [_busy(), _busy(), {}]},
        pages={"today-1280": TODAY_DATED},
    )
    results = _today(run, monkeypatch, "T1", "T2")
    assert (results["T1"].status, results["T2"].status) == ("通過", "通過")
    assert run.fetched == ["dashboard"]  # T2's run.get only; no recheck was needed
    env = run.environment(1, list(results.values()))
    assert env["recovered"] == ["today"] and env["rechecked"] == {}
    assert env["checks"] == []


def test_a_page_whose_api_answers_200_still_fails_on_wrong_text(tmp_path, monkeypatch):
    # AC-2: no 5xx at all, the API is 200 and the page shows another date -> 失敗.
    run = ShotRun(tmp_path, pages={"today-1280": "今日\n資料 2026/10/21\n"})
    results = _today(run, monkeypatch, "T1", "T2")
    assert results["T1"].status == "通過"
    assert results["T2"].status == "失敗" and not results["T2"].environment
    assert "缺整行 `資料 2026/10/22`" in results["T2"].detail
    assert run.calls.count("today") == 1  # no retake without an /api/ 5xx
    assert run.environment(1, list(results.values()))["hits"] == 0


def test_an_api_call_that_times_out_is_environment(tmp_path, monkeypatch):
    run = ShotRun(tmp_path, statuses={"dashboard": 0})
    with pytest.raises(page_checks.Environment, match="/api/dashboard 回 0"):
        run.dashboard()
    run = ShotRun(tmp_path, statuses={"dashboard": 404})
    with pytest.raises(page_checks.Undetermined) as error:
        run.dashboard()
    assert not isinstance(error.value, page_checks.Environment)


def test_the_summary_opens_with_the_5xx_urls(tmp_path, monkeypatch):
    run = ShotRun(tmp_path, {"today": [_busy(), _busy()]})
    results = list(_today(run, monkeypatch, "T1").values())
    env = run.environment(1, results)
    summary = page_checks.summary_markdown(
        results, ["today"], "## head", environment=env
    )
    head, section, bullets = summary.split("\n\n")[:3]
    assert head == "## head"
    assert section == "### 環境：API 5xx／逾時 4 次（截圖 4、API 呼叫 0；截圖並行 1）"
    assert "重截 1 張（串列、各一次），恢復 0 張" in bullets
    assert "直接 GET 回 200 的 1 個" in bullets and "`today T1`" in bullets
    assert "| `/api/dashboard` | 504 | 4 |" in summary
    assert summary.index("### 環境") < summary.index("### 今日名單")
    quiet = page_checks.summary_markdown(
        results, ["today"], "## head", environment=ShotRun(tmp_path).environment(1, [])
    )
    assert "### 環境" not in quiet


def test_the_default_jobs_are_one_on_real_data_only():
    assert page_checks.default_jobs(None, fixture=True) == 4
    assert page_checks.default_jobs(None, fixture=False) == 1
    assert page_checks.default_jobs(3, fixture=False) == 3
    assert page_checks.default_jobs(2, fixture=True) == 2
