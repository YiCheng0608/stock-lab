"""The daily Telegram card (backend/worker/notify_card.py, #754).

The page tests read the HTML the card draws; the drawing tests run fake browsers (shell
scripts, Linux: the process group is killed) and, where the image's Chromium is there
(the CI docker job, tools/ci/docker_suite.json), draw a real card.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time
import zlib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from test_notify import CARD_US, MONDAY, US, _us
from worker import notify, notify_card

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="process groups: Linux only")
TAGS = {
    "html",
    "head",
    "meta",
    "style",
    "body",
    "header",
    "section",
    "div",
    "span",
    "h1",
    "h2",
}


class Page(HTMLParser):
    """The card's tags, and the text of each table row (``div.row``) as its cells."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._depth = 0  # inside a row: the open div/span count
        self._cell: list[str] | None = None
        self._cell_depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and "row" in classes:
            self.rows.append([])
            self._depth = 1
            return
        if self._depth:
            self._depth += 1
            if self._depth == 2:  # a cell of the row
                self._cell = []
                self._cell_depth = 2

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if self._depth == self._cell_depth and self._cell is not None:
            self.rows[-1].append("".join(self._cell))
            self._cell = None
        self._depth -= 1

    def handle_data(self, data):
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)


LEVELS = {
    "entry": {"type": "breakout", "low": 233.0, "high": 236.5},
    "stop": 226.0,
    "target_1": 243.5,
    "target_2": 254.5,
    "risk_reward": 1.5,
}
RULES = {"status": "success", "candidate_count": 3, "items": []}


def _pick(rank, symbol="1477", name="聚陽", levels=LEVELS, **extra):
    return {
        "rank": rank,
        "symbol": symbol,
        "name": name,
        "setup_text": "突破",
        "confidence_text": "把握中",
        "levels": levels,
        "levels_text": None if levels else "價位未通過核對，未顯示",
        "corporate_action_on_session": False,
        "reasons": [{"text": "根據收盤創 20 日新高，推論突破格局成形", "refs": []}],
        **extra,
    }


def _view(picks=None, session="2026-09-07", failure=None, status="done"):
    return {
        "status": status,
        "today": MONDAY.isoformat(),
        "session_date": session if status == "done" else None,
        "list_date": "2026-09-04",
        "prompt_version": "ai_list_v1",
        "llm_model": "claude-sonnet-5-5",
        "failure": failure,
        "market": {
            "stance_text": "中性",
            "confidence_text": "把握低",
            "reasons": [{"text": "根據台指期夜盤持平，推論開盤缺乏方向", "refs": []}],
        },
        "sectors": [{"name": "PCB", "direction_text": "可能正向"}],
        "picks": [_pick(1), _pick(2, "9999", "範例", None)] if picks is None else picks,
        "empty_text": None,
    }


def _card(view=None, indexes=US, rules=RULES):
    return notify.content(MONDAY, _view() if view is None else view, indexes, rules)


FAILURE = {"session_date": "2026-09-07", "reason_text": "呼叫逾時"}
TEN = [_pick(n, f"{1000 + n}", f"名{n}") for n in range(1, 11)]


def test_the_card_shows_the_texts_picks_in_its_words():
    """AC-1 (#754, #1146): one Content; the card's picks are the text's, in its words."""

    card = _card(
        _view(
            [_pick(1, corporate_action_on_session=True), _pick(2, "9999", "範例", None)]
        )
    )
    html = notify_card.card_html(card)
    text = notify.text(card)
    for pick in card.ai.picks:
        assert f'<span class="name line">{pick.head}</span>' in html
        assert f"<b>{pick.head}</b>｜{pick.method}" in text
        assert notify_card.esc(pick.levels) in html and pick.levels in text
    assert '<div class="corp line">（除權息，價位以 09/04 為基準）</div>' in html
    page = Page(html)
    page_text = "".join(page.text)
    for word in (
        "AI 名單",
        "AI 推論，未經驗證",
        "（規則名單 3 檔見今日名單頁）",
        "來源 FinMind",
    ):
        assert word in page_text and word in text
    # The US rows: the label, close, change and note of the text's lines.
    lines = text.splitlines()
    for row, cells in zip(card.us.rows, page.rows, strict=True):
        label, close, change, *note = cells
        line = f"{notify.esc(label)}{notify.INDENT}{close}{notify.INDENT}{change}"
        mark = notify.US_MARKS.get(row.tone or "")
        assert (f"{mark} {line}" if mark else line) in lines


def test_the_run_reads_once_for_the_card_and_the_text(monkeypatch):
    """The text and the card of a send come from one ``read`` (``_Run._run``)."""

    source = Path(notify.__file__).read_text(encoding="utf-8")
    run = source[
        source.index("    def _run(") : source.index("    def _remove_old_logs")
    ]
    assert run.count("read(db, self.today)") == 1
    assert "message(db" not in run
    assert "text(card)" in run and "caption(card)" in run and "draw(card)" in run


def test_the_data_texts_are_escaped_on_the_card():
    """AC-1 (#754): no text of the data makes a tag of the page."""

    evil = "<script>alert(1)</script>&<b>"
    indexes = [
        {**_us("SPX", 7561.67, -0.004), "source": {"label": f"{evil} x"}},
        {
            "symbol": "<i>",
            "name": evil,
            "status": "unavailable",
            "reason": "fetch_failed",
        },
    ]
    view = _view([_pick(1, "1234", evil, reasons=[{"text": evil, "refs": []}])])
    view["sectors"] = [{"name": evil, "direction_text": "可能正向"}]
    pages = [
        notify_card.card_html(_card(view, indexes)),
        notify_card.card_html(
            _card(_view(status="missing", failure={**FAILURE, "reason_text": evil}))
        ),
    ]
    for html in pages:
        page = Page(html)
        assert page.tags <= TAGS, page.tags - TAGS
        assert evil in "".join(page.text)
        assert "<script>" not in html and "&lt;script&gt;" in html
    # Nothing outside the file: no URL, the policy forbids any fetch.
    assert "http" not in pages[0].replace("http-equiv", "")
    assert "default-src 'none'" in pages[0]
    text = notify.text(_card(view, indexes))
    assert "<script>" not in text and "&lt;script&gt;" in text


def test_the_caption_says_the_date_count_and_mark():
    assert notify.caption(_card()) == (
        "<b>AI 名單 09/07（一）</b>・2 檔・AI 推論，未經驗證"
    )
    before = _card(_view(session="2026-09-04", failure=FAILURE))
    assert notify.caption(before) == (
        "<b>AI 名單 09/04（五）</b>・09/04 的名單・2 檔・AI 推論，未經驗證"
    )
    none = _card(_view(status="missing", failure=FAILURE))
    assert notify.caption(none) == (
        "<b>AI 名單 09/07（一）</b>・今天的 AI 名單沒有產出（呼叫逾時）"
    )
    assert notify.caption(_card(_view(status="missing"))) == (
        f"<b>AI 名單 09/07（一）</b>・{notify.AI_LIST_MISSING}"
    )
    # No count on a list that is not there (not 「0 檔」).
    assert 'class="count"' not in notify_card.card_html(none)


def test_the_cards_height_follows_its_blocks():
    p = notify_card
    none = _card(_view(status="missing"))
    base = (
        2 * p.PAD
        + p.HEAD_TITLE_H
        + p.HEAD_LINE_H
        + p.HEAD_LINE_H  # 尚無 AI 名單
        + p.GAP
        + p.MORE_H  # the rule list's line
        + p.GAP
        + 2
        + p.US_TITLE_H
        + 4 * p.US_ROW_H
        + p.SOURCE_H
    )
    assert p.card_height(none) == base
    pick = p.AI_LINE_H + p.AI_LEVELS_H + p.AI_REASON_H
    section = (
        p.GAP
        + 2
        + p.AI_TITLE_H
        + p.AI_META_H
        + p.AI_HEAD_H
        + p.AI_REASON_H
        + p.AI_HEAD_H
    )
    done = _card(_view([_pick(1)]))
    assert p.card_height(done) == base - p.HEAD_LINE_H + section + pick
    corp = _card(_view([_pick(1, corporate_action_on_session=True)]))
    assert p.card_height(corp) == p.card_height(done) + p.AI_NOTE_H
    failed = _card(_view([_pick(1)], session="2026-09-04", failure=FAILURE))
    assert p.card_height(failed) == p.card_height(done) + p.HEAD_NOTE_H
    ten = _card(_view(TEN))
    assert p.card_height(ten) == p.card_height(done) + 9 * pick
    # A US row with a note has a second line.
    behind = _card(
        _view([_pick(1)]), [*US[:3], _us("SOX", 1.0, 0.01, "2026-09-03", "stale")]
    )
    assert p.card_height(behind) == p.card_height(done) + 4 * p.US_NOTE_H


# --- drawing ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def private_temp(monkeypatch):
    """Each test its own system temp directory (#754 review 6888784128): the backend job
    runs the suite in parallel, and another worker's drawing must not count here."""

    # A short path in the real temp directory, not tmp_path: Chromium's profile holds a
    # Unix socket, whose path has a limit of about 108 bytes (abort, exit -6).
    temp = Path(tempfile.mkdtemp(prefix="nc-"))
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


def _fake_browser(tmp_path, script: str) -> str:
    path = tmp_path / "browser"
    path.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_no_browser_is_a_reason(monkeypatch):
    monkeypatch.setenv(notify_card.BROWSER_ENV, "/nonexistent/chromium")
    drawn = notify_card.render(_card())
    assert drawn.png is None and drawn.reason == "no_browser"


def test_a_temp_dir_that_cannot_be_made_is_a_reason_not_an_exception(
    tmp_path, monkeypatch
):
    """Review 6888784128 必修 1: a full disk or no write access; the text goes instead."""

    def refused(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", refused)
    drawn = notify_card.render(_card(), browser=_fake_browser(tmp_path, "exit 0"))
    assert drawn.png is None and drawn.reason == "error:OSError"


def test_the_browser_gets_no_token_or_credential(tmp_path):
    environ = {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "TELEGRAM_BOT_TOKEN": "123:x",
        "TELEGRAM_CHAT_ID": "1",
        "GH_TOKEN": "g",
        "CLAUDE_CODE_OAUTH_TOKEN": "c",
    }
    env = notify_card.browser_environment(tmp_path, environ)
    assert env == {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "TMPDIR": str(tmp_path),
    }


@linux_only
@pytest.mark.parametrize(
    "script, reason",
    [
        ("exit 3", "exit_3"),
        ("exit 0", "empty_png"),
        # A file that is no PNG.
        (
            'for a; do case "$a" in --screenshot=*) echo x > "${a#--screenshot=}";;'
            " esac; done",
            "empty_png",
        ),
    ],
)
def test_a_browser_that_fails_is_a_reason_and_leaves_nothing(
    tmp_path, private_temp, script, reason
):
    drawn = notify_card.render(_card(), browser=_fake_browser(tmp_path, script))
    assert drawn.png is None and drawn.reason == reason
    assert os.listdir(private_temp) == []


@linux_only
def test_a_browser_past_the_time_limit_is_killed_with_its_children(
    tmp_path, private_temp
):
    pid_file = tmp_path / "child.pid"
    browser = _fake_browser(tmp_path, f"sleep 60 & echo $! > {pid_file}; wait")
    drawn = notify_card.render(_card(), browser=browser, timeout=1.0)
    assert drawn.png is None and drawn.reason == "timeout"
    assert drawn.seconds < 10
    child = int(pid_file.read_text())
    # The child of the group is gone too (killed, then reaped by its parent's death or
    # tini; at most a zombie). Right after the kill a loaded runner can still show it
    # as R while it dies (CI 2026-11-17 and 2026-11-22), so poll briefly; a child the
    # kill missed sleeps (S) and never gets there.
    deadline = time.monotonic() + 10
    while True:
        try:
            state = Path(f"/proc/{child}/stat").read_text().split()[2]
        except FileNotFoundError:
            state = "gone"
        if state in ("gone", "Z") or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert state in ("gone", "Z")
    assert os.listdir(private_temp) == []


@linux_only
def test_the_browser_gets_the_page_the_size_and_a_profile_in_the_temp_dir(
    tmp_path, private_temp, monkeypatch
):
    """A fake browser that copies its page and environment and writes a tiny PNG."""

    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
    )
    seen = tmp_path / "seen"
    png = notify_card.PNG_SIGNATURE + b"\x00\x00\x00\rIHDR" + (8).to_bytes(4, "big") * 2
    (tmp_path / "tiny.png").write_bytes(png)
    script = (
        f'echo "$@" > {seen}/args; echo "$HOME" > {seen}/home; env > {seen}/env\n'
        'for a; do case "$a" in\n'
        f'  --screenshot=*) cp {tmp_path}/tiny.png "${{a#--screenshot=}}";;\n'
        f'  file://*) cp "${{a#file://}}" {seen}/card.html;;\n'
        "esac; done"
    )
    seen.mkdir()
    drawn = notify_card.render(_card(), browser=_fake_browser(tmp_path, script))
    assert drawn.reason is None and drawn.png == png
    assert (drawn.width, drawn.height) == (8, 8)
    args = (seen / "args").read_text()
    assert (
        f"--window-size={notify_card.WIDTH},{notify_card.card_height(_card())}" in args
    )
    assert f"--user-data-dir={private_temp}/stock-notify-card-" in args
    assert (seen / "home").read_text().startswith(f"{private_temp}/stock-notify-card-")
    assert "TELEGRAM" not in (seen / "env").read_text()
    assert (seen / "card.html").read_text(encoding="utf-8") == notify_card.card_html(
        _card()
    )
    assert os.listdir(private_temp) == []


def _pixels(png: bytes) -> tuple[int, int, list[bytes]]:
    """(width, channels, rows of pixel bytes) of an 8-bit RGB or RGBA PNG."""

    width, height = notify_card.png_size(png)
    at, data = 8, b""
    depth = kind = None
    while at < len(png):
        size = int.from_bytes(png[at : at + 4], "big")
        name, body = png[at + 4 : at + 8], png[at + 8 : at + 8 + size]
        if name == b"IHDR":
            depth, kind = body[8], body[9]
        elif name == b"IDAT":
            data += body
        at += 12 + size
    assert depth == 8 and kind in (2, 6)
    channels = 3 if kind == 2 else 4
    raw = zlib.decompress(data)
    stride = width * channels
    rows, previous = [], bytes(stride)
    for y in range(height):
        kind_of_filter = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for x in range(stride):
            left = line[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            if kind_of_filter == 1:
                line[x] = (line[x] + left) & 255
            elif kind_of_filter == 2:
                line[x] = (line[x] + up) & 255
            elif kind_of_filter == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind_of_filter == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                guess = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                line[x] = (line[x] + guess) & 255
        rows.append(bytes(line))
        previous = rows[-1]
    return width, channels, rows


def _blank(row: bytes, channels: int) -> bool:
    background = bytes.fromhex("0b0f1a")
    return all(row[x : x + 3] == background for x in range(0, len(row), channels))


BROWSER = notify_card.find_browser()
# The runner has /usr/bin/chromium too, so this test runs in the backend job beside the
# docker job's image. There it shares 4 cores with the other xdist workers: 91 green runs
# took about 15 s at the median, 25 at p95 and up to 33 per case, and three runs on
# 2026-11-16 were cut at 30 s (#824). The test checks the drawing, not the speed; notify
# still uses RENDER_TIMEOUT_SECONDS (1.53 s at 08:45 on 2026-11-16).
RUNNER_RENDER_TIMEOUT_SECONDS = 120.0


@pytest.mark.skipif(
    BROWSER is None, reason="no Chromium (the image has it: docker job)"
)
@pytest.mark.parametrize("case", ["two", "ten", "failed", "missing"])
def test_the_images_chromium_draws_the_card(private_temp, monkeypatch, case):
    """AC-2 (#754): the real drawing, in the backend image. The window is drawn EXTRA px
    taller than card_height: below card_height there is only the page's background, and
    the last section's bottom edge sits PAD above it (the heights are neither short nor
    long, review 6888784128 建議 4)."""

    view = {
        "two": _view(
            [_pick(1, corporate_action_on_session=True), _pick(2, "9999", "範例", None)]
        ),
        "ten": _view(TEN),
        "failed": _view([_pick(1)], session="2026-09-04", failure=FAILURE),
        "missing": _view(status="missing", failure=FAILURE),
    }[case]
    card = _card(view, CARD_US)
    height = notify_card.card_height(card)
    extra = 40
    monkeypatch.setattr(notify_card, "card_height", lambda _card: height + extra)
    drawn = notify_card.render(card, timeout=RUNNER_RENDER_TIMEOUT_SECONDS)
    assert drawn.reason is None, drawn.reason
    scale = notify_card.SCALE
    assert (drawn.width, drawn.height) == (
        notify_card.WIDTH * scale,
        (height + extra) * scale,
    )
    _width, channels, rows = _pixels(drawn.png)
    assert all(_blank(row, channels) for row in rows[height * scale :])
    edge = (height - notify_card.PAD) * scale
    assert not all(_blank(row, channels) for row in rows[edge - 4 : edge])
    assert all(_blank(row, channels) for row in rows[edge + 2 : height * scale])
    assert os.listdir(private_temp) == []
