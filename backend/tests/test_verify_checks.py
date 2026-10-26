"""tools/verify/page_checks.py, the CI checks of the five main pages (Issue #243).

The features labels must match the implemented checks (a check labeled CI in
features/*.md without code, or code without a CI label, fails).  The checks
themselves run on hand-written page text and API payloads; the CI ``verify``
job runs them on real screenshots of the fixture database.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / ".claude" / "skills" / "verify-stock-lab" / "features"


def _load():
    spec = importlib.util.spec_from_file_location(
        "page_checks", ROOT / "tools" / "verify" / "page_checks.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["page_checks"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


page_checks = _load()


# ---- features labels ----


def test_every_ci_check_in_features_is_implemented():
    labels = page_checks.feature_checks()
    assert all(labels[page] for page in page_checks.PAGES), labels
    assert page_checks.registry_problems(labels, page_checks.CHECKS) == []


def test_every_feature_check_has_a_type():
    for page, codes in page_checks.feature_checks().items():
        for code, kind in codes.items():
            assert kind in ("CI", "人工"), (page, code, kind)


def _features_with(tmp_path: Path, page: str, row: str) -> Path:
    copy = tmp_path / "features"
    shutil.copytree(FEATURES, copy)
    path = copy / f"{page}.md"
    text = path.read_text(encoding="utf-8")
    head, rest = text.split("\n## 檢查\n", 1)
    section, tail = rest.split("\n## ", 1)
    path.write_text(
        head + "\n## 檢查\n" + section.rstrip("\n") + f"\n{row}\n\n## " + tail,
        encoding="utf-8",
    )
    return copy


def test_a_new_ci_check_without_code_fails(tmp_path):
    features = _features_with(tmp_path, "today", "| T99 | CI | 新檢查 | 某條件 |")
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == ["today.md T99: labeled CI but not implemented"]


def test_every_manual_check_has_a_sampler():
    labels = page_checks.feature_checks()
    manual = {
        (page, code)
        for page, codes in labels.items()
        for code, kind in codes.items()
        if kind == "人工"
    }
    assert {("news", "N7"), ("news", "N8"), ("today", "T10")} <= manual
    assert all(code in page_checks.MANUAL[page] for page, code in manual)


def test_a_manual_check_without_a_sampler_fails(tmp_path):
    # #251: the sample is fixed by code, not picked by whoever judges it.
    features = _features_with(
        tmp_path, "news", "| N99 | 人工 | 摘要合理 | agent 判斷 |"
    )
    labels = page_checks.feature_checks(features)
    assert labels["news"]["N99"] == "人工"
    assert page_checks.registry_problems(labels, page_checks.CHECKS) == [
        "news.md N99: labeled 人工 but has no sampler"
    ]


def test_a_sampler_without_a_manual_label_fails(tmp_path):
    features = tmp_path / "features"
    shutil.copytree(FEATURES, features)
    path = features / "today.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("| T10 | 人工 |", "| T10 | CI |"),
        encoding="utf-8",
    )
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == [
        "today.md T10: labeled CI but not implemented",
        "today T10: sampled but today.md does not label it 人工",
    ]


def test_a_check_without_a_type_fails(tmp_path):
    features = _features_with(tmp_path, "themes", "| G8 | 新檢查 | 某條件 |")
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == ["themes.md G8: 類型 is '新檢查', not CI or 人工"]


def test_code_that_features_label_manual_fails(tmp_path):
    features = tmp_path / "features"
    shutil.copytree(FEATURES, features)
    path = features / "actions.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("| A5 | CI |", "| A5 | 人工 |"),
        encoding="utf-8",
    )
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == [
        "actions.md A5: labeled 人工 but has no sampler",
        "actions A5: implemented but actions.md does not label it CI",
    ]


# ---- page text ----


def test_normalize_keeps_tabs_and_collapses_spaces():
    assert page_checks.normalize("  資料　 2026/10/16  ") == "資料 2026/10/16"
    assert page_checks.normalize("排名\t族群\t") == "排名\t族群\t"


def test_normalize_treats_unicode_spaces_as_spaces():
    # Issue #249: news 2845's title has "\xa0 ", which the browser shows as one space.
    title = "交易真相\xa0 網友反問"
    assert page_checks.normalize(title) == "交易真相 網友反問"
    assert page_checks.normalize(" 資料 2026/10/16\xa0") == "資料 2026/10/16"
    # The expected string from the API is normalized too, not only the page text.
    assert page_checks.Text("p.txt", "交易真相 網友反問\n").has(title)


def test_text_skips_blank_lines_and_keeps_line_numbers():
    text = page_checks.Text("p.txt", "明日候選\n\n  \n資料 2026/10/16\n3 檔\n")
    assert text.lines == ["明日候選", "資料 2026/10/16", "3 檔"]
    i = text.find("明日候選")
    assert text.after(i) == "資料 2026/10/16"
    assert text.after(i, 2) == "3 檔"
    assert text.after(i, 3) is None
    assert text.at(text.find("3 檔")) == "p.txt 第 5 行"


# ---- checks on fake pages ----


class FakeRun(page_checks.Run):
    """Serves fixed API payloads and page text instead of HTTP and screenshots."""

    def __init__(self, tmp_path, payloads, pages, facts=None, metas=None):
        super().__init__(
            "http://api",
            "http://web",
            tmp_path / "db",
            tmp_path / "out",
            now=datetime(2026, 10, 24, 12, tzinfo=page_checks.TAIPEI),
        )
        self.payloads = payloads
        self.pages = pages
        self.fake_facts = facts or {}
        self.metas = metas or {}

    def get(self, path, name=None):
        if path not in self.payloads:
            raise page_checks.Undetermined(f"/api/{path} 回 404")
        return self.payloads[path]

    def facts(self, stock=None):
        return self.fake_facts

    def shoot(self, shot):
        return self.metas.get(
            shot.name, {width: {"width": width, "ready": True} for width in shot.widths}
        )

    def text(self, shot, width=1280):
        key = f"{shot.name}-{width}"
        if key not in self.pages:
            raise page_checks.Undetermined(f"{key} 未 ready")
        return page_checks.Text(f"{key}.txt", self.pages[key])


def _candidates(count=2, inference=True):
    return {
        "status": "success",
        "trading_date": "2026-10-16",
        "candidate_count": count,
        "items": [
            {
                "rank": n + 1,
                "instrument": {"symbol": f"910{n}"},
                "components": {"news_sentiment": {"inference": inference}},
                # #1 has a note, #2 none: their entries read AI 推論 ▸ and AI 說明 ▸.
                "llm_note": {"status": "done"} if n == 0 else None,
            }
            for n in range(count)
        ],
    }


# The 1280 table (#276): rank cell first, tab-separated cells, then the opened detail row.
TODAY_CANDIDATES = (
    "明日候選\n資料 2026/10/16\n2 檔\n"
    "名次\t股票\t所屬族群（名次）\t最近收盤\n"
    "#1\t9100 示範一\n上市 · 突破條件\t半導體（產業，第 1 名／9）\t21.10\n+0.48%\tAI 推論 ▸\n"
    "AI 推論\n" + page_checks.CANDIDATE_DISCLAIMER + "\n來源：訊號 a（推論）\n"
    "#2\t9101 示範二\n上櫃 · 回踩條件\t無所屬產業或題材\t13.20\n漲跌待核實\tAI 說明 ▸\n"
    "AI 推論\n" + page_checks.CANDIDATE_DISCLAIMER + "\n來源：訊號 b（推論）\n"
    "熱門族群\n#1\n半導體\n"
)


def test_t7_and_t8_pass_on_matching_text(tmp_path):
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": TODAY_CANDIDATES},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    assert "名次列 2、來源行 2 = items" in page_checks.t7(run)
    result = page_checks.t8(run)
    assert "`AI 推論` 2 行" in result and "`AI 推論 ▸` 1、`AI 說明 ▸` 1" in result


def test_t7_fails_on_the_old_candidate_cards(tmp_path):
    # Before #276 each candidate was a card without a rank cell starting a table row.
    page = TODAY_CANDIDATES.replace("#1\t", "").replace("#2\t", "")
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": page},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    with pytest.raises(
        page_checks.Fail, match=r"`#n` 名次列 \[\]，預期依 items \[1, 2\]"
    ):
        page_checks.t7(run)


def test_t7_counts_only_the_rank_rows_before_the_groups(tmp_path):
    # The group rows' `#1` after 熱門族群 is not a candidate row.
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates(count=1)},
        {"today-1280": TODAY_CANDIDATES.replace("2 檔", "1 檔")},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    with pytest.raises(
        page_checks.Fail, match=r"`#n` 名次列 \[1, 2\]，預期依 items \[1\]"
    ):
        page_checks.t7(run)


def test_t8_fails_when_an_ai_entry_does_not_match_the_note(tmp_path):
    page = TODAY_CANDIDATES.replace("AI 說明 ▸", "AI 推論 ▸")
    run = FakeRun(tmp_path, {"candidates": _candidates()}, {"today-1280": page})
    with pytest.raises(
        page_checks.Fail, match="`AI 推論 ▸` 2 個、`AI 說明 ▸` 0 個，預期 1／1"
    ):
        page_checks.t8(run)


def test_t7_fails_when_the_page_drops_the_candidates(tmp_path):
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": "明日候選\n資料 2026/10/16\n2 檔\n"},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    with pytest.raises(page_checks.Fail, match=r"`#n` 名次列 \[\]，預期依 items"):
        page_checks.t7(run)


def test_t8_fails_without_the_inference_mark(tmp_path):
    page = TODAY_CANDIDATES.replace("來源：訊號 b（推論）", "來源：訊號 b")
    run = FakeRun(tmp_path, {"candidates": _candidates()}, {"today-1280": page})
    with pytest.raises(page_checks.Fail, match="#2 9101 來源行沒有以 `（推論）` 結尾"):
        page_checks.t8(run)


# ---- T11 market overview, T12 block order (#276) ----


def _overview(tpex_status="available"):
    twse = {
        "exchange": "TWSE",
        "status": "available",
        "index": {"close": 46041.43, "change": -846.34, "change_pct": -0.0181},
        "turnover": {
            "value": 933437473560,
            "scope_label": "集中市場總計（含 ETF、權證等）",
        },
        "breadth": {
            "advancers": 247,
            "decliners": 756,
            "unchanged": 74,
            "limit_up": 3,
            "limit_down": 5,
        },
    }
    tpex = (
        {
            "exchange": "TPEx",
            "status": "available",
            "index": {"close": 381.69, "change": -13.73, "change_pct": -0.0347},
            "turnover": {"value": 225545000000, "scope_label": "上櫃股票"},
            "breadth": {
                "advancers": 146,
                "decliners": 659,
                "unchanged": 63,
                "limit_up": 17,
                "limit_down": 11,
            },
        }
        if tpex_status == "available"
        else {"exchange": "TPEx", "status": "unavailable", "reason": "not_collected"}
    )
    return {
        "market_overview": {"trading_date": "2026-10-22", "exchanges": [twse, tpex]}
    }


def _summary(**extra):
    row = {
        "trading_date": "2026-10-22",
        "index_close": 46041.43,
        "index_change": -846.34,
        "turnover": 933437473560,
        "advancers": 247,
        "decliners": 756,
    }
    return {**row, **extra}


TPEX_SUMMARY = {
    "trading_date": "2026-10-22",
    "index_close": 381.69,
    "index_change": -13.73,
    "turnover": 225545000000,
    "advancers": 146,
    "decliners": 659,
}
OVERVIEW_PAGE = (
    "資料截至 2026/10/22 · TWSE／TPEx 官方資料 · 官方單日快照\n資料說明\n"
    "成交金額範圍：上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票\n"
    "加權指數\n點\n46,041.43\n-846.34（-1.81%）\n"
    "櫃買指數\n點\n381.69\n-13.73（-3.47%）\n"
    "成交金額\n億元\n上市 9,334.37\n上櫃 2,255.45\n"
    "漲跌家數（股票）\n括號為漲停／跌停\n"
    "上市 上漲 247 · 下跌 756 · 平盤 74（3／5）\n"
    "上櫃 上漲 146 · 下跌 659 · 平盤 63（17／11）\n"
)


def test_t11_passes_when_the_widgets_show_the_api_and_db_values(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"today-1280": OVERVIEW_PAGE},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    assert "TWSE 46,041.43、TPEx 381.69" in page_checks.t11(run)


def test_t11_fails_on_a_widget_that_differs_from_the_api(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"today-1280": OVERVIEW_PAGE.replace("上市 9,334.37", "上市 9,334.38")},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    with pytest.raises(page_checks.Fail, match="TWSE 缺整行 `上市 9,334.37`"):
        page_checks.t11(run)


def test_t11_fails_on_an_api_value_that_differs_from_the_db(tmp_path):
    facts = {"TWSE": _summary(advancers=248), "TPEx": TPEX_SUMMARY}
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"today-1280": OVERVIEW_PAGE},
        {"market_summary_latest": facts},
    )
    with pytest.raises(
        page_checks.Fail, match="TWSE breadth.advancers 247 ≠ DB advancers 248"
    ):
        page_checks.t11(run)


def test_t11_unavailable_needs_its_copy_and_no_db_row_of_the_day(tmp_path):
    page = (
        OVERVIEW_PAGE.replace("；上櫃為上櫃股票", "")
        .replace("381.69\n-13.73（-3.47%）", "上櫃大盤資料未取得")
        .replace("上櫃 2,255.45", "上櫃大盤資料未取得")
    )
    facts = {"market_summary_latest": {"TWSE": _summary()}}
    run = FakeRun(
        tmp_path, {"dashboard": _overview("unavailable")}, {"today-1280": page}, facts
    )
    assert "TPEx 未取得" in page_checks.t11(run)
    facts = {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}}
    run = FakeRun(
        tmp_path, {"dashboard": _overview("unavailable")}, {"today-1280": page}, facts
    )
    with pytest.raises(
        page_checks.Fail,
        match="TPEx 為 unavailable，但 DB market_summaries 有 2026-10-22 的列",
    ):
        page_checks.t11(run)


def test_t11_fails_on_the_old_page_without_an_overview(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"today-1280": "資料截至\n2026/10/22\nTWSE／TPEx 官方資料\n"},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    with pytest.raises(page_checks.Fail, match="TWSE 缺整行 `46,041.43`"):
        page_checks.t11(run)


def test_t12_needs_the_candidates_before_groups_and_news(tmp_path):
    page = "明日候選\n資料 2026/10/16\n熱門族群\n資料 2026/10/16\n重點新聞\n關注標的\n"
    run = FakeRun(tmp_path, {}, {"today-1280": page})
    assert "`明日候選`" in page_checks.t12(run)
    old = "今日市場／重大事件\n熱門族群\n明日候選\n關注標的\n"
    run = FakeRun(tmp_path, {}, {"today-1280": old})
    with pytest.raises(page_checks.Fail, match="缺整行 `重點新聞`"):
        page_checks.t12(run)
    swapped = "熱門族群\n重點新聞\n明日候選\n"
    run = FakeRun(tmp_path, {}, {"today-1280": swapped})
    with pytest.raises(page_checks.Fail, match="熱門族群 → 重點新聞 → 明日候選"):
        page_checks.t12(run)


def test_a_missing_api_makes_the_check_undetermined(tmp_path):
    run = FakeRun(tmp_path, {}, {"today-1280": TODAY_CANDIDATES})
    with pytest.raises(page_checks.Undetermined) as error:
        page_checks.t7(run)
    assert str(error.value) == "無法判定：/api/candidates 回 404"


def test_a5_reports_the_line_of_an_inference_mark(tmp_path):
    run = FakeRun(tmp_path, {}, {"actions-1280": "我的庫存\n\n理由（推論）\n"})
    with pytest.raises(page_checks.Fail, match="actions-1280.txt 第 3 行"):
        page_checks.a5(run)


def _theme_run(tmp_path, total, pager):
    theme = "official-industry-x"
    members = {
        "meta": {"total": total, "data_as_of": "2026-10-16"},
        "items": [{"symbol": "9101", "name": "示範晶圓"}],
    }
    board = {
        "meta": {"trading_date": "2026-10-16"},
        "items": [{"theme_id": theme, "display_name": "半導體"}],
    }
    page = "代號\t名稱\t市場\t角色\t收盤\t資料日期\n9101\t示範晶圓\t上市\n" + pager
    return FakeRun(
        tmp_path,
        {
            "themes?board=industry&limit=5": board,
            f"themes/{theme}": {"theme": {"display_name": "半導體"}},
            f"themes/{theme}/members?page=1&page_size=30&sort=price": members,
        },
        {"theme-detail-1280": page},
    )


@pytest.mark.parametrize(
    ("total", "pager"), [(3, "共 3 檔"), (31, "第 1／2 頁 · 共 31 檔")]
)
def test_g6_follows_the_member_pager(tmp_path, total, pager):
    assert pager in page_checks.g6(_theme_run(tmp_path, total, pager))


def test_g6_fails_on_the_wrong_pager(tmp_path):
    with pytest.raises(page_checks.Fail, match="缺整行 `第 1／2 頁 · 共 31 檔`"):
        page_checks.g6(_theme_run(tmp_path, 31, "共 31 檔"))


def test_page_usable_reports_errors_and_overflow(tmp_path):
    metas = {
        "today": {
            1280: {"width": 1280, "ready": True, "consoleErrors": ["boom"]},
            390: {
                "width": 390,
                "ready": True,
                "overflow": True,
                "scrollWidth": 420,
                "clientWidth": 390,
            },
        }
    }
    run = FakeRun(tmp_path, {}, {}, metas=metas)
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t1(run)
    assert str(error.value) == (
        "today-1280 consoleErrors ['boom']；"
        "today-390 橫向捲動 scrollWidth 420 > clientWidth 390"
    )


def test_known_failures_do_not_fail_the_run_until_they_pass(tmp_path, monkeypatch):
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("actions", "A5"),
        page_checks.Known("https://example/1", "出現 LLM 推論標記"),
    )
    clean = FakeRun(tmp_path, {}, {"actions-1280": "我的庫存\n查看個股詳情 →\n"})
    marked = FakeRun(tmp_path, {}, {"actions-1280": "AI 推論\n"})
    monkeypatch.setitem(page_checks.CHECKS, "actions", {"A5": page_checks.a5})
    (failing,) = page_checks.run_page(marked, "actions", [])
    assert (failing.state, failing.failed, failing.status) == (
        "失敗",
        False,
        "失敗（已知）",
    )
    (passing,) = page_checks.run_page(clean, "actions", [])
    assert passing.failed and "從 KNOWN_FAILURES 移除 actions A5" in passing.detail


def _t6_run(tmp_path, ai, card_ai, card):
    item = {"id": "7", "title": "新聞甲", "ai": card_ai}
    return FakeRun(
        tmp_path,
        {"dashboard": {"news": [item]}, "news/7": {"ai": ai}},
        {
            "today-1280": f"今日市場／重大事件\n新聞甲\n摘要\n{card}未有已核實的標的或族群\n熱門族群\n"
        },
    )


AI_DONE = {"status": "done", "inference": True, "impact_direction": "positive"}


def test_t6_passes_when_the_card_shows_the_ai_direction(tmp_path):
    run = _t6_run(tmp_path, AI_DONE, AI_DONE, "可能正向\nAI 推論\n")
    assert "7 `可能正向`" in page_checks.t6(run)
    # An unsupported item's AI direction is 影響尚未判定, as on the news page.
    unsupported = {**AI_DONE, "unsupported": True}
    run = _t6_run(tmp_path, unsupported, unsupported, "影響尚未判定\nAI 推論\n")
    assert "7 `影響尚未判定`" in page_checks.t6(run)


def test_t6_fails_when_the_card_falls_back_to_the_rule_direction(tmp_path):
    # #233: dashboard.news had no ai block, so the card showed the rule direction.
    run = _t6_run(tmp_path, AI_DONE, None, "影響尚未判定\n")
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t6(run)
    assert "ai 與 /api/news/<id> 不同" in str(error.value)
    assert "卡片沒有 `AI 推論`" in str(error.value)


def test_t6_fails_when_the_card_direction_differs(tmp_path):
    run = _t6_run(tmp_path, AI_DONE, AI_DONE, "可能負向\nAI 推論\n")
    with pytest.raises(
        page_checks.Fail, match="卡片方向 `可能負向`，AI 方向 `可能正向`"
    ):
        page_checks.t6(run)


def _n6_run(tmp_path, generated_at, shown):
    ai = {
        "status": "done",
        "inference": True,
        "model": "m",
        "prompt_version": "news_v1",
        "generated_at": generated_at,
    }
    page = (
        "來源事實\nAI 摘要與判讀\nAI 推論\n"
        f"模型 m · 提示版本 news_v1 · 產生時間 {shown}。候選未經規則核實。\n"
    )
    return FakeRun(
        tmp_path,
        {
            "news?category=domestic&limit=20": {"items": [{"id": "7", "ai": ai}]},
            "news/7": {"ai": ai},
        },
        {"news-detail-1280": page},
    )


def test_n6_needs_the_taipei_generated_time(tmp_path):
    run = _n6_run(tmp_path, "2026-10-21T16:01:32.746332+00:00", "2026/10/22 00:01")
    assert "產生時間 2026/10/22 00:01" in page_checks.n6(run)
    assert page_checks.taipei_minute("2026-10-21T16:01:32Z") == "2026/10/22 00:01"


def test_n6_fails_when_the_generated_time_is_pending(tmp_path):
    # #234: the page wrote 待核實 while the API had a time.
    run = _n6_run(tmp_path, "2026-10-21T16:01:32.746332+00:00", "待核實")
    with pytest.raises(page_checks.Fail, match="沒有 `產生時間 2026/10/22 00:01`"):
        page_checks.n6(run)


def test_n6_fails_when_generated_at_has_no_zone(tmp_path):
    run = _n6_run(tmp_path, "2026-10-21T16:01:32.746332", "待核實")
    with pytest.raises(page_checks.Fail, match="沒有時區"):
        page_checks.n6(run)


def test_news_source_label_matches_the_frontend():
    presentation = (ROOT / "frontend" / "src" / "presentation.ts").read_text(
        encoding="utf-8"
    )
    for label in (
        "公開資訊觀測站公告",
        "櫃買中心官方資料",
        "證交所官方資料",
        "官方公告資料",
    ):
        assert f"'{label}'" in presentation
    assert page_checks.news_source_label("MOPS") == "公開資訊觀測站公告"
    assert page_checks.news_source_label("mops_material") == "公開資訊觀測站公告"
    assert page_checks.news_source_label("tpex_news") == "櫃買中心官方資料"
    assert page_checks.news_source_label(None) == "官方公告資料"


def test_status_summary_leaves_out_the_evidence():
    results = [
        page_checks.Result("actions", "A2", "通過", "庫存 2330 台積電 100 股"),
        page_checks.Result("actions", "A3", "失敗", "預期 X，實際 Y"),
    ]
    full = page_checks.summary_markdown(results, ["actions"], "## head")
    status = page_checks.summary_markdown(results, ["actions"], "## head", False)
    assert "台積電" in full and "預期 X" in full
    assert "台積電" not in status and "預期 X" not in status
    assert "### 行動 `/actions`：失敗" in status
    assert "| A2 | 通過 |" in status and "| A3 | 失敗 |" in status
