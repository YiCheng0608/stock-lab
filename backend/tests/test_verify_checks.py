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
    features = _features_with(tmp_path, "today", "| T10 | CI | 新檢查 | 某條件 |")
    problems = page_checks.registry_problems(
        page_checks.feature_checks(features), page_checks.CHECKS
    )
    assert problems == ["today.md T10: labeled CI but not implemented"]


def test_a_manual_check_needs_no_code(tmp_path):
    features = _features_with(tmp_path, "news", "| N7 | 人工 | 摘要合理 | agent 判斷 |")
    labels = page_checks.feature_checks(features)
    assert labels["news"]["N7"] == "人工"
    assert page_checks.registry_problems(labels, page_checks.CHECKS) == []


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
    assert problems == ["actions A5: implemented but actions.md does not label it CI"]


# ---- page text ----


def test_normalize_keeps_tabs_and_collapses_spaces():
    assert page_checks.normalize("  資料　 2026/10/16  ") == "資料 2026/10/16"
    assert page_checks.normalize("排名\t族群\t") == "排名\t族群\t"


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
                "instrument": {"symbol": f"910{n}"},
                "components": {"news_sentiment": {"inference": inference}},
            }
            for n in range(count)
        ],
    }


TODAY_CANDIDATES = (
    "明日候選\n資料 2026/10/16\n2 檔\n"
    "AI 推論\n" + page_checks.CANDIDATE_DISCLAIMER + "\n來源：訊號 a（推論）\n"
    "AI 推論\n" + page_checks.CANDIDATE_DISCLAIMER + "\n來源：訊號 b（推論）\n"
)


def test_t7_and_t8_pass_on_matching_text(tmp_path):
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": TODAY_CANDIDATES},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    assert "來源行 2 = items" in page_checks.t7(run)
    assert "`AI 推論` 2 行" in page_checks.t8(run)


def test_t7_fails_when_the_page_drops_the_candidates(tmp_path):
    run = FakeRun(
        tmp_path,
        {"candidates": _candidates()},
        {"today-1280": "明日候選\n資料 2026/10/16\n2 檔\n"},
        {"candidate_run_latest_trading_date": "2026-10-16"},
    )
    with pytest.raises(page_checks.Fail, match="`來源：` 行 0，items 2"):
        page_checks.t7(run)


def test_t8_fails_without_the_inference_mark(tmp_path):
    page = TODAY_CANDIDATES.replace("來源：訊號 b（推論）", "來源：訊號 b")
    run = FakeRun(tmp_path, {"candidates": _candidates()}, {"today-1280": page})
    with pytest.raises(page_checks.Fail, match="#2 9101 來源行沒有以 `（推論）` 結尾"):
        page_checks.t8(run)


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
            "themes?board=industry&limit=10": board,
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
        page_checks.KNOWN_FAILURES, ("actions", "A5"), "https://example/1"
    )
    clean = FakeRun(tmp_path, {}, {"actions-1280": "我的庫存\n"})
    marked = FakeRun(tmp_path, {}, {"actions-1280": "AI 推論\n"})
    monkeypatch.setitem(page_checks.CHECKS, "actions", {"A5": page_checks.a5})
    (failing,) = page_checks.run_page(marked, "actions", [])
    assert (failing.ok, failing.failed, failing.status) == (
        False,
        False,
        "失敗（已知）",
    )
    (passing,) = page_checks.run_page(clean, "actions", [])
    assert passing.failed and "從 KNOWN_FAILURES 移除 actions A5" in passing.detail


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
