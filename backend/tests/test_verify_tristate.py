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
    "資料日期待核實\n今日\n資料截至\n資料日期待核實\n"
    f"熱門族群\n產業榜\n資料日期待核實\n{NO_RUN}\n"
    "明日候選\n資料 2026/10/22\n20 檔\n"
    f"關注標的\n{ACTIONS_EMPTY}\n"
)


def _run(tmp_path, payloads=None, pages=None, facts=None):
    base = {
        "dashboard": DASHBOARD,
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
    pages = {"today-1280": "明日候選\n資料 2026/10/22\n1 檔\n#1\t2301 光寶科\n"}
    _only(monkeypatch, "today", "T7", "T8")
    t7, t8 = page_checks.run_page(_run(tmp_path, payloads, pages), "today", [])
    assert (t7.status, t8.status) == ("失敗", "無法判定")
    assert t8.detail.startswith("無法判定（上游 T7）：`來源：` 行 0，items 1")


# ---- KNOWN_FAILURES matches the message ----


def _t6_run(tmp_path):
    news = {
        "id": "2845",
        "title": "颱風假台股該不該開盤？政大教授點出交易真相\xa0 網友反問",
    }
    page = "今日市場／重大事件\n颱風假台股該不該開盤？政大教授點出交易真相\n熱門族群\n"
    return _run(
        tmp_path, {"dashboard": {**DASHBOARD, "news": [news]}}, {"today-1280": page}
    )


def test_a_different_failure_of_a_known_check_fails(tmp_path, monkeypatch):
    issue = "https://github.com/YiCheng0608/stock-lab/issues/233"
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("today", "T6"),
        page_checks.Known(issue, "卡片沒有 `AI 推論`"),
    )
    _only(monkeypatch, "today", "T6")
    (t6,) = page_checks.run_page(_t6_run(tmp_path), "today", [])
    # Before #251 this was 失敗（已知） and did not fail the run.
    assert (t6.status, t6.failed, t6.known) == ("失敗", True, None)
    assert "缺新聞標題整行" in t6.detail
    assert "不是已知失敗" in t6.detail and issue in t6.detail


def test_the_known_failure_itself_stays_known(tmp_path, monkeypatch):
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("today", "T6"),
        page_checks.Known("#233", "缺新聞標題整行"),
    )
    _only(monkeypatch, "today", "T6")
    (t6,) = page_checks.run_page(_t6_run(tmp_path), "today", [])
    assert (t6.status, t6.failed, t6.known) == ("失敗（已知）", False, "#233")


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
        {"dashboard": {**DASHBOARD, "groups": []}},
        {
            "themes-1280": f"產業榜 · 共 0 個族群\n{NO_RUN}\n",
            "themes-390": f"{NO_RUN}\n",
        },
        {"group_scores_latest_trading_date": None},
    )
    assert NO_RUN in page_checks.g3(run)


def test_the_empty_watch_list_fails_next_to_todays_candidates(tmp_path):
    # Before #251 T9 passed on 「沒有卡片，顯示 `目前沒有資料完整的可執行條件…`」.
    with pytest.raises(page_checks.Fail, match="candidates.json 有 20 檔 2026-10-22"):
        page_checks.t9(_run(tmp_path))


def test_the_watch_list_fails_when_the_dashboard_has_cards_to_show(tmp_path):
    action = {
        "instrument": {"exchange": "TWSE", "symbol": "2330"},
        "action_state": "hold_observe",
    }
    run = _run(tmp_path, {"dashboard": {**DASHBOARD, "actions": [action]}})
    with pytest.raises(page_checks.Fail, match="dashboard.actions／candidates 有 1 筆"):
        page_checks.t9(run)


def test_zero_candidates_fail_when_the_db_has_them(tmp_path):
    payloads = {"candidates": {**CANDIDATES, "candidate_count": 0, "items": []}}
    run = _run(tmp_path, payloads, {"today-1280": "明日候選\n當日零候選\n"})
    with pytest.raises(page_checks.Fail, match="DB candidate_runs 2026-10-22 有 20 檔"):
        page_checks.t7(run)


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
    assert run.picked.startswith("明日候選 #1（略過 今日榜：")


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
    assert "明日候選：candidates.json 的 items 為空" in run.picked


def test_stocks_checks_that_need_no_stock_run_without_one(tmp_path, monkeypatch):
    listed = {"items": [], "meta": {"total": 0}}
    header = "代號\t名稱\t交易所\t類型\t最近收盤\t目前研究動作\t策略判斷資料"
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
