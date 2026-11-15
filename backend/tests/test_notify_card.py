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
import zlib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from test_notify import (
    CARD_ITEMS,
    CARD_US,
    LISTING,
    MONDAY,
    US,
    _breakout,
    _item,
    _us,
)
from test_candidates import T
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


def _card(listing=LISTING, indexes=US, status=None):
    return notify.content(MONDAY, T, listing, indexes, status)


def _text_rows(card):
    """The text's list rows as (name, levels), in its order (sections, then rank)."""

    lines = notify.text(card).splitlines()
    rows = []
    for at, line in enumerate(lines):
        if line.startswith("<b>") and lines[at + 1].startswith(notify.INDENT):
            rows.append((line[3:-4], lines[at + 1][1:]))
    return rows


def _card_rows(page, count):
    """The card's first COUNT rows as (name, levels), the text's way of writing them."""

    rows = []
    for cells in page.rows[:count]:
        name = cells[0]
        if len(cells) == 4:
            levels = f"進場 {cells[1]}｜停損 {cells[2]}｜目標 {cells[3]}"
        else:
            levels = cells[1]
        rows.append((notify.esc(name), levels))
    return rows


@pytest.mark.parametrize(
    "listing, indexes",
    [
        ({"status": "success", "candidate_count": 23, "items": CARD_ITEMS}, CARD_US),
        (LISTING, US),
        # One index behind: its own close date and 非最新 on the row.
        (LISTING, [*US[:3], _us("SOX", 10000.0, 0.01, "2026-09-03", "stale")]),
    ],
)
def test_the_card_shows_the_texts_rows_item_by_item(listing, indexes):
    """AC-1 (#754): one Content; the card's rows are the text's, in its order and words."""

    card = _card(listing, indexes)
    page = Page(notify_card.card_html(card))
    text_rows = _text_rows(card)
    assert text_rows and _card_rows(page, len(text_rows)) == text_rows
    # The US rows: the label, close, change and note of the text's lines.
    us_rows = page.rows[len(text_rows) :]
    lines = notify.text(card).splitlines()
    for row, cells in zip(card.us.rows, us_rows, strict=True):
        if row.close is None:
            assert cells == [row.label, row.note]
            assert f"{notify.esc(row.label)}{notify.INDENT}{row.note}" in lines
        else:
            label, close, change, *note = cells
            assert note == ([row.note.strip()] if row.note.strip() else [])
            # The text's line, rebuilt from the card's cells.
            line = (
                f"{notify.esc(label)}{notify.INDENT}{close}{notify.INDENT}{change}"
                f"{row.note[: len(row.note) - len(row.note.lstrip())]}{''.join(note)}"
            )
            mark = notify.US_MARKS.get(row.tone or "")
            assert (f"{mark} {line}" if mark else line) in lines
    page_text = "".join(page.text)
    for word in ("另 3 檔見今日名單頁", "來源 FinMind"):
        assert (word in page_text) == (word in notify.text(card))
    # Each section's head and count as the text has it.
    for _mark, title, members in notify.sections(card.rows):
        assert f"{title}{len(members)} 檔" in page_text
        assert f"<b>{title}（{len(members)} 檔）</b>" in notify.text(card)


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
    listing = {
        "status": "success",
        "candidate_count": 1,
        "items": [_item(1, "1234", evil, _breakout(61.1, 58.5, 65.27))],
    }
    indexes = [
        {**_us("SPX", 7561.67, -0.004), "source": {"label": f"{evil} x"}},
        {
            "symbol": "<i>",
            "name": evil,
            "status": "unavailable",
            "reason": "fetch_failed",
        },
    ]
    pages = [
        notify_card.card_html(_card(listing, indexes)),
        notify_card.card_html(
            _card(
                {**listing, "candidate_count": 0, "items": [], "zero_reason_text": evil}
            )
        ),
        notify_card.card_html(_card({"status": "not_computed", "items": []}, US, evil)),
    ]
    for html in pages:
        page = Page(html)
        assert page.tags <= TAGS, page.tags - TAGS
        assert evil in "".join(page.text)
        assert "<script>" not in html and "&lt;script&gt;" in html
    # Nothing outside the file: no URL, the policy forbids any fetch.
    assert "http" not in pages[0].replace("http-equiv", "")
    assert "default-src 'none'" in pages[0]
    # The caption (Telegram HTML) escapes the section heads; its tags are <b> only.
    assert (
        notify.caption(_card(listing, indexes)) == "<b>今日名單 09/07（一）</b>・突破 1"
    )


def test_the_caption_says_the_sections_or_why_there_are_none():
    card = _card({"status": "success", "candidate_count": 23, "items": CARD_ITEMS})
    assert (
        notify.caption(card) == "<b>今日名單 09/07（一）</b>・突破 17、回踩 2、其他 1"
    )
    missing = _card({"status": "not_computed", "items": []})
    assert notify.caption(missing) == "<b>今日名單 09/07（一）</b>・名單無資料"
    # No count on a list that was not made (not 「0 檔」).
    assert 'class="count"' not in notify_card.card_html(missing)
    assert '<span class="count">0 檔</span>' in notify_card.card_html(
        _card({"status": "success", "candidate_count": 0, "items": []})
    )
    empty = {"status": "success", "candidate_count": 0, "items": []}
    assert notify.caption(_card(empty)) == "<b>今日名單 09/07（一）</b>・0 檔"


def test_the_card_counts_the_rows_it_leaves_out_and_its_height_follows_its_blocks():
    many = [
        _item(rank, f"{rank:04d}", "名", _breakout(61.1, 58.5, 65.27))
        for rank in range(1, 21)
    ]
    card = _card({"status": "success", "candidate_count": 25, "items": many})
    page = Page(notify_card.card_html(card))
    assert len(page.rows) == 20 + len(US)
    assert "另 5 檔見今日名單頁" in "".join(page.text)
    small = _card()
    p = notify_card
    # A US row with a note has a second line.
    behind = _card(LISTING, [*US[:3], _us("SOX", 1.0, 0.01, "2026-09-03", "stale")])
    # Two close dates: each row has its own (and SOX 非最新).
    assert p.card_height(behind) == p.card_height(small) + 4 * p.US_NOTE_H
    assert p.card_height(small) == (
        2 * p.PAD
        + p.HEAD_TITLE_H
        + p.HEAD_LINE_H
        + 2 * (p.GAP + 2 + p.SECTION_H + p.TABLE_HEAD_H + p.ROW_H)
        + p.GAP
        + 2
        + p.US_TITLE_H
        + 4 * p.US_ROW_H
        + p.SOURCE_H
    )
    assert (
        p.card_height(card)
        == p.card_height(small)
        - 2 * (p.GAP + 2 + p.SECTION_H + p.TABLE_HEAD_H + p.ROW_H)
        + (p.GAP + 2 + p.SECTION_H + p.TABLE_HEAD_H + 20 * p.ROW_H)
        + p.GAP
        + p.MORE_H
    )


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
    # tini; at most a zombie).
    try:
        state = Path(f"/proc/{child}/stat").read_text().split()[2]
    except FileNotFoundError:
        state = "gone"
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


@pytest.mark.skipif(
    BROWSER is None, reason="no Chromium (the image has it: docker job)"
)
@pytest.mark.parametrize("more", [False, True])
def test_the_images_chromium_draws_the_card(private_temp, monkeypatch, more):
    """AC-2 (#754): the real drawing, in the backend image. The window is drawn EXTRA px
    taller than card_height: below card_height there is only the page's background, and
    the last section's bottom edge sits PAD above it (the heights are neither short nor
    long, review 6888784128 建議 4)."""

    items = CARD_ITEMS if more else CARD_ITEMS[:4]
    card = _card(
        {"status": "success", "candidate_count": 23 if more else 4, "items": items},
        CARD_US,
    )
    height = notify_card.card_height(card)
    extra = 40
    monkeypatch.setattr(notify_card, "card_height", lambda _card: height + extra)
    drawn = notify_card.render(card)
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
