"""tools/verify/page_checks.py, the CI checks of the five main pages (Issue #243).

The features labels must match the implemented checks (a check labeled CI in
features/*.md without code, or code without a CI label, fails).  The checks
themselves run on hand-written page text and API payloads; the CI ``verify``
job runs them on real screenshots of the fixture database.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date, datetime
from types import SimpleNamespace
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
    features = _features_with(tmp_path, "themes", "| G99 | 新檢查 | 某條件 |")
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == ["themes.md G99: 類型 is '新檢查', not CI or 人工"]


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


# The 1280 list (#510): the navbar's 今日名單 link, the section title (no eyebrow), then rows
# whose title line starts `#<rank> <symbol> <name>`, then the opened detail.
TODAY_CANDIDATES = (
    "今日名單\n我的追蹤\n"
    "今日名單\n資料 2026/10/16\n2 檔\n2026/10/16 收盤後條件成立\n策略說明 →\n"
    "#1 9100 示範一 上市 · 半導體（產業 #1）\n突破型\n2026/10/16 收盤已突破 21.10 元\n"
    "收盤（元）\n21.10\n+0.48%\nRR\n1.60 倍\nAI 推論 ▸\n"
    "AI 進出點說明\nAI 推論\n"
    + page_checks.CANDIDATE_DISCLAIMER
    + "\n來源：訊號 a（推論）\n"
    "#2 9101 示範二 上櫃 · 無所屬族群\n回踩型\n2026/10/16 已拉回到支撐區\n"
    "收盤（元）\n13.20\n漲跌待核實\nRR\n1.60 倍\nAI 說明 ▸\n"
    "AI 進出點說明\nAI 推論\n"
    + page_checks.CANDIDATE_DISCLAIMER
    + "\n來源：訊號 b（推論）\n"
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


def test_t7_fails_on_the_old_candidate_rows(tmp_path):
    # Before #493 the rank was a cell of its own (`#1<TAB>9100 …`), and before #276 a card
    # (`#1` on a line of its own); neither is a 今日名單 row.
    for old in ("\t", "\n"):
        page = TODAY_CANDIDATES.replace("#1 ", "#1" + old).replace("#2 ", "#2" + old)
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


def test_t7_reads_the_section_title_not_the_navbar_link(tmp_path):
    # #493: the navbar 今日名單 comes first; the date must follow the section title.
    page = TODAY_CANDIDATES.replace("我的追蹤\n今日名單\n", "我的追蹤\n", 1)
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": page},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    with pytest.raises(page_checks.Fail, match="`今日名單` 下一行是 '我的追蹤'"):
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


# The 1280 hot groups card (#510): one head line, the date and the returns note once, then
# five rows of two lines (`#n`, the name, the score; the returns).
def _board(count=6):
    return {
        "meta": {"trading_date": "2026-10-16"},
        "items": [{"display_name": f"族群{n}"} for n in range(1, count + 1)],
    }


TODAY_GROUPS = (
    "熱門族群\n產業\n題材\n完整排行 →\n資料 2026/10/16\n"
    + page_checks.GROUP_RETURNS_NOTE
    + "\n"
    + "".join(
        f"#{n}\n族群{n}\n分數 8{n}.00\n1 日 +0.10% 5 日 +1.00% 20 日 +2.00%\n"
        for n in range(1, 6)
    )
    + page_checks.FOOTER_FIRST_LINE
    + "\n"
)


def test_t5_passes_on_the_five_two_line_rows(tmp_path):
    run = FakeRun(
        tmp_path,
        {"themes?board=industry&limit=5": _board()},
        {"today-1280": TODAY_GROUPS},
    )
    assert page_checks.t5(run).startswith("5 列（`#n` 與名稱）= items 前 5 名")


def test_t5_fails_on_a_missing_note_or_a_row_out_of_order(tmp_path):
    payloads = {"themes?board=industry&limit=5": _board()}
    no_note = TODAY_GROUPS.replace(page_checks.GROUP_RETURNS_NOTE + "\n", "")
    run = FakeRun(tmp_path, payloads, {"today-1280": no_note})
    with pytest.raises(
        page_checks.Fail, match="缺整行 `1／5／20 日為相對加權指數的報酬`"
    ):
        page_checks.t5(run)
    swapped = TODAY_GROUPS.replace("#1\n族群1\n", "#1\n族群2\n", 1)
    run = FakeRun(tmp_path, payloads, {"today-1280": swapped})
    with pytest.raises(page_checks.Fail, match="`熱門族群` 列 \\['族群2', '族群2'"):
        page_checks.t5(run)


def test_t7_fails_when_the_page_drops_the_candidates(tmp_path):
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": "今日名單\n資料 2026/10/16\n2 檔\n"},
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
            "scope": "twse_all_securities",
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
            "turnover": {
                "value": 225545000000,
                "scope": "tpex_stocks",
                "scope_label": "上櫃股票",
            },
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
# The market page (/market, Issue 549): the overview block's title, date badge and 資料說明, then the widgets.
OVERVIEW_PAGE = (
    "大盤\n上市、上櫃的收盤概況與加權指數走勢。\n大盤概況\n資料 2026/10/22\n資料說明\n"
    "成交金額範圍：上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票\n"
    "加權指數\n點\n46,041.43\n-846.34（-1.81%）\n"
    "櫃買指數\n點\n381.69\n-13.73（-3.47%）\n"
    "成交金額\n億元\n上市 9,334.37 集中市場總計\n上櫃 2,255.45 上櫃股票\n"
    "漲跌家數（股票）\n括號為漲停／跌停\n"
    "上市 上漲 247 · 下跌 756 · 平盤 74（3／5）\n"
    "上櫃 上漲 146 · 下跌 659 · 平盤 63（17／11）\n"
)


def test_t11_passes_when_the_widgets_show_the_api_and_db_values(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"market-1280": OVERVIEW_PAGE},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    assert "TWSE 46,041.43、TPEx 381.69" in page_checks.t11(run)


def test_t11_fails_on_a_widget_that_differs_from_the_api(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"market-1280": OVERVIEW_PAGE.replace("上市 9,334.37", "上市 9,334.38")},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    with pytest.raises(
        page_checks.Fail, match="TWSE 缺整行 `上市 9,334.37 集中市場總計`"
    ):
        page_checks.t11(run)


def test_t11_fails_on_an_api_value_that_differs_from_the_db(tmp_path):
    facts = {"TWSE": _summary(advancers=248), "TPEx": TPEX_SUMMARY}
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"market-1280": OVERVIEW_PAGE},
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
        .replace("上櫃 2,255.45 上櫃股票", "上櫃大盤資料未取得")
    )
    facts = {"market_summary_latest": {"TWSE": _summary()}}
    run = FakeRun(
        tmp_path, {"dashboard": _overview("unavailable")}, {"market-1280": page}, facts
    )
    assert "TPEx 未取得" in page_checks.t11(run)
    facts = {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}}
    run = FakeRun(
        tmp_path, {"dashboard": _overview("unavailable")}, {"market-1280": page}, facts
    )
    with pytest.raises(
        page_checks.Fail,
        match="TPEx 為 unavailable，但 DB market_summaries 有 2026-10-22 的列",
    ):
        page_checks.t11(run)


def test_fixed_rounds_like_the_page():
    # formatFixed rounds with JS toFixed: the exact binary value, a tie away from
    # zero. Python round() keeps a tie even (1.125 -> 1.12) and would fail T11.
    assert page_checks.fixed(1.125, 2) == "1.13"
    assert page_checks.fixed(-1.125, 2, True) == "-1.13"
    assert page_checks.fixed(1234.5, 0) == "1,235"
    assert page_checks.fixed(2.675, 2) == "2.67"  # 2.67499999… in binary, as toFixed
    assert page_checks.fixed(0.004, 2, True) == "0.00"  # rounds to zero: no sign


def test_t11_passes_on_a_change_that_rounds_at_a_half(tmp_path):
    overview = _overview()
    twse = overview["market_overview"]["exchanges"][0]
    twse["index"] = {"close": 46041.43, "change": 1.125, "change_pct": 0.0000244}
    page = OVERVIEW_PAGE.replace("-846.34（-1.81%）", "+1.13（0.00%）")
    run = FakeRun(
        tmp_path,
        {"dashboard": overview},
        {"market-1280": page},
        {
            "market_summary_latest": {
                "TWSE": _summary(index_change=1.125),
                "TPEx": TPEX_SUMMARY,
            }
        },
    )
    assert "TWSE 46,041.43" in page_checks.t11(run)


def test_t11_fails_on_the_old_page_without_an_overview(tmp_path):
    run = FakeRun(
        tmp_path,
        {"dashboard": _overview()},
        {"market-1280": "資料截至\n2026/10/22\nTWSE／TPEx 官方資料\n"},
        {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}},
    )
    with pytest.raises(page_checks.Fail, match="TWSE 缺整行 `46,041.43`"):
        page_checks.t11(run)


def test_t11_reads_the_market_page_and_its_date_badge(tmp_path):
    facts = {"market_summary_latest": {"TWSE": _summary(), "TPEx": TPEX_SUMMARY}}
    # Issue 549: the overview on the today page no longer counts.
    run = FakeRun(
        tmp_path, {"dashboard": _overview()}, {"today-1280": OVERVIEW_PAGE}, facts
    )
    with pytest.raises(page_checks.Undetermined, match="market-1280 未 ready"):
        page_checks.t11(run)
    page = OVERVIEW_PAGE.replace(
        "大盤概況\n資料 2026/10/22", "大盤概況\n資料 2026/10/21"
    )
    run = FakeRun(tmp_path, {"dashboard": _overview()}, {"market-1280": page}, facts)
    with pytest.raises(page_checks.Fail, match="預期日期 badge `資料 2026/10/22`"):
        page_checks.t11(run)


def test_today_shots_include_the_market_page():
    shots = page_checks.today_shots(None)
    # The shared chart of another row is selected through ?index= (Issue 564), at 1280 only.
    assert [(shot.name, shot.path, shot.widths) for shot in shots] == [
        ("today", "/", (1280, 390)),
        ("market", "/market", (1280, 390)),
        ("market-tpex", "/market?index=tpex", (1280,)),
        ("market-tx", "/market?index=tx", (1280,)),
    ]


# The today page's one market line (Issue 549): the two indexes, the date, the link.
SUMMARY_PAGE = (
    "今日名單\n資料 2026/10/22\n資料截至 2026/10/22 · TWSE／TPEx 官方資料 · 官方單日快照\n"
    "大盤\n加權 46,041.43 -1.81%\n櫃買 381.69 -3.47%\n資料 2026/10/22\n看大盤 →\n"
    "條件已成立 · 依評分排序\n今日名單\n資料 2026/10/16\n2 檔\n"
)


def test_t14_passes_on_the_summary_line(tmp_path):
    run = FakeRun(tmp_path, {"dashboard": _overview()}, {"today-1280": SUMMARY_PAGE})
    assert "`加權 46,041.43 -1.81%`" in page_checks.t14(run)


def test_t14_unavailable_and_missing_pct(tmp_path):
    overview = _overview("unavailable")
    overview["market_overview"]["exchanges"][0]["index"]["change_pct"] = None
    page = SUMMARY_PAGE.replace("-1.81%", "—").replace(
        "櫃買 381.69 -3.47%", "櫃買 未取得"
    )
    run = FakeRun(tmp_path, {"dashboard": overview}, {"today-1280": page})
    assert "`櫃買 未取得`" in page_checks.t14(run)


def test_t14_fails_on_a_wrong_value_or_the_old_widgets(tmp_path):
    page = SUMMARY_PAGE.replace("-3.47%", "-3.48%")
    run = FakeRun(tmp_path, {"dashboard": _overview()}, {"today-1280": page})
    with pytest.raises(page_checks.Fail, match="預期 `加權 46,041.43 -1.81%`"):
        page_checks.t14(run)
    page = SUMMARY_PAGE + "漲跌家數（股票）\n括號為漲停／跌停\n"
    run = FakeRun(tmp_path, {"dashboard": _overview()}, {"today-1280": page})
    with pytest.raises(page_checks.Fail, match="仍有大盤概況"):
        page_checks.t14(run)
    # The old page: four widgets and no summary line.
    run = FakeRun(tmp_path, {"dashboard": _overview()}, {"today-1280": OVERVIEW_PAGE})
    with pytest.raises(page_checks.Fail, match="缺整行 `加權 46,041.43 -1.81%`"):
        page_checks.t14(run)


def _taiex_bars(closes):
    """Close-only twse_index rows (開＝高＝低＝收) as the bars API returns them today; None is a suspended day."""

    bars = [
        {
            "date": f"2026-10-{day:02d}",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "is_suspended": close is None,
        }
        for day, close in closes
    ]
    return {
        "count": len(bars),
        "data_as_of": bars[-1]["date"] if bars else None,
        "bars": bars,
    }


TAIEX_PATH = "stocks/TWSE/TAIEX/bars?interval=day&limit=250"
TPEX_PATH = "stocks/TPEx/TPEX/bars?interval=day&limit=250"
TX_PATH = "stocks/TAIFEX/TX/bars?interval=day&limit=250"
ATTRIBUTION = "資料來源：臺灣期貨交易所（政府資料開放平臺，政府資料開放授權條款第1版）"
# One stock-page K-line card per page (decision 6715021190, Issue 552/564): 加權指數 by default with close-only
# rows, the TPEx index selected through ?index= with no bars (no instrument yet: 404), TX with one real bar in whole
# points, then its footer. Each page has the index table before the chart.
TABLE_HEAD = "大盤概況\n資料 2026/10/22\n指數總表\n資料 2026/10/22\n"
TAIEX_PAGE = TABLE_HEAD + (
    "技術指標 indicators/v1\n加權指數日線\n資料 2026/10/22\n日K\n週K\nMA5\n"
    "來源 臺灣證券交易所\n最近 2 根日線；缺日不補、停牌不畫 K 線\n查看圖表資料表（最近 30 根）\n"
    "日期\t開（點）\t高（點）\t低（點）\t收（點）\t成交量（張）\tMA5（點）\n"
    "2026/10/22\t46,041.43\t46,041.43\t46,041.43\t46,041.43\t\t\n"
    "2026/10/21\t46,887.77\t46,887.77\t46,887.77\t46,887.77\t\t\n"
)
TPEX_PAGE = TABLE_HEAD + (
    "技術指標\n櫃買指數日線\n資料日期未提供\n日K\n週K\n無資料\n來源未提供日線\n"
)
TX_PAGE = TABLE_HEAD + (
    "技術指標 indicators/v1\n台指期近月日線\n資料 2026/10/22\n日K\n週K\n"
    "來源 臺灣期貨交易所\n最近 1 根日線；缺日不補、停牌不畫 K 線\n查看圖表資料表（最近 30 根）\n"
    "日期\t開（點）\t高（點）\t低（點）\t收（點）\t成交量（口）\tMA5（點）\n"
    "2026/10/22\t46,100\t46,330\t45,900\t46,272\t55,226\t\n"
    "2026/10/22 合約 2026/11 · 未平倉 115,258 口 · 結算價 46,234\n"
    f"自 2026/10/22 起收集，無更早歷史；近月合約：每月第三個週三（到期日）起改用次月，換月不做價差調整；只含一般交易時段\n{ATTRIBUTION}\n"
)


def _chart_pages(taiex=TAIEX_PAGE, tpex=TPEX_PAGE, tx=TX_PAGE):
    return {"market-1280": taiex, "market-tpex-1280": tpex, "market-tx-1280": tx}


def _payloads(taiex_close=46041.43):
    tx = {
        "date": "2026-10-22",
        "open": 46100,
        "high": 46330,
        "low": 45900,
        "close": 46272,
    }
    return {
        TAIEX_PATH: _taiex_bars([(21, 46887.77), (22, taiex_close)]),
        TX_PATH: {"count": 1, "data_as_of": "2026-10-22", "bars": [tx]},
    }


def test_t15_passes_on_the_shared_chart_of_each_selection(tmp_path):
    run = FakeRun(tmp_path, _payloads(), _chart_pages())
    summary = page_checks.t15(run)
    assert "`2026/10/22\t46,041.43\t46,041.43\t46,041.43\t46,041.43`" in summary
    assert "`櫃買指數日線` `來源未提供日線`" in summary
    assert "`2026/10/22\t46,100\t46,330\t45,900\t46,272`" in summary


def test_t15_fails_on_a_wrong_close_a_missing_chart_or_attribution(tmp_path):
    run = FakeRun(tmp_path, _payloads(46041.44), _chart_pages())
    with pytest.raises(page_checks.Fail, match="資料表缺最新一根"):
        page_checks.t15(run)
    run = FakeRun(
        tmp_path,
        _payloads(),
        _chart_pages(tpex=TPEX_PAGE.replace("櫃買指數日線\n", "")),
    )
    with pytest.raises(page_checks.Fail, match="缺整行 `櫃買指數日線`"):
        page_checks.t15(run)
    page = TX_PAGE.replace(ATTRIBUTION, "資料來源：臺灣期貨交易所")
    run = FakeRun(tmp_path, _payloads(), _chart_pages(tx=page))
    with pytest.raises(page_checks.Fail, match="台指期之後缺整行"):
        page_checks.t15(run)
    # TX in two decimals (an index's format) is not the futures card.
    page = TX_PAGE.replace(
        "46,100\t46,330\t45,900\t46,272", "46,100.00\t46,330.00\t45,900.00\t46,272.00"
    )
    run = FakeRun(tmp_path, _payloads(), _chart_pages(tx=page))
    with pytest.raises(page_checks.Fail, match="`台指期近月日線`：資料表缺最新一根"):
        page_checks.t15(run)
    # The old close-line chart (before the decision) has no stock-page meta line.
    old = TAIEX_PAGE.replace(
        "最近 2 根日線；缺日不補、停牌不畫 K 線", "最近 2 根日線；缺日不補"
    )
    run = FakeRun(tmp_path, _payloads(), _chart_pages(taiex=old))
    with pytest.raises(page_checks.Fail, match="缺整行 `最近 2 根日線"):
        page_checks.t15(run)


def test_t15_fails_on_more_than_one_chart_or_a_chart_before_the_table(tmp_path):
    # The page before Issue 564: three charts on /market.
    page = TAIEX_PAGE + "櫃買指數日線\n台指期近月日線\n"
    run = FakeRun(tmp_path, _payloads(), _chart_pages(taiex=page))
    with pytest.raises(page_checks.Fail, match="只該有 `加權指數日線` 一張圖"):
        page_checks.t15(run)
    # ?index=tx still drawing 加權指數 is a selection the URL did not keep.
    page = TX_PAGE.replace("台指期近月日線", "加權指數日線")
    run = FakeRun(tmp_path, _payloads(), _chart_pages(tx=page))
    with pytest.raises(page_checks.Fail, match="缺整行 `台指期近月日線`"):
        page_checks.t15(run)
    page = TAIEX_PAGE.replace("指數總表\n", "") + "指數總表\n"
    run = FakeRun(tmp_path, _payloads(), _chart_pages(taiex=page))
    with pytest.raises(page_checks.Fail, match="不在 `指數總表` 之後"):
        page_checks.t15(run)


def test_t15_newest_row_skips_a_suspended_day(tmp_path):
    payloads = {
        **_payloads(),
        TAIEX_PATH: _taiex_bars([(21, 46887.77), (22, 46041.43), (23, None)]),
    }
    page = TAIEX_PAGE.replace(
        "加權指數日線\n資料 2026/10/22", "加權指數日線\n資料 2026/10/23"
    ).replace("最近 2 根", "最近 3 根")
    run = FakeRun(tmp_path, payloads, _chart_pages(taiex=page))
    assert "`2026/10/22\t46,041.43" in page_checks.t15(run)


def test_t15_without_bars_needs_the_empty_copy(tmp_path):
    empty = "\n資料日期未提供\n日K\n週K\n無資料\n來源未提供日線\n"
    pages = _chart_pages(
        taiex=f"{TABLE_HEAD}技術指標\n加權指數日線{empty}",
        tx=f"{TABLE_HEAD}技術指標\n台指期近月日線{empty}{ATTRIBUTION}\n",
    )
    run = FakeRun(tmp_path, {TAIEX_PATH: _taiex_bars([])}, pages)
    assert "`加權指數日線` `來源未提供日線`" in page_checks.t15(run)
    run = FakeRun(tmp_path, {TAIEX_PATH: _taiex_bars([])}, _chart_pages())
    with pytest.raises(page_checks.Fail, match="缺整行 `來源未提供日線`"):
        page_checks.t15(run)


# ---- T16: the index table (Issue 564) ----

FRED = "資料來源：FinMind（個人非商業使用）"  # the US attribution, gone from the page (Issue 633)


def _index(key, group, **extra):
    row = {
        "key": key,
        "group": group,
        "status": "available",
        "trading_date": "2026-10-22" if group == "tw" else "2026-10-21",
        "expected_date": "2026-10-22" if group == "tw" else "2026-10-21",
        "freshness": "latest",
        "close": 46041.43,
        "change": -846.34,
        "change_pct": -0.0181,
        "ma60": {
            "status": "available",
            "required_closes": 60,
            "ma60": 44012.5,
            "position": "above",
        },
        "source": {"label": "FRED" if group == "us" else "臺灣證券交易所"},
    }
    row.update(extra)
    return row


def _indexes(**changes):
    rows = [
        _index("taiex", "tw"),
        _index(
            "tpex",
            "tw",
            close=395.42,
            change=2.1,
            change_pct=0.005339,
            trading_date="2026-10-21",
            freshness="stale",
            ma60={"status": "insufficient", "required_closes": 60, "close_count": 42},
            source={"label": "證券櫃檯買賣中心"},
        ),
        _index(
            "tx",
            "tw",
            close=46110,
            change=None,
            change_pct=None,
            change_status="contract_roll",
            contract_month="202611",
            ma60={
                "status": "available",
                "required_closes": 60,
                "ma60": 46502.4,
                "position": "below",
            },
            source={"label": "臺灣期貨交易所"},
        ),
        _index("spx", "us", close=7353.73, change=-334.89, change_pct=-0.043557),
        _index(
            "ixic",
            "us",
            close=24579.42,
            change=264.42,
            change_pct=0.010875,
            ma60={
                "status": "unavailable",
                "required_closes": 60,
                "reason": "indicator_not_computed",
            },
        ),
        _index(
            "dji",
            "us",
            close=51285.73,
            change=-40.25,
            change_pct=-0.000784,
            trading_date="2026-10-20",
            freshness="us_market_closed",
            ma60={
                "status": "available",
                "required_closes": 60,
                "ma60": 51285.73,
                "position": "equal",
            },
        ),
        {
            "key": "sox",
            "group": "us",
            "status": "unavailable",
            "reason": "fetch_failed",
            "last_attempt_date": "2026-10-22",
            "ma60": None,
            "source": {"label": "FRED"},
        },
    ]
    for key, extra in changes.items():
        rows = [{**row, **extra} if row["key"] == key else row for row in rows]
    return {
        "dashboard": {
            "market_overview": {"trading_date": "2026-10-22", "indexes": rows}
        }
    }


US_PAGE_ROW = (
    "S&P 500\t7,353.73\t-334.89\t-4.36%\t2026/10/21\t之上 季線 44,012.50\tFRED\n"
)
# Issue 633: the page lists the three Taiwan rows; the API (_indexes) still has the US rows.
INDEX_PAGE = (
    "大盤概況\n資料 2026/10/22\n指數總表\n資料 2026/10/22\n資料說明\n"
    f"{ATTRIBUTION}\n"
    "指數\t收盤（點）\t漲跌\t漲跌幅\t資料日\t相對季線（MA60）\t來源\n"
    "加權指數\t46,041.43\t-846.34\t-1.81%\t2026/10/22\t之上 季線 44,012.50\t臺灣證券交易所\n"
    "櫃買指數\t395.42\t+2.10\t+0.53%\t2026/10/21 非最新\t資料不足（42／60 日）\t證券櫃檯買賣中心\n"
    "台指期近月 合約 2026/11\t46,110\t換月\t換月\t2026/10/22\t之下 季線 46,502\t臺灣期貨交易所\n"
    "台指期近月 2026/10/22 換月（2026/10 → 2026/11），與前一筆是不同合約，不計漲跌\n"
    "技術指標 indicators/v1\n加權指數日線\n"
)


def test_t16_passes_on_the_index_table(tmp_path):
    run = FakeRun(tmp_path, _indexes(), {"market-1280": INDEX_PAGE})
    summary = page_checks.t16(run)
    assert summary.endswith("；沒有美股列")
    assert (
        "`台指期近月 合約 2026/11\t46,110\t換月\t換月\t2026/10/22\t之下 季線 46,502\t臺灣期貨交易所`"
        in summary
    )
    assert "費城半導體指數" not in summary


def test_t16_fails_on_a_wrong_cell_order_or_a_us_row(tmp_path):
    # MA60 from another value than the API's (AC-3: the page shows the stored ma60).
    page = INDEX_PAGE.replace("之上 季線 44,012.50\t臺灣", "之上 季線 44,012.49\t臺灣")
    run = FakeRun(tmp_path, _indexes(), {"market-1280": page})
    with pytest.raises(page_checks.Fail, match="taiex：缺整行"):
        page_checks.t16(run)
    # A roll day with a blank change instead of its reason (decision 6725073156).
    page = INDEX_PAGE.replace("46,110\t換月\t換月", "46,110\t—\t—")
    run = FakeRun(tmp_path, _indexes(), {"market-1280": page})
    with pytest.raises(page_checks.Fail, match="tx：缺整行"):
        page_checks.t16(run)
    # Rows out of order.
    tx = "台指期近月 合約 2026/11\t46,110\t換月\t換月\t2026/10/22\t之下 季線 46,502\t臺灣期貨交易所\n"
    page = INDEX_PAGE.replace(tx, "").replace(
        "加權指數\t46,041.43", tx + "加權指數\t46,041.43"
    )
    run = FakeRun(tmp_path, _indexes(), {"market-1280": page})
    with pytest.raises(page_checks.Fail, match="tx：缺整行 .*或不在前一列之後"):
        page_checks.t16(run)
    # The table after the chart, or without the attribution in 資料說明.
    page = INDEX_PAGE.replace("技術指標 indicators/v1\n加權指數日線\n", "").replace(
        "大盤概況\n", "大盤概況\n加權指數日線\n"
    )
    run = FakeRun(tmp_path, _indexes(), {"market-1280": page})
    with pytest.raises(
        page_checks.Fail, match="不在 `大盤概況` 與 `加權指數日線` 之間"
    ):
        page_checks.t16(run)
    run = FakeRun(
        tmp_path,
        _indexes(),
        {"market-1280": INDEX_PAGE.replace(f"{ATTRIBUTION}\n", "")},
    )
    with pytest.raises(page_checks.Fail, match="資料說明"):
        page_checks.t16(run)
    # Issue 633: a US row, its group title or its attribution is back on the page.
    for line, shown in (
        (US_PAGE_ROW, "S&P 500"),
        ("美股（前一交易日）\n", "美股（前一交易日）"),
        (f"{FRED}\n", FRED),
    ):
        page = INDEX_PAGE.replace(
            "台指期近月 2026/10/22 換月", line + "台指期近月 2026/10/22 換月"
        )
        run = FakeRun(tmp_path, _indexes(), {"market-1280": page})
        with pytest.raises(page_checks.Fail, match="大盤頁仍有美股的") as error:
            page_checks.t16(run)
        assert f"`{shown}`" in str(error.value)
    run = FakeRun(
        tmp_path,
        {"dashboard": {"market_overview": {"indexes": []}}},
        {"market-1280": INDEX_PAGE},
    )
    with pytest.raises(page_checks.Fail, match="indexes 的台股列是"):
        page_checks.t16(run)


def test_t12_needs_the_candidates_before_groups_and_no_news_card(tmp_path):
    page = "今日名單\n資料 2026/10/16\n熱門族群\n資料 2026/10/16\n"
    run = FakeRun(tmp_path, {}, {"today-1280": page})
    assert "`今日名單`" in page_checks.t12(run)
    run = FakeRun(tmp_path, {}, {"today-1280": "今日名單\n資料 2026/10/16\n"})
    with pytest.raises(page_checks.Fail, match="缺整行 `熱門族群`"):
        page_checks.t12(run)
    swapped = "熱門族群\n今日名單\n"
    run = FakeRun(tmp_path, {}, {"today-1280": swapped})
    with pytest.raises(page_checks.Fail, match="區塊順序 `熱門族群` → `今日名單`"):
        page_checks.t12(run)
    # Issue 625: the news card left the home page.
    run = FakeRun(tmp_path, {}, {"today-1280": page + "重點新聞\n"})
    with pytest.raises(page_checks.Fail, match="首頁仍有整行 `重點新聞`"):
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


MEMBER_HEADER = "代號\t名稱\t市場\t收盤（元）\t漲跌幅（%）\t成交金額（億元）\t5 日相對（%）\t20 日相對（%）\n"
# 9102 has the most turnover, 9101 the highest close, 9201 no turnover.
MEMBERS = [
    {"symbol": "9102", "exchange": "TWSE", "name": "示範封測", "turnover": 5e9},
    {"symbol": "9101", "exchange": "TWSE", "name": "示範晶圓", "turnover": 1e9},
    {"symbol": "9201", "exchange": "TPEx", "name": "示範矽材", "turnover": None},
]
# The 1280 rows as innerText: the stale 9201 has its bar date under the close.
MEMBER_ROWS = {
    "9101": "9101\t示範晶圓 候選 #1\t上市\t1,085.00\t+3.63\t10.00\t+4.50\t+10.00\n",
    "9102": "9102\t示範封測\t上市\t52.30\t-0.24\t50.00\t+3.50\t+8.00\n",
    "9201": "9201\t示範矽材\t上櫃\t25.10\n資料 2026/10/15\t\t\t+2.50\t+6.00\n",
}


def _theme_run(tmp_path, total, pager, items=None, rows=None):
    theme = "official-industry-x"
    items = MEMBERS if items is None else items
    members = {
        "meta": {"total": total, "data_as_of": "2026-10-16"},
        "items": items,
    }
    board = {
        "meta": {"trading_date": "2026-10-16"},
        "items": [{"theme_id": theme, "display_name": "半導體"}],
    }
    rows = [item["symbol"] for item in items] if rows is None else rows
    page = MEMBER_HEADER + "".join(MEMBER_ROWS[symbol] for symbol in rows) + pager
    return FakeRun(
        tmp_path,
        {
            "themes?board=industry&limit=5": board,
            f"themes/{theme}": {"theme": {"display_name": "半導體"}},
            f"themes/{theme}/members?page=1&page_size=30&sort=turnover": members,
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


def test_g6_fails_on_the_old_member_header(tmp_path):
    run = _theme_run(tmp_path, 3, "共 3 檔")
    old = "代號\t名稱\t市場\t角色\t收盤\t資料日期\n"
    run.pages["theme-detail-1280"] = run.pages["theme-detail-1280"].replace(
        MEMBER_HEADER, old
    )
    with pytest.raises(page_checks.Fail, match="缺成員表頭"):
        page_checks.g6(run)


def test_g8_passes_when_the_page_lists_members_by_turnover(tmp_path):
    detail = page_checks.g8(_theme_run(tmp_path, 3, "共 3 檔"))
    assert "9102、9101、9201" in detail


def test_g8_fails_on_the_old_page_sorted_by_close(tmp_path):
    # Before #280 the page asked for sort=price: the highest close came first.
    run = _theme_run(tmp_path, 3, "共 3 檔", rows=["9101", "9102", "9201"])
    with pytest.raises(page_checks.Fail, match="頁面成員順序"):
        page_checks.g8(run)


# Issue 522: the industry board as screenshot.cjs reads it, one list at every width with each
# row's five components opened: `#<rank>`, the name, the extremes, the returns, the score, the
# button, then the components as label and value lines.
G3_ITEMS = [
    {
        "rank": 1,
        "display_name": "水泥",
        "components": {
            "relative_return": 0.968,
            "breadth": 0.97,
            "volume_strength": 0.85,
            "institutional_flow": 0.91,
            "catalyst": 0.3,
        },
        "eligible_members": 7,
        "member_count": 7,
    },
    {
        "rank": 2,
        "display_name": "半導體",
        "components": {
            "relative_return": 0.125,
            "breadth": None,
            "volume_strength": 0.5,
            "institutional_flow": 0,
            "catalyst": 0.94,
        },
        "eligible_members": 70,
        "member_count": 82,
    },
]
G3_ROWS = {
    1: "#1\n水泥\n廣度 97・催化劑 30\n1 日 +2.68%\n5 日 +8.03%\n20 日 +18.25%\n分數 87.62\n五分項 ▾\n"
    "相對報酬\n97\n廣度\n97\n量能\n85\n法人\n91\n催化劑\n30\n成員（檔）\n7／7\n族群詳情 →\n",
    # 0.125 shows 13 (toFixed rounds the tie up), the null breadth 「—」.
    2: "#2\n半導體\n催化劑 94・法人 0\n1 日 -0.12%\n5 日 +1.00%\n20 日 —\n分數 40.10\n五分項 ▾\n"
    "相對報酬\n13\n廣度\n—\n量能\n50\n法人\n0\n催化劑\n94\n成員（檔）\n70／82\n族群詳情 →\n",
}
G3_HEAD = "族群排行\n族群\n產業\n題材\n產業榜 · 共 2 個族群\n資料 2026/11/05\n說明\n"
# Before Issue 522: the 12-column table at 1280 and one card per group at 390.
G3_OLD_WIDE = (
    "產業榜 · 共 2 個族群\n資料 2026/11/05\n"
    "排名\t族群\t分數（0–100）\t相對報酬\t廣度\t量能\t法人\t催化劑\t1 日（%）\t5 日（%）\t20 日（%）\t成員（檔）\n"
    "1\t水泥\n熱門族群\t87.62\t97\t97\t85\t91\t30\t+2.68\t+8.03\t+18.25\t7／7\n"
    "2\t半導體\n熱門族群\t40.10\t13\t—\t50\t0\t94\t-0.12\t+1.00\t—\t70／82\n"
)
G3_OLD_NARROW = "產業榜 · 共 2 個族群\n資料 2026/11/05\n#1\n水泥\n87.62\n熱門族群\n相對報酬\n97\n#2\n半導體\n40.10\n"


def _g3_run(tmp_path, wide, narrow, items=None):
    return FakeRun(
        tmp_path,
        {"themes?board=industry&limit=100": {"items": items or G3_ITEMS, "meta": {}}},
        {"themes-1280": wide, "themes-390": narrow},
    )


def test_g3_passes_on_the_two_line_board(tmp_path):
    page = G3_HEAD + G3_ROWS[1] + G3_ROWS[2]
    detail = page_checks.g3(_g3_run(tmp_path, page, page))
    assert "`#1` → `水泥`" in detail and "`#2` → `半導體`" in detail


def test_g3_fails_on_the_old_table(tmp_path):
    with pytest.raises(page_checks.Fail, match="仍有 `排名\\\\t族群` 表頭"):
        page_checks.g3(_g3_run(tmp_path, G3_OLD_WIDE, G3_OLD_NARROW))


def test_g3_fails_on_the_old_phone_cards(tmp_path):
    page = G3_HEAD + G3_ROWS[1] + G3_ROWS[2]
    with pytest.raises(
        page_checks.Fail,
        match="themes-390.txt `#1` 之後缺 `分數 …` 行|themes-390.txt `#1` 的五分項",
    ):
        page_checks.g3(_g3_run(tmp_path, page, G3_OLD_NARROW))


def test_g3_fails_when_a_component_differs_from_the_api(tmp_path):
    page = G3_HEAD + G3_ROWS[1] + G3_ROWS[2].replace("相對報酬\n13\n", "相對報酬\n12\n")
    with pytest.raises(page_checks.Fail, match="`#2` 的五分項是"):
        page_checks.g3(_g3_run(tmp_path, page, page))


def test_g4_fails_when_the_suggestions_are_back(tmp_path):
    # Issue 627: the themes page dropped the news theme suggestions.
    run = FakeRun(tmp_path, {}, {"themes-1280": "族群榜\n產業榜 · 共 2 個族群\n"})
    assert "沒有新聞題材建議區" in page_checks.g4(run)
    page = "族群榜\n新聞聚合 · AI 推論\n新聞題材建議\n2 個建議\n"
    run = FakeRun(tmp_path, {}, {"themes-1280": page})
    with pytest.raises(page_checks.Fail, match="族群頁仍有 `新聞題材建議`"):
        page_checks.g4(run)


def test_g8_fails_when_the_api_is_not_sorted_by_turnover(tmp_path):
    items = [MEMBERS[1], MEMBERS[0], MEMBERS[2]]
    with pytest.raises(page_checks.Fail, match="不是依成交金額由大到小"):
        page_checks.g8(_theme_run(tmp_path, 3, "共 3 檔", items=items))


def test_g8_needs_a_member_without_turnover_last(tmp_path):
    items = [MEMBERS[2], MEMBERS[0], MEMBERS[1]]
    with pytest.raises(page_checks.Fail, match="不是依成交金額由大到小"):
        page_checks.g8(_theme_run(tmp_path, 3, "共 3 檔", items=items))


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


# ---- T17: the today list's number block at 390 (Issue 608) ----


def _row(rank, scroll=300, client=300, covered=(), clipped=()):
    return {
        "rank": rank,
        "numsScrollWidth": scroll,
        "numsClientWidth": client,
        "covered": list(covered),
        "clipped": list(clipped),
    }


def _t17_run(tmp_path, rows, payload=None, ready=True):
    metas = {"today": {390: {"width": 390, "ready": ready, "candidateRows": rows}}}
    payloads = {"candidates": _candidates() if payload is None else payload}
    return FakeRun(tmp_path, payloads, {}, metas=metas)


def test_t17_passes_when_every_row_fits(tmp_path):
    run = _t17_run(tmp_path, [_row(1), _row(2)])
    assert page_checks.t17(run) == (
        "390：2 列數字區不溢出、不被 AI 按鈕蓋住、沒有超出列邊"
    )


def test_t17_fails_on_the_issue_608_row(tmp_path):
    # The #606 measurement: the block wider than its column, the total under the button, its label cut.
    rows = [
        _row(1, 349, 246, ["dd 76"], ["dt 總分（0–100）"]),
        _row(2, 342, 246, ["dd 74"]),
    ]
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t17(_t17_run(tmp_path, rows))
    assert str(error.value) == (
        "#1 數字區 scrollWidth 349 > clientWidth 246；#1 被 AI 按鈕蓋住：dd 76；"
        "#1 超出列邊被切：dt 總分（0–100）；"
        "#2 數字區 scrollWidth 342 > clientWidth 246；#2 被 AI 按鈕蓋住：dd 74"
    )


def test_t17_needs_every_candidate_measured(tmp_path):
    # The rest of the list is measured too (the screenshot opens its <details>).
    with pytest.raises(
        page_checks.Fail, match=r"量到的候選列 \[1\]，預期依 items \[1, 2\]"
    ):
        page_checks.t17(_t17_run(tmp_path, [_row(1)]))
    old_tool = {"today": {390: {"width": 390, "ready": True}}}
    run = FakeRun(tmp_path, {"candidates": _candidates()}, {}, metas=old_tool)
    with pytest.raises(page_checks.Fail, match="沒有 candidateRows"):
        page_checks.t17(run)


def test_t17_without_candidates_or_a_ready_shot(tmp_path):
    empty = {"status": "success", "trading_date": "2026-10-16", "items": []}
    assert page_checks.t17(_t17_run(tmp_path, [], empty)) == "沒有候選列"
    with pytest.raises(page_checks.Undetermined, match="today-390 未 ready"):
        page_checks.t17(_t17_run(tmp_path, [_row(1), _row(2)], ready=False))


# ---- T19 / G9 / S15: score bars and strength blocks (Issue 654) ----

UP, DOWN = "rgb(239, 68, 68)", "rgb(34, 197, 94)"
TOKENS = {"up": UP, "down": DOWN}


def _bar(label, value, fill=None):
    if value is None:
        return {"kind": "bar", "label": f"{label} 無資料", "score": "none", "fill": None, "hasFill": False, "trackWidth": 72}
    share = value / 100 if fill is None else fill
    return {"kind": "bar", "label": f"{label} {value}（0–100）", "score": str(value), "fill": share, "hasFill": True, "trackWidth": 72}


def _chip(window, text, strength, background=None, opacity=None):
    tone, level = strength.split("-")
    label = f"{window} 日相對加權指數 " + ("無資料" if tone == "none" else text)
    default = {"up": UP, "down": DOWN}.get(tone, "rgb(55, 65, 81)")
    return {
        "kind": "chip",
        "label": label,
        "strength": strength,
        "text": text,
        "background": background or default,
        "opacity": opacity if opacity is not None else page_checks.STRENGTH_OPACITY.get(int(level), 1.0),
    }


def _component(score, items=True):
    return {"score": score, "items": {"x": {}} if items else {}}


def _scored(scores):
    keys = ("technical", "chips", "news_sentiment", "group")
    return {key: _component(score) for key, score in zip(keys, scores)}


def _t19_run(tmp_path, items, ready=True):
    candidates = {"status": "success", "trading_date": "2026-10-16", "items": [{"rank": 1, "components": _scored([0.75, 0.44, None, 1])}]}
    board = {"items": [{"theme_id": "i-1", "display_name": "半導體", "relative_returns": {"1d": 0.012, "5d": -0.0045, "20d": None}}]}
    metas = {"today": {1280: {"width": 1280, "ready": ready, "graphics": {"tokens": TOKENS, "items": items}}}}
    payloads = {"candidates": candidates, "themes?board=industry&limit=5": board}
    return FakeRun(tmp_path, payloads, {}, metas=metas)


T19_ITEMS = [
    _bar("技術", 75),
    _bar("籌碼", 44),
    _bar("新聞情緒", None),
    _bar("族群", 100),
    _chip(1, "+1.20%", "up-2"),
    _chip(5, "-0.45%", "down-1"),
    _chip(20, "—", "none-0", background="rgba(0, 0, 0, 0)"),
]


def test_want_chip_steps_follow_the_shown_two_decimals():
    cases = [
        (0.004, "+0.40%", "up-1"),
        (0.00999, "+1.00%", "up-2"),
        (-0.0299, "-2.99%", "down-2"),
        (0.03, "+3.00%", "up-3"),
        (-0.06, "-6.00%", "down-4"),
        (0.00004, "0.00%", "flat-0"),
        (-0.00004, "0.00%", "flat-0"),
        (None, "—", "none-0"),
    ]
    for value, text, strength in cases:
        chip = page_checks.want_chip("1 日", value)
        assert (chip["text"], chip["strength"]) == (text, strength), value
    assert page_checks.want_bar("技術", 0.746) == {"label": "技術 75（0–100）", "score": "75", "fill": 0.746}
    assert page_checks.want_bar("族群", None)["fill"] is None


def test_t19_passes_when_bars_and_blocks_match_the_api(tmp_path):
    assert page_checks.t19(_t19_run(tmp_path, T19_ITEMS)) == (
        "4 條分項橫條（1 檔×4）與 3 個報酬色塊（1 族群×3）= API"
    )


@pytest.mark.parametrize(
    ("index", "change", "message"),
    [
        (0, {"fill": 0.375}, "今日名單明細 第 1 條（技術 75（0–100）） 填色比例 0.375，預期 0.750"),
        (2, {"hasFill": True}, "今日名單明細 第 3 條（新聞情緒 無資料） 無資料卻畫了填色"),
        (1, {"score": "0", "label": "籌碼 0（0–100）"}, "今日名單明細 第 2 條（籌碼 44（0–100）） 是 `籌碼 0（0–100）` data-score=0"),
        (4, {"background": DOWN}, f"熱門族群 第 1 個色塊（1 日相對加權指數 +1.20%） 底色 {DOWN}，預期 --color-up {UP}"),
        (5, {"opacity": 0.5}, "熱門族群 第 2 個色塊（5 日相對加權指數 -0.45%） 不透明度 0.5，預期第 1 級 0.16"),
        (4, {"strength": "up-1"}, "熱門族群 第 1 個色塊（1 日相對加權指數 +1.20%） 是 `1 日相對加權指數 +1.20%` up-1 `+1.20%`"),
        (6, {"background": UP}, f"熱門族群 第 3 個色塊（20 日相對加權指數 無資料） 平盤或無資料卻用了漲跌色 {UP}"),
    ],
)
def test_t19_fails_on_a_wrong_fill_hue_or_step(tmp_path, index, change, message):
    items = [dict(item) for item in T19_ITEMS]
    items[index].update(change)
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t19(_t19_run(tmp_path, items))
    assert str(error.value) == message


def test_t19_needs_the_measurement_and_every_graphic(tmp_path):
    with pytest.raises(page_checks.Fail, match="今日名單明細 有 3 條分數橫條，預期 4 條"):
        page_checks.t19(_t19_run(tmp_path, T19_ITEMS[1:]))
    run = _t19_run(tmp_path, T19_ITEMS)
    run.metas = {"today": {1280: {"width": 1280, "ready": True}}}
    with pytest.raises(page_checks.Fail, match="today-1280 沒有 graphics 量測"):
        page_checks.t19(run)
    with pytest.raises(page_checks.Undetermined, match="today-1280 未 ready"):
        page_checks.t19(_t19_run(tmp_path, T19_ITEMS, ready=False))


def _board_item(theme_id, components, returns):
    keys = ("relative_return", "breadth", "volume_strength", "institutional_flow", "catalyst")
    return {"theme_id": theme_id, "display_name": theme_id, "components": dict(zip(keys, components)), "relative_returns": dict(zip(("1d", "5d", "20d"), returns))}


def test_g9_checks_both_boards_and_the_detail(tmp_path):
    industry = _board_item("i-1", (0.9, 0.75, None, 0.25, 1), (0.012, 0, 0.08))
    theme = _board_item("t-1", (0.4, 0.25, 0.1, 0.9, None), (-0.031, 0.051, None))
    row_bars = [_bar("相對報酬", 90), _bar("廣度", 75), _bar("量能", None), _bar("法人", 25), _bar("催化劑", 100)]
    row_chips = [_chip(1, "+1.20%", "up-2"), _chip(5, "0.00%", "flat-0"), _chip(20, "+8.00%", "up-4")]
    theme_items = [
        _chip(1, "-3.10%", "down-3"), _chip(5, "+5.10%", "up-3"), _chip(20, "—", "none-0", background="rgba(0, 0, 0, 0)"),
        _bar("相對報酬", 40), _bar("廣度", 25), _bar("量能", 10), _bar("法人", 90), _bar("催化劑", None),
    ]

    def meta(items):
        return {1280: {"width": 1280, "ready": True, "graphics": {"tokens": TOKENS, "items": items}}}

    payloads = {
        "themes?board=industry&limit=5": {"items": [industry]},
        "themes?board=industry&limit=100": {"items": [industry]},
        "themes?board=theme&limit=100": {"items": [theme]},
        "themes/i-1": {"board": "industry", "theme": {"metrics": {}}},
    }
    metas = {"themes": meta(row_chips + row_bars), "themes-theme": meta(theme_items), "theme-detail": meta(row_bars + row_chips)}
    run = FakeRun(tmp_path, payloads, {}, metas=metas)
    assert page_checks.g9(run) == "industry 1 列、theme 1 列與詳情 `i-1`：五分項橫條與 1／5／20 日色塊 = API"
    metas["theme-detail"] = meta(row_bars[:4] + [_bar("催化劑", 100, fill=0.5)] + row_chips)
    with pytest.raises(page_checks.Fail, match=r"theme-detail-1280 第 5 條（催化劑 100（0–100）） 填色比例 0.5，預期 1.000"):
        page_checks.g9(FakeRun(tmp_path, payloads, {}, metas=metas))


def test_s15_bars_follow_the_candidate_components(tmp_path):
    stock = page_checks.Stock("TWSE", "9101")
    components = _scored([0.75, 0.44, 0.92, None])
    components["group"]["items"] = {}  # no sub-items: ScoreDetails draws no title row for it
    payloads = {"stocks/TWSE/9101": {"candidate": {"components": components}}}

    def run(items):
        metas = {"stock-research": {1280: {"width": 1280, "ready": True, "graphics": {"tokens": TOKENS, "items": items}}}}
        return FakeRun(tmp_path, payloads, {}, metas=metas)

    assert page_checks.s15(run([_bar("技術", 75), _bar("籌碼", 44), _bar("新聞情緒", 92)]), stock) == "評分細節 3 個分項橫條 = stock.json candidate"
    with pytest.raises(page_checks.Fail, match="有 4 條分數橫條，預期 3 條"):
        page_checks.s15(run([_bar("技術", 75), _bar("籌碼", 44), _bar("新聞情緒", 92), _bar("族群", None)]), stock)
    payloads["stocks/TWSE/9101"] = {"candidate": None}
    assert page_checks.s15(run([]), stock) == "不是每日候選：研究條件分頁沒有分數橫條"

# ---- T18: the rows' sparkline closes (Issue 653) ----


def _with_closes(tmp_path, *recents, closes_on_day=(21.1, 13.2)):
    payload = _candidates(len(recents))
    for item, recent, close in zip(payload["items"], recents, closes_on_day):
        item["market"] = {"close": close}
        if recent is not None:
            item["recent_closes"] = recent
    return FakeRun(tmp_path, {"candidates": payload}, {})


def test_t18_passes_on_closes_that_end_at_the_list_date(tmp_path):
    run = _with_closes(
        tmp_path,
        {
            "dates": ["2026-10-14", "2026-10-15", "2026-10-16"],
            "closes": [20.0, None, 21.1],
        },
        {"dates": ["2026-10-15", "2026-10-16"], "closes": [None, 13.2]},
    )
    assert page_checks.t18(run) == (
        "2 列 recent_closes：≤ 30 個交易日、由舊到新、止於 2026-10-16、名單日收盤 = market.close；"
        "1 列有 2 個以上收盤（畫線），缺日 2 個（留空）"
    )


def test_t18_fails_on_closes_the_line_cannot_draw(tmp_path):
    run = _with_closes(
        tmp_path,
        None,
        {
            "dates": ["2026-10-16", "2026-10-15", "2026-10-17"],
            "closes": [13.0, 0, 13.2],
        },
    )
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t18(run)
    assert str(error.value) == (
        "#1 9100 沒有 recent_closes；#2 9101 日期不是由舊到新、不重複；"
        "#2 9101 最後一日 2026-10-17 晚於名單日 2026-10-16；#2 9101 收盤不是正數或 null：[0]"
    )
    wrong = _with_closes(
        tmp_path,
        {"dates": ["2026-10-15", "2026-10-16"], "closes": [20.0, 20.5]},
        {"dates": ["2026-10-16"], "closes": [13.2, 13.3]},
    )
    with pytest.raises(page_checks.Fail) as error:
        page_checks.t18(wrong)
    assert str(error.value) == (
        "#1 9100 名單日收盤 20.5 ≠ market.close 21.1；#2 9101 dates 1 筆、closes 2 筆"
    )


def test_t18_without_candidates(tmp_path):
    empty = {"status": "success", "trading_date": "2026-10-16", "items": []}
    assert page_checks.t18(FakeRun(tmp_path, {"candidates": empty}, {})) == "沒有候選列"



def test_known_failures_do_not_fail_the_run_until_they_pass(tmp_path, monkeypatch):
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("actions", "A5"),
        page_checks.Known("https://example/1", "出現 LLM 推論標記", "2026-11-20"),
    )
    clean = FakeRun(
        tmp_path, {}, {"actions-1280": "我的庫存\n2330\t2026/10/22\t策略總表 →\n"}
    )
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


# ---- KNOWN_FAILURES expire (#311) ----

ISSUE = "https://github.com/YiCheng0608/stock-lab/issues/311"
PAGE_CHECKS = "tools/verify/page_checks.py"


def _entry_sources(text: str) -> dict[tuple[str, str], str]:
    """(page, code) -> the source of its ``Known(...)`` in KNOWN_FAILURES."""

    for node in ast.parse(text).body:
        target = (
            getattr(node, "target", None)
            or (getattr(node, "targets", None) or [None])[0]
        )
        if getattr(target, "id", None) == "KNOWN_FAILURES":
            return {
                ast.literal_eval(key): ast.get_source_segment(text, value)
                for key, value in zip(node.value.keys, node.value.values)
            }
    raise AssertionError("KNOWN_FAILURES not found")


def _added(source: str) -> date:
    """The day of the commit that added ``source`` to page_checks.py; today when uncommitted."""

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8", check=True
        ).stdout

    if source not in git("show", f"HEAD:{PAGE_CHECKS}"):
        return datetime.now(page_checks.TAIPEI).date()
    day = git("log", "-1", "--format=%cs", "-S", source, "--", PAGE_CHECKS).strip()
    return date.fromisoformat(day)


def test_known_failures_expire_within_30_days_of_the_commit_that_added_them():
    sources = _entry_sources((ROOT / PAGE_CHECKS).read_text(encoding="utf-8"))
    assert sources.keys() == page_checks.KNOWN_FAILURES.keys()
    assert (
        page_checks.known_problems(
            page_checks.KNOWN_FAILURES, lambda key: _added(sources[key])
        )
        == []
    )


def test_an_entry_is_read_from_the_source_and_dated_today_until_committed():
    text = (
        "KNOWN_FAILURES: dict[tuple[str, str], Known] = {\n"
        '    ("today", "T5"): Known(\n'
        f'        "{ISSUE}", "缺新聞標題整行", "2026-11-20"\n'
        "    ),\n"
        "}\n"
    )
    (source,) = _entry_sources(text).values()
    assert source.startswith("Known(") and source.endswith(")")
    assert _added(source) == datetime.now(page_checks.TAIPEI).date()
    # Committed text gets the day of the commit that added it.
    committed = "KNOWN_FAILURES: dict[tuple[str, str], Known] = {}"
    assert _added(committed) <= datetime.now(page_checks.TAIPEI).date()


def test_known_requires_expires():
    with pytest.raises(TypeError):
        page_checks.Known(ISSUE, "缺新聞標題整行")


def test_known_problems_flag_a_missing_or_late_expires():
    def problems(entry, key=("today", "T5")):
        return page_checks.known_problems({key: entry}, lambda key: date(2026, 10, 28))

    assert page_checks.known_problems({}, lambda key: date(2026, 10, 28)) == []
    assert problems(page_checks.Known(ISSUE, "缺新聞標題整行", "2026-11-27")) == []
    assert problems(page_checks.Known(ISSUE, "缺新聞標題整行", "2026-10-28")) == []
    assert problems(SimpleNamespace(issue=ISSUE, match="缺新聞標題整行")) == [
        "KNOWN_FAILURES today T5：缺 expires 或不是 YYYY-MM-DD（None）"
    ]
    assert problems(page_checks.Known(ISSUE, "缺新聞標題整行", "2026-11-28")) == [
        "KNOWN_FAILURES today T5：expires 2026-11-28 要在加入日 2026-10-28 起 30 天內"
    ]
    assert problems(page_checks.Known(ISSUE, "缺新聞標題整行", "2026-10-27")) == [
        "KNOWN_FAILURES today T5：expires 2026-10-27 要在加入日 2026-10-28 起 30 天內"
    ]
    assert problems(page_checks.Known(ISSUE, "缺新聞標題整行", "2026/11/20")) == [
        "KNOWN_FAILURES today T5：缺 expires 或不是 YYYY-MM-DD（'2026/11/20'）"
    ]
    assert problems(page_checks.Known("#233", "", "2026-11-20"), ("today", "T99")) == [
        "KNOWN_FAILURES today T99：不是 CHECKS 裡的檢查",
        "KNOWN_FAILURES today T99：issue 要是 stock-lab 的 Issue 連結",
        "KNOWN_FAILURES today T99：缺 match",
    ]


def _a5_known(monkeypatch, expires):
    monkeypatch.setitem(
        page_checks.KNOWN_FAILURES,
        ("actions", "A5"),
        page_checks.Known(ISSUE, "出現 LLM 推論標記", expires),
    )
    monkeypatch.setitem(page_checks.CHECKS, "actions", {"A5": page_checks.a5})


def test_an_expired_known_failure_fails_as_usual(tmp_path, monkeypatch):
    # FakeRun runs on 2026-10-24 (Taipei): the entry counts through its expires day.
    marked = FakeRun(tmp_path, {}, {"actions-1280": "AI 推論\n"})
    _a5_known(monkeypatch, "2026-10-24")
    (known,) = page_checks.run_page(marked, "actions", [])
    assert (known.status, known.failed, known.known) == ("失敗（已知）", False, ISSUE)
    _a5_known(monkeypatch, "2026-10-23")
    (expired,) = page_checks.run_page(marked, "actions", [])
    assert (expired.status, expired.failed, expired.known) == ("失敗", True, None)
    assert expired.detail.endswith(f"（已知失敗 {ISSUE} 已於 2026-10-23 到期）")
    clean = FakeRun(
        tmp_path, {}, {"actions-1280": "我的庫存\n2330\t2026/10/22\t策略總表 →\n"}
    )
    (passing,) = page_checks.run_page(clean, "actions", [])
    assert (passing.status, passing.failed) == ("通過", False)
    assert passing.detail.endswith("；KNOWN_FAILURES 的 actions A5 已到期，移除")


def test_page_checks_exits_1_on_an_expired_known_failure(tmp_path, monkeypatch):
    marked = FakeRun(tmp_path, {}, {"actions-1280": "AI 推論\n"})
    monkeypatch.setattr(page_checks, "Run", lambda *args: marked)
    monkeypatch.setattr(page_checks, "stocks_for", lambda run, fixture: [])
    monkeypatch.setattr(page_checks, "prefetch", lambda *args: None)
    monkeypatch.setattr(page_checks, "write_samples", lambda run, pages: [])
    monkeypatch.setattr(page_checks, "registry_problems", lambda *args: [])
    argv = ["--api", "http://api", "--web", "http://web", "--db", str(tmp_path / "db")]
    argv += ["--out", str(tmp_path / "out"), "--pages", "actions"]
    _a5_known(monkeypatch, "2026-10-24")
    assert page_checks.main(argv) == 0
    _a5_known(monkeypatch, "2026-10-23")
    assert page_checks.main(argv) == 1


AI_DONE = {"status": "done", "inference": True, "impact_direction": "positive"}


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


def test_display_title_matches_the_frontend_cases():
    """#523: the same cases the frontend news test runs through cleanNewsLead."""

    cases = json.loads(
        (ROOT / "frontend" / "src" / "news" / "newsLead.cases.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    assert len(cases) >= 20
    wrong = [
        (case["why"], page_checks.display_title(case["input"]), case["output"])
        for case in cases
        if page_checks.display_title(case["input"]) != case["output"]
    ]
    assert wrong == []
    assert page_checks.display_title(None) == "標題未提供"


def _n2_run(tmp_path, domestic_page):
    items = [{"id": "1", "title": "■ 台積電狠甩英特爾"}]
    empty = {
        "news-international-1280": "目前沒有符合條件的國際新聞。\n",
        "news-official-1280": "目前沒有符合條件的官方公告。\n",
    }
    return FakeRun(
        tmp_path,
        {
            "news?category=domestic&limit=20": {"items": items},
            "news?category=international&limit=20": {"items": []},
            "news?source_kind=official_disclosure&limit=20": {"items": []},
        },
        {"news-1280": domestic_page, **empty},
    )


def test_n2_reads_the_cleaned_title(tmp_path):
    # #523: the page drops the leading ■; the API keeps the source title.
    page = "新聞\n台積電狠甩英特爾\n可能正向\nAI 推論\nYahoo奇摩股市\n·\n發布於 2026/11/05 23:49\n展開\n"
    assert "domestic 前 1 則" in page_checks.n2(_n2_run(tmp_path, page))
    raw = page.replace("台積電狠甩英特爾", "■ 台積電狠甩英特爾")
    with pytest.raises(page_checks.Fail, match="缺 `台積電狠甩英特爾`"):
        page_checks.n2(_n2_run(tmp_path, raw))


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
    assert "### 我的追蹤 `/watch`：失敗" in status
    assert "| A2 | 通過 |" in status and "| A3 | 失敗 |" in status


# ---- A18: /watch is 我的追蹤 and /actions redirects there (#493) ----

WATCH_PAGE = "今日名單\n我的追蹤\n族群\n追蹤與提醒\n我的追蹤\n我的庫存\n"


def _a18_run(tmp_path, final_url, legacy_page=WATCH_PAGE):
    metas = {"actions-legacy": {1280: {"width": 1280, "ready": True}}}
    if final_url is not None:
        metas["actions-legacy"][1280]["finalUrl"] = final_url
    return FakeRun(
        tmp_path,
        {},
        {"actions-1280": WATCH_PAGE, "actions-legacy-1280": legacy_page},
        metas=metas,
    )


def test_a18_passes_when_actions_lands_on_watch_with_query_and_anchor(tmp_path):
    run = _a18_run(tmp_path, "http://127.0.0.1:4173/watch?from=legacy#plan-0")
    assert "轉到 `/watch?from=legacy#plan-0`" in page_checks.a18(run)


@pytest.mark.parametrize(
    "final_url",
    [
        # The pre-#493 app rendered the page at /actions itself: same text, no redirect.
        "http://127.0.0.1:4173/actions?from=legacy#plan-0",
        "http://127.0.0.1:4173/watch",
        "http://127.0.0.1:4173/watch?from=legacy",
    ],
)
def test_a18_fails_when_the_redirect_drops_the_url_or_does_not_happen(
    tmp_path, final_url
):
    with pytest.raises(page_checks.Fail, match=r"預期 `/watch\?from=legacy#plan-0`"):
        page_checks.a18(_a18_run(tmp_path, final_url))


def test_a18_fails_without_the_landing_url_or_on_a_404(tmp_path):
    with pytest.raises(page_checks.Fail, match="沒有 finalUrl"):
        page_checks.a18(_a18_run(tmp_path, None))
    with pytest.raises(page_checks.Fail, match="`/actions` 是找不到此頁"):
        page_checks.a18(
            _a18_run(tmp_path, "http://x/watch", "找不到此頁。\n回到今日名單\n")
        )


# ---- stock page summary card and strategy board (#519) ----

STOCK = page_checks.Stock("TWSE", "2884")
OBSERVED_ROW = {
    "label": "突破條件",
    "status": "observation",
    "levels": {"kind": "observation"},
}
PASSED_ROW = {
    "label": "回踩條件",
    "status": "conditional",
    "levels": {"kind": "actionable"},
}


def _stock_payload(board=None, action=None):
    return {"strategy_board": board, "decision_summary": action}


def _summary_page(
    verdict, reason, closest="最接近成立\n突破條件\n觀察\n差：收盤未突破前 20 日高點\n"
):
    # StockSummaryCard as innerText: the three column labels, the date badge beside the first.
    return (
        "2884\n玉山金\n資料 2026/11/05\n來源 臺灣證券交易所\n"
        f"目前判斷\n資料 2026/11/05\n{verdict}\n{reason}\n{closest}"
        "規則價位\n條件未成立・觀察價位\n收盤（元） ≥\n50.20\n完整條件 →\n"
        "走勢\n籌碼\n"
    )


def _s11(tmp_path, payload, page):
    run = FakeRun(tmp_path, {"stocks/TWSE/2884": payload}, {"stock-1280": page})
    return page_checks.s11(run, STOCK)


def test_s11_passes_on_the_candidate_verdict(tmp_path):
    board = {
        "as_of": "2026-11-05",
        "candidate": {"rank": 1, "total_score": 0.814, "strategy": "pullback_v1"},
        "strategies": [OBSERVED_ROW, PASSED_ROW],
    }
    page = _summary_page("條件成立", "每日候選第 1 名 · 總分 81 · 回踩條件")
    result = _s11(
        tmp_path, _stock_payload(board, {"action_state": "conditional_entry"}), page
    )
    assert "摘要卡 `條件成立`：`每日候選第 1 名 · 總分 81 · 回踩條件`" in result


def test_s11_reads_the_gap_reasons_and_the_primary_reason(tmp_path):
    gaps = [
        {"label": "上市（櫃）後只有 41 個交易日，未滿 60 個交易日"},
        {"label": "近 60 個交易日有 3 天官方行情無成交"},
    ]
    action = {"action_state": "data_insufficient", "gap_reasons": gaps}
    payload = _stock_payload({"strategies": [OBSERVED_ROW]}, action)
    reason = "；".join(g["label"] for g in gaps)
    assert reason in _s11(tmp_path, payload, _summary_page("資料不足", reason))
    observed = _stock_payload(
        {"strategies": [OBSERVED_ROW]},
        {
            "action_state": "no_condition",
            "primary_reason": {"label": "回踩條件差 1 項：支撐區"},
        },
    )
    assert "`觀察`" in _s11(
        tmp_path, observed, _summary_page("觀察", "回踩條件差 1 項：支撐區")
    )
    with pytest.raises(page_checks.Fail, match="預期 `回踩條件差 1 項：支撐區`"):
        _s11(tmp_path, observed, _summary_page("觀察", "突破條件差 2 項：價格、量能"))


def test_s11_fails_on_a_wrong_verdict_or_the_old_page(tmp_path):
    payload = _stock_payload(
        {"strategies": [{**PASSED_ROW}]}, {"action_state": "conditional_entry"}
    )
    with pytest.raises(page_checks.Fail, match="預期判斷 `條件成立`"):
        _s11(tmp_path, payload, _summary_page("觀察", "x"))
    # Before #519 the header was followed by the cutoff form and the tabs.
    old = "2884\n玉山金\n資料 2026/11/05\n來源 臺灣證券交易所\n研究截止日期\n走勢\n"
    with pytest.raises(page_checks.Fail, match="缺整行 `目前判斷`"):
        _s11(tmp_path, payload, old)
    no_link = _summary_page("條件成立", "不在這個資料日的每日候選名單").replace(
        "完整條件 →\n", ""
    )
    with pytest.raises(page_checks.Fail, match="缺整行 `完整條件 →`"):
        _s11(tmp_path, payload, no_link)


def test_s11_without_any_judgement_reads_no_data(tmp_path):
    page = _summary_page(
        "無資料", "尚無行動摘要。", closest="最接近成立\n此股尚無策略判定資料。\n"
    ).replace("規則價位\n條件未成立・觀察價位\n收盤（元） ≥\n50.20\n", "")
    assert "`無資料`" in _s11(tmp_path, _stock_payload(), page)


def _board_page(summary_label: bool) -> str:
    summary = (
        "目前判斷\n觀察\n規則價位\n條件未成立・觀察價位\n" if summary_label else ""
    )
    return (
        f"{summary}走勢\n進出場\n策略總表\n資料 2026/11/05\n價位規則 v1\n"
        "突破條件\t\n觀察\t收盤未突破前 20 日高點\n條件未成立・觀察價位\n"
        "回踩條件\t\n成立\t全部達成\n"
    )


def test_s10_counts_only_the_board_observation_labels(tmp_path):
    board = {
        "as_of": "2026-11-05",
        "candidate": None,
        "strategies": [OBSERVED_ROW, PASSED_ROW],
    }
    run = FakeRun(
        tmp_path,
        {"stocks/TWSE/2884": {"strategy_board": board}},
        {"stock-research-1280": _board_page(summary_label=True)},
    )
    assert "觀察價位 1 列" in page_checks.s10(run, STOCK)


# ---- stock page 圖優先 and one set of levels (#648) ----

LEVELS_ROW = {
    "label": "突破條件",
    "status": "conditional",
    "levels": {"kind": "actionable", "invalid_price": 2364.0, "target_1": 2458.0},
}
HEADER = "2884\n玉山金\n資料 2026/11/05\n來源 臺灣證券交易所\n"
CHART = "K 線與技術指標\n資料 2026/11/05\n"
SUMMARY = "目前判斷\n條件成立\n規則價位\n停損（元）\n2,364.00\n2,458.00／2,508.00\n"
TABS = "走勢\n籌碼\n財務\n新聞與公告\n進出場\n資料來源\n"
BOARD = (
    "策略總表\n資料 2026/11/05\n突破型\n"
    "進場、停損與目標價見下方策略總表「突破條件」列。\n"
    "突破條件\t\n成立\t全部達成\t2,400.00\t2,364.00\t2,458.00／2,508.00\n"
    "研究動作\n查看風險提醒與時間\n價位見上方策略總表。\n"
)
MAIN = HEADER + CHART + SUMMARY + TABS + page_checks.CHART_TAB_NOTE + "\n"


def _s14(tmp_path, main, research, board=None):
    payload = {"strategy_board": board or {"strategies": [LEVELS_ROW]}}
    run = FakeRun(
        tmp_path,
        {"stocks/TWSE/2884": payload},
        {"stock-1280": main, "stock-research-1280": research},
    )
    return page_checks.s14(run, STOCK)


def test_s14_passes_on_chart_first_and_one_set_of_levels(tmp_path):
    result = _s14(tmp_path, MAIN, HEADER + CHART + SUMMARY + TABS + BOARD)
    assert "`2,364.00` 1 次" in result and "`2,458.00` 1 次" in result


def test_s14_fails_on_the_old_order_and_the_chart_in_the_tab(tmp_path):
    # Before #648: header, summary card, tabs, then the chart card inside the 走勢 tab.
    old_main = HEADER + SUMMARY + TABS + CHART
    with pytest.raises(page_checks.Fail, match="要在摘要卡 `目前判斷`"):
        _s14(tmp_path, old_main, HEADER + SUMMARY + TABS + BOARD)
    twice = HEADER + CHART + SUMMARY + TABS + CHART + page_checks.CHART_TAB_NOTE
    with pytest.raises(page_checks.Fail, match="有 2 行，預期 1"):
        _s14(tmp_path, twice, HEADER + CHART + SUMMARY + TABS + BOARD)
    with pytest.raises(page_checks.Fail, match="走勢分頁缺整行"):
        _s14(
            tmp_path,
            HEADER + CHART + SUMMARY + TABS,
            HEADER + CHART + SUMMARY + TABS + BOARD,
        )


def test_s14_fails_when_the_research_tab_repeats_the_levels(tmp_path):
    # Before #648: the candidate sentence and the research action's grid repeated the board's set.
    repeated = BOARD.replace(
        "進場、停損與目標價見下方策略總表「突破條件」列。",
        "明天起在 2,400.00 元附近可進場；跌破 2,364.00 元停損，目標 2,458.00 元",
    ).replace("價位見上方策略總表。", "停損（元）\n2,364.00\n目標一（元）\n2,458.00")
    with pytest.raises(page_checks.Fail, match="`2,364.00`（invalid_price）出現 3 次"):
        _s14(tmp_path, MAIN, HEADER + CHART + SUMMARY + TABS + repeated)


def test_s14_without_actionable_levels_checks_the_order_only(tmp_path):
    board = {"strategies": [OBSERVED_ROW]}
    assert "不計次" in _s14(tmp_path, MAIN, HEADER + CHART + SUMMARY + TABS, board)


# ---- stock page 財務 tab (#528) ----

FUNDAMENTAL_ROWS = [
    {
        "period_end": "2026-09-30",
        "fiscal_period": "Q3",
        "announcement_date": "2026-11-05",
        "revenue": 385478.0,
        "eps": -0.52,
        "roe": None,
        "source": "mops_fundamental",
        "data_as_of": "2026-09-30",
    },
    {
        "period_end": "2026-06-30",
        "fiscal_period": "Q2",
        "announcement_date": "2026-10-30",
        "revenue": None,
        "eps": 49.33,
        "roe": None,
        "source": "mops_fundamental",
        "data_as_of": "2026-06-30",
    },
]


def _financials_page(rows_text: str, badge: str = "資料 2026/09/30\n") -> str:
    # StockFundamentalsPanel as innerText: eyebrow, title, badge, 說明, table, source line.
    return (
        "走勢\n籌碼\n財務\n新聞與公告\n財務資料\n季報營收與 EPS\n"
        f"{badge}說明\n期別\t年初至季底累計營收（億元）\t年初至季底累計 EPS（元）\t"
        f"ROE（%）\t可得日\t來源\n{rows_text}來源：公開資訊觀測站 季報\n"
    )


ROWS_TEXT = (
    "2026 年第 3 季\t3.85\t-0.52\t來源未提供\t2026/11/05\t公開資訊觀測站 季報\n"
    "2026 年第 2 季\t來源未提供\t49.33\t來源未提供\t2026/10/30\t公開資訊觀測站 季報\n"
)


def _s12(tmp_path, payload, page):
    run = FakeRun(
        tmp_path, {"stocks/TWSE/2884": payload}, {"stock-financials-1280": page}
    )
    return page_checks.s12(run, STOCK)


def test_s12_passes_when_every_row_matches_the_api(tmp_path):
    payload = {
        "fundamentals": FUNDAMENTAL_ROWS,
        "instrument": {"instrument_type": "stock"},
    }
    result = _s12(tmp_path, payload, _financials_page(ROWS_TEXT))
    assert "2 列與 API 相同" in result
    assert "資料 2026/09/30" in result


def test_s12_fails_on_a_wrong_value_order_or_badge(tmp_path):
    payload = {
        "fundamentals": FUNDAMENTAL_ROWS,
        "instrument": {"instrument_type": "stock"},
    }
    # A missing revenue shown as 0 is not 來源未提供.
    zero = ROWS_TEXT.replace("2 季\t來源未提供", "2 季\t0.00")
    with pytest.raises(page_checks.Fail, match="2026 年第 2 季\t來源未提供"):
        _s12(tmp_path, payload, _financials_page(zero))
    swapped = "\n".join(reversed(ROWS_TEXT.strip().split("\n"))) + "\n"
    with pytest.raises(page_checks.Fail, match="順序"):
        _s12(tmp_path, payload, _financials_page(swapped))
    with pytest.raises(page_checks.Fail, match="缺 `資料 2026/09/30`"):
        _s12(tmp_path, payload, _financials_page(ROWS_TEXT, badge=""))


def test_s12_fails_on_the_old_page_without_the_tab(tmp_path):
    payload = {"fundamentals": [], "instrument": {"instrument_type": "stock"}}
    with pytest.raises(page_checks.Fail, match="缺整行 `季報營收與 EPS`"):
        _s12(tmp_path, payload, "走勢\n籌碼\n新聞與公告\n")


def test_s12_reads_the_empty_reason_by_instrument_type(tmp_path):
    etf = {"fundamentals": [], "instrument": {"instrument_type": "etf"}}
    page = _financials_page("無資料\nETF 沒有公司財報，不適用。\n", badge="")
    assert "ETF 沒有公司財報，不適用。" in _s12(tmp_path, etf, page)
    stock = {"fundamentals": [], "instrument": {"instrument_type": "stock"}}
    with pytest.raises(page_checks.Fail, match="尚未收集到這檔的季報"):
        _s12(tmp_path, stock, page)
    with pytest.raises(page_checks.Fail, match="沒有期別列|卻有期別列"):
        _s12(
            tmp_path,
            etf,
            _financials_page("ETF 沒有公司財報，不適用。\n" + ROWS_TEXT, badge=""),
        )


# ---- stock page 財務 tab: the 月營收 card (#530) ----

MONTHLY_ROWS = [
    {
        "revenue_month": "2026-09",
        "revenue": 511857399.0,
        "yoy": 54.648,
        "announcement_date": "2026-10-12",
        "source": "mops_t21sc03",
        "data_as_of": "2026-09-30",
    },
    {
        "revenue_month": "2026-08",
        "revenue": 514805337.0,
        "yoy": None,
        "announcement_date": "2026-09-10",
        "source": "mops_t21sc03",
        "data_as_of": "2026-08-31",
    },
]
MONTHLY_TEXT = (
    "2026 年 9 月\t5,118.57\t+54.6\t2026/10/12\t公開資訊觀測站 營業收入統計表\n"
    "2026 年 8 月\t5,148.05\t來源未提供\t2026/09/10\t公開資訊觀測站 營業收入統計表\n"
)


def _monthly_page(rows_text: str, badge: str = "資料 2026/09/30\n") -> str:
    # The quarterly card (empty here) and then the 月營收 card, as innerText.
    return _financials_page(
        "無資料\n尚未收集到這檔的季報：官方季報快照與彙總報表都沒有這檔。\n", badge=""
    ) + (
        f"財務資料\n月營收\n{badge}說明\n月份\t營收（億元）\t年增率（%）\t可得日\t來源\n"
        f"{rows_text}來源：公開資訊觀測站 營業收入統計表\n"
    )


def _s13(tmp_path, payload, page):
    run = FakeRun(
        tmp_path, {"stocks/TWSE/2884": payload}, {"stock-financials-1280": page}
    )
    return page_checks.s13(run, STOCK)


def test_s13_passes_when_every_month_matches_the_api(tmp_path):
    payload = {
        "monthly_revenues": MONTHLY_ROWS,
        "instrument": {"instrument_type": "stock"},
    }
    result = _s13(tmp_path, payload, _monthly_page(MONTHLY_TEXT))
    assert "2 個月與 API 相同" in result and "資料 2026/09/30" in result


def test_s13_fails_on_a_wrong_value_order_or_badge(tmp_path):
    payload = {
        "monthly_revenues": MONTHLY_ROWS,
        "instrument": {"instrument_type": "stock"},
    }
    # An unsigned yoy, and a missing yoy shown as 0.
    with pytest.raises(page_checks.Fail, match=r"\+54\.6"):
        _s13(tmp_path, payload, _monthly_page(MONTHLY_TEXT.replace("+54.6", "54.6")))
    with pytest.raises(page_checks.Fail, match="來源未提供"):
        _s13(
            tmp_path, payload, _monthly_page(MONTHLY_TEXT.replace("來源未提供", "0.0"))
        )
    swapped = "\n".join(reversed(MONTHLY_TEXT.strip().split("\n"))) + "\n"
    with pytest.raises(page_checks.Fail, match="順序"):
        _s13(tmp_path, payload, _monthly_page(swapped))
    with pytest.raises(page_checks.Fail, match="缺 `資料 2026/09/30`"):
        _s13(tmp_path, payload, _monthly_page(MONTHLY_TEXT, badge=""))
    with pytest.raises(page_checks.Fail, match="缺整行 `月營收`"):
        _s13(tmp_path, payload, _financials_page(ROWS_TEXT))


def test_s13_reads_the_empty_reason_by_instrument_type(tmp_path):
    etf = {"monthly_revenues": [], "instrument": {"instrument_type": "etf"}}
    page = _monthly_page("", badge="").replace(
        "說明\n月份\t營收（億元）\t年增率（%）\t可得日\t來源\n來源：公開資訊觀測站 營業收入統計表\n",
        "無資料\nETF 不申報月營收，不適用。\n",
    )
    assert "ETF 不申報月營收，不適用。" in _s13(tmp_path, etf, page)
    stock = {"monthly_revenues": [], "instrument": {"instrument_type": "stock"}}
    with pytest.raises(page_checks.Fail, match="尚未收集到這檔的月營收"):
        _s13(tmp_path, stock, page)
    with pytest.raises(page_checks.Fail, match="卻有月份列"):
        _s13(tmp_path, etf, page + MONTHLY_TEXT)


def _s2(tmp_path, rows):
    payload = {
        "items": [
            {"instrument": {"symbol": symbol, "instrument_type": kind}}
            for symbol, kind in rows
        ],
        "meta": {"total": len(rows)},
    }
    page = (
        "代號\t名稱\t交易所\t類型\t最近收盤（元）\t目前研究動作\n"
        + "".join(f"{symbol}\t名稱\n" for symbol, _ in rows)
        + f"第 1／1 頁 · 共 {len(rows)} 筆\n"
    )
    run = FakeRun(
        tmp_path, {"stocks?page=1&page_size=30": payload}, {"stocks-1280": page}
    )
    return page_checks.s2(run, None)


def test_s2_passes_on_the_type_then_symbol_order(tmp_path):
    # #602: stocks first, then ETFs and new listings, each by symbol.
    rows = [("1101", "stock"), ("3105", "stock"), ("0050", "etf"), ("7795", "ipo")]
    assert "類型→代號順序" in _s2(tmp_path, rows)


@pytest.mark.parametrize(
    "rows",
    [
        # The old exchange-then-symbol order put a TPEx bond ETF first.
        [("00679B", "etf"), ("1101", "stock")],
        [("2330", "stock"), ("1101", "stock")],
    ],
)
def test_s2_fails_on_another_order(tmp_path, rows):
    with pytest.raises(page_checks.Fail, match="類型→代號"):
        _s2(tmp_path, rows)
