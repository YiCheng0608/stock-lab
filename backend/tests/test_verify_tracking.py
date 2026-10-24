"""verify checks of the user tracking plans (#253): today T11, actions A8-A11.

The page text is written the way the browser's innerText lays out
frontend/src/tracking/TrackingViews.tsx (one line per block, table cells
joined by tabs); the CI ``verify`` job runs the same checks on screenshots of
the fixture database.
"""

from __future__ import annotations

import pytest
from test_verify_checks import FakeRun, _candidates, page_checks

OPEN = "tracking?status=open&page=1&page_size=20"
CLOSED = "tracking?status=closed&page=1&page_size=20"
NOTE = (
    "計畫價位來自建立當日的研究條件；成交與結果是依日線規則的模擬（買賣各 5 bps 滑價、"
    "來回 30 bps 成本假設），不是實際成交，也不統計勝率。實際持股請看「我的庫存」。"
)


def plan(plan_id, status, **values):
    item = {
        "id": plan_id,
        "status": status,
        "open": status in {"pending", "triggered"},
        "plan_date": "2026-10-13",
        "created_at": "2026-10-13T13:00:00+00:00",  # 21:00 Taipei, same day
        "data_quality": "complete",
        "sessions_observed": 0,
        "last_session_date": None,
        "result_return": None,
        "result_comparable": None,
    }
    item.update(values)
    return item


PENDING = plan(
    1, "pending", plan_date="2026-10-16", created_at="2026-10-16T16:30:00+00:00"
)
TRIGGERED = plan(2, "triggered", sessions_observed=2, last_session_date="2026-10-15")
TARGET = plan(
    3,
    "target_hit",
    sessions_observed=2,
    last_session_date="2026-10-15",
    result_return=0.0408364,
    result_comparable=True,
)
EXPIRED = plan(4, "expired", sessions_observed=1, last_session_date="2026-10-14")
DETAIL = {
    "plan": TARGET,
    "sessions": [
        {"session_date": "2026-10-14", "session_no": 1, "status": "active"},
        {"session_date": "2026-10-15", "session_no": 2, "status": "target_1_hit"},
    ],
}
ROWS = {
    1: [],
    2: [
        "2026/10/14\t第 1 日\t已模擬成交\t98.29",
        "2026/10/15\t第 2 日\t已模擬成交\t98.11",
    ],
    3: ["2026/10/14\t第 1 日\t已模擬成交\t71.30", "2026/10/15\t第 2 日\t達標\t74.40"],
    4: ["2026/10/14\t第 1 日\t未觸發\t50.04"],
}


def card(item, status_label, created, *body, conflict=False):
    lines = [
        "上市 · 突破條件",
        f"9{item['id']:03d} 示範",
        status_label,
        "資料 2026/10/16",
        *(["行情有更正，狀態待核對"] if conflict else []),
        "進場區",
        "98.70",
        f"計畫資料日 {item['plan_date'].replace('-', '/')} · 建立 {created}",
        f"第 {item['sessions_observed']}／20 個交易日",
        *body,
        "版本、來源與逐日明細",
        "來源 個股研究條件 · 追蹤規則 plan_tracking_v1",
        *ROWS[item["id"]],
    ]
    return "\n".join(lines)


def page(
    cards_open, cards_closed, *, before="", after="查看個股詳情 →\n資料日 2026/10/16"
):
    return "\n".join(
        [
            "行動中心",
            "我的庫存",
            "記錄來源 本地 · 記錄日期 待核實",
            before,
            "模擬追蹤 · 進行中",
            "追蹤計畫",
            NOTE,
            *cards_open,
            "模擬追蹤 · 已結束",
            "追蹤回看",
            *cards_closed,
            after,
        ]
    )


GOOD = page(
    [
        card(PENDING, "待觸發", "2026/10/17", "尚未模擬成交", "取消追蹤"),
        card(
            TRIGGERED, "已觸發", "2026/10/13", "模擬成交 2026/10/14 98.75", "取消追蹤"
        ),
    ],
    [
        card(
            TARGET,
            "達標",
            "2026/10/13",
            "模擬成交 2026/10/14 71.34",
            "模擬出場 2026/10/15 74.46",
            "模擬報酬 +4.08%",
        ),
        card(
            EXPIRED,
            "到期",
            "2026/10/13",
            "尚未模擬成交",
            "模擬報酬：無法比較（視窗內未模擬成交）",
        ),
    ],
)
PAYLOADS = {
    OPEN: {"items": [PENDING, TRIGGERED]},
    CLOSED: {"items": [TARGET, EXPIRED]},
    "tracking/plans/3": DETAIL,
}


def actions_run(tmp_path, text=GOOD, payloads=PAYLOADS, facts=None):
    return FakeRun(tmp_path, payloads, {"actions-1280": text}, facts)


def test_the_tracking_checks_pass_on_matching_text(tmp_path):
    run = actions_run(tmp_path)
    assert "進行中 2＋已結束 2 張卡" in page_checks.a8(run)
    assert "沒有 `勝率`" in page_checks.a9(run)
    assert "我的庫存 < 追蹤計畫 < 追蹤回看 < 行動卡" in page_checks.a10(run)
    assert "計畫 3 的 2 列 = tracking-plan.json" in page_checks.a11(run)


def test_a8_compares_the_plan_and_creation_dates(tmp_path):
    # The creation date is the Taipei date of created_at (16:30 UTC is the next day).
    text = GOOD.replace("· 建立 2026/10/17", "· 建立 2026/10/16")
    with pytest.raises(
        page_checks.Fail, match="計畫 1 為 .*預期 \\('2026/10/16', '2026/10/17'\\)"
    ):
        page_checks.a8(actions_run(tmp_path, text))


def test_a8_fails_when_the_page_drops_a_card(tmp_path):
    payloads = {**PAYLOADS, OPEN: {"items": [PENDING, TRIGGERED, plan(9, "pending")]}}
    with pytest.raises(
        page_checks.Fail, match="`計畫資料日` 4 行，進行中 3＋已結束 2 筆"
    ):
        page_checks.a8(actions_run(tmp_path, payloads=payloads))


def test_a8_empty_sections_pass_only_without_plans_in_the_db(tmp_path):
    empty = page([page_checks.EMPTY_OPEN_PLANS], [page_checks.EMPTY_CLOSED_PLANS])
    payloads = {OPEN: {"items": []}, CLOSED: {"items": []}}
    assert "進行中 0＋已結束 0" in page_checks.a8(
        actions_run(tmp_path, empty, payloads)
    )
    run = actions_run(tmp_path, empty, payloads, {"tracking_plans_closed": 2})
    with pytest.raises(page_checks.Fail, match="DB tracking_plans_closed 有 2 筆"):
        page_checks.a8(run)


def test_a9_reads_the_status_badge_of_each_card(tmp_path):
    text = GOOD.replace("達標\n資料 2026/10/16", "失效\n資料 2026/10/16")
    with pytest.raises(page_checks.Fail, match="計畫 3 狀態標籤 '失效'，預期 `達標`"):
        page_checks.a9(actions_run(tmp_path, text))


def test_a9_needs_the_simulated_return_of_an_ended_plan(tmp_path):
    with pytest.raises(page_checks.Fail, match="計畫 3 缺整行 `模擬報酬 \\+4.08%`"):
        page_checks.a9(
            actions_run(tmp_path, GOOD.replace("模擬報酬 +4.08%", "模擬報酬 +4.10%"))
        )
    text = GOOD.replace("模擬報酬：無法比較（視窗內未模擬成交）", "")
    with pytest.raises(page_checks.Fail, match="計畫 4 已結束不可比較"):
        page_checks.a9(actions_run(tmp_path, text))


def test_a9_marks_a_transition_conflict(tmp_path):
    conflict = {**TRIGGERED, "data_quality": "transition_conflict"}
    payloads = {**PAYLOADS, OPEN: {"items": [PENDING, conflict]}}
    with pytest.raises(
        page_checks.Fail,
        match="計畫 2 data_quality transition_conflict，`行情有更正，狀態待核對` 沒有",
    ):
        page_checks.a9(actions_run(tmp_path, payloads=payloads))
    text = GOOD.replace(
        card(
            TRIGGERED, "已觸發", "2026/10/13", "模擬成交 2026/10/14 98.75", "取消追蹤"
        ),
        card(
            conflict,
            "已觸發",
            "2026/10/13",
            "模擬成交 2026/10/14 98.75",
            "取消追蹤",
            conflict=True,
        ),
    )
    assert "更正標示" in page_checks.a9(actions_run(tmp_path, text, payloads))


def test_a9_fails_on_a_win_rate_outside_the_note(tmp_path):
    text = GOOD.replace("模擬報酬 +4.08%", "模擬報酬 +4.08%\n勝率 60%")
    with pytest.raises(page_checks.Fail, match="出現 `勝率`"):
        page_checks.a9(actions_run(tmp_path, text))


def test_a10_keeps_positions_plans_and_actions_apart(tmp_path):
    with pytest.raises(page_checks.Fail, match="`記錄來源` 在庫存區外"):
        page_checks.a10(
            actions_run(tmp_path, GOOD + "\n記錄來源 本地 · 記錄日期 待核實")
        )
    with pytest.raises(page_checks.Fail, match="`模擬成交` 在追蹤區外"):
        page_checks.a10(
            actions_run(tmp_path, page([], [], before="模擬成交 2026/10/14 98.75"))
        )
    reordered = GOOD.replace("追蹤計畫\n", "", 1).replace(
        "追蹤回看\n", "追蹤回看\n追蹤計畫\n", 1
    )
    with pytest.raises(page_checks.Fail, match="行序"):
        page_checks.a10(actions_run(tmp_path, reordered))


def test_a11_counts_the_history_rows_of_every_card(tmp_path):
    text = GOOD.replace("\n2026/10/14\t第 1 日\t未觸發\t50.04", "")
    with pytest.raises(page_checks.Fail, match="計畫 4 明細 0 列，sessions_observed 1"):
        page_checks.a11(actions_run(tmp_path, text))
    text = GOOD.replace("2026/10/15\t第 2 日\t達標", "2026/10/15\t第 2 日\t失效")
    with pytest.raises(page_checks.Fail, match="計畫 3 明細"):
        page_checks.a11(actions_run(tmp_path, text))


def test_t11_counts_one_add_or_tracked_line_per_candidate(tmp_path):
    payload = _candidates()
    payload["items"][0]["open_plan_id"] = 1
    payload["items"][1]["open_plan_id"] = None
    good = "明日候選\n已在追蹤\n加入追蹤\n"
    run = FakeRun(tmp_path, {"candidates": payload}, {"today-1280": good})
    assert "`已在追蹤` 1 = open_plan_id" in page_checks.t11(run)
    run = FakeRun(
        tmp_path, {"candidates": payload}, {"today-1280": "加入追蹤\n加入追蹤\n"}
    )
    with pytest.raises(
        page_checks.Fail, match="`已在追蹤` 0 行，open_plan_id 非 null 1 筆"
    ):
        page_checks.t11(run)
    run = FakeRun(tmp_path, {"candidates": payload}, {"today-1280": "加入追蹤\n"})
    with pytest.raises(page_checks.Fail, match="items 2"):
        page_checks.t11(run)
