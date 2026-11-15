"""The daily Telegram message as a picture (#754): ``notify.Content`` drawn as one PNG.

The card is an HTML page of its own, drawn by the image's Chromium (``SCREENSHOT_BROWSER``,
``/usr/bin/chromium`` in backend/Dockerfile, with ``fonts-noto-cjk``) through its command
line ``--headless --screenshot``. Why the command line and not the DevTools protocol of
tools/ops/screenshot.cjs: Python's standard library has no WebSocket, and the card needs
no wait for data. The command line captures the window only, so the page has a known
height: every block has a fixed height here (``card_height``) and the same one in the CSS,
each line one row that does not wrap (a long name ends with an ellipsis).

The page:
- links nothing (``Content-Security-Policy: default-src 'none'``): the styles are in the
  file and the fonts are the image's own, named in ``font-family``.
- ``html.escape``s every text from the data (names, reasons, labels, sources).
- shows the rows ``notify.Content`` gives, in the text's sections and order, at most
  ``MAX_ROWS`` of them, the rest counted in 「另 N 檔見今日名單頁」 as the text does.

The drawing (``render``) runs in a new temporary directory under the system's (not beside
any output, #750): the page, the browser profile and the PNG live there, and the directory
is removed when the drawing ends, whatever its outcome. The browser runs in its own process
group with ``HOME`` in that directory and only the environment it needs
(``browser_environment``: no token, no credential), dies with the run (``PR_SET_PDEATHSIG``),
is killed with its group after ``RENDER_TIMEOUT_SECONDS``, and any outcome but a PNG is a
reason (``no_browser``, ``exit_<code>``, ``timeout``, ``empty_png``, ``error:<type>``),
never an exception (``_Run`` also treats an exception here as ``error:<type>``).

Only the standard library: serve imports worker.notify, which imports this module when it
draws.
"""

from __future__ import annotations

import html
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # notify imports this module, not the other way at run time
    from .notify import Content, Row

BROWSER_ENV = "SCREENSHOT_BROWSER"
DEFAULT_BROWSERS = ("/usr/bin/chromium",)
# Drawing a card in the scheduler image took about 0.5 to 0.8 s (#754 AC-3); a stuck one is
# killed well before serve's five minutes.
RENDER_TIMEOUT_SECONDS = 30.0
# CSS pixels; the PNG is SCALE times that (1080 px wide).
WIDTH = 540
SCALE = 2
# The rows shown: the today page's cap, as the text's.
MAX_ROWS = 20
# The entry, stop and target cells longer than these (prices of 1,000 and up:
# 「1,234.50～1,300.00」, 「1,234.50」) get a smaller font, so they stay in their columns.
LONG_NUMBER = (13, 7, 7)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TEMP_PREFIX = "stock-notify-card-"
# The only variables the browser gets from the run's environment.
BROWSER_ENV_KEEP = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "FONTCONFIG_PATH",
    "FONTCONFIG_FILE",
)

# Fixed heights (CSS px), the same in STYLE: card_height adds them up.
PAD = 24
HEAD_TITLE_H = 40
HEAD_LINE_H = 24
HEAD_NOTE_H = 44  # a reason on up to two lines
GAP = 16
SECTION_H = 36
TABLE_HEAD_H = 26
ROW_H = 40
MORE_H = 32
US_TITLE_H = 36
US_ROW_H = 36
US_NOTE_H = 24  # a second line for 「（11/11 收盤） 非最新」
SOURCE_H = 28

# docs/DESIGN_SYSTEM.md tokens (the frontend's tokens.css): the dark terminal layout.
STYLE = f"""
:root {{
  --color-bg: #0b0f1a; --color-bg-alt: #111827; --color-bg-card: #1f2937;
  --color-bg-elevated: #374151; --color-border: rgba(255, 255, 255, 0.10);
  --color-text: #f9fafb; --color-text-muted: #9ca3af; --color-text-subtle: #6b7280;
  --color-primary: #3b82f6; --color-warning: #f59e0b;
  --color-up: #ef4444; --color-down: #22c55e; --color-flat: #9ca3af;
  --font-body: "Inter", "Noto Sans CJK TC", "Noto Sans TC", sans-serif;
  --font-mono: "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono CJK TC", monospace;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {WIDTH}px; background: var(--color-bg); overflow: hidden; }}
body {{ font-family: var(--font-body); color: var(--color-text); padding: {PAD}px; }}
.num {{ font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  text-align: right; white-space: nowrap; }}
.muted {{ color: var(--color-text-muted); }}
.line {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
header .title {{ height: {HEAD_TITLE_H}px; display: flex; align-items: baseline; gap: 12px; }}
header h1 {{ font-size: 26px; font-weight: 700; }}
header .date {{ font-size: 20px; font-weight: 600; }}
header .count {{ margin-left: auto; font-size: 20px; font-weight: 700; }}
header .sub {{ height: {HEAD_LINE_H}px; line-height: {HEAD_LINE_H}px; font-size: 15px; }}
header .note {{ height: {HEAD_NOTE_H}px; line-height: 22px; font-size: 15px;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; }}
section {{ margin-top: {GAP}px; background: var(--color-bg-card);
  border: 1px solid var(--color-border); border-radius: 12px; overflow: hidden; }}
section h2 {{ height: {SECTION_H}px; line-height: {SECTION_H}px; padding: 0 14px;
  font-size: 17px; font-weight: 700; background: var(--color-bg-alt);
  border-left: 3px solid var(--color-primary); }}
section h2 .n {{ color: var(--color-text-muted); font-weight: 600; margin-left: 8px; }}
.grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 150px 74px 74px;
  column-gap: 8px; align-items: center; padding: 0 14px; }}
.thead {{ height: {TABLE_HEAD_H}px; font-size: 13px; color: var(--color-text-muted); }}
.thead span:not(:first-child) {{ text-align: right; }}
.row {{ height: {ROW_H}px; border-top: 1px solid var(--color-border); font-size: 17px; }}
.row .name {{ font-weight: 600; }}
.row .long {{ font-size: 14px; letter-spacing: -0.3px; }}
.row .sym {{ font-family: var(--font-mono); }}
.row .incomplete {{ grid-column: 2 / 5; text-align: right; font-size: 15px; }}
.more {{ margin-top: {GAP}px; height: {MORE_H}px; line-height: {MORE_H}px; font-size: 15px;
  padding: 0 2px; }}
.us h2 {{ height: {US_TITLE_H}px; line-height: {US_TITLE_H}px; }}
.us h2 .status {{ color: var(--color-warning); font-weight: 600; margin-left: 8px; }}
.us h2 .closed {{ color: var(--color-text-muted); font-weight: 400; font-size: 15px;
  margin-left: 8px; }}
.us .grid {{ grid-template-columns: 112px 150px 110px minmax(0, 1fr); }}
.us .row {{ height: {US_ROW_H}px; }}
.us .noted {{ height: {US_ROW_H + US_NOTE_H}px;
  grid-template-rows: {US_ROW_H - 4}px {US_NOTE_H}px; }}
.us .note {{ grid-column: 2 / 4; grid-row: 2; font-size: 14px; text-align: right;
  line-height: {US_NOTE_H - 4}px; align-self: start; }}
.us .nodata {{ grid-column: 2 / 5; text-align: right; font-size: 15px; }}
.up {{ color: var(--color-up); }} .down {{ color: var(--color-down); }}
.flat {{ color: var(--color-flat); }}
.up, .down, .flat {{ font-weight: 600; }}
.source {{ height: {SOURCE_H}px; line-height: {SOURCE_H}px; font-size: 13px;
  padding: 0 14px; border-top: 1px solid var(--color-border); }}
"""

CSP = "default-src 'none'; style-src 'unsafe-inline'"


def esc(value: object) -> str:
    """Data text for the page (quotes too: nothing of the data goes in an attribute, but
    escaping them costs nothing)."""

    return html.escape(str(value), quote=True)


def shown_rows(content: Content) -> list[Row]:
    return content.rows[:MAX_ROWS]


def more_count(content: Content) -> int:
    """「另 N 檔」: what the list has and the card leaves out (the text's rule)."""

    return max(len(content.rows), content.total) - len(shown_rows(content))


def card_height(content: Content) -> int:
    """The page's height in CSS px: the fixed heights in the order the page has them."""

    from .notify import sections

    height = 2 * PAD + HEAD_TITLE_H + HEAD_LINE_H
    if content.note:
        height += HEAD_NOTE_H
    for _mark, _title, members in sections(shown_rows(content)):
        height += GAP + 2 + SECTION_H + TABLE_HEAD_H + len(members) * ROW_H
    if more_count(content):
        height += GAP + MORE_H
    us = content.us
    height += GAP + 2 + US_TITLE_H
    if us.rows:
        height += len(us.rows) * US_ROW_H
        height += sum(US_NOTE_H for row in us.rows if row.close and row.note.strip())
    if us.source:
        height += SOURCE_H
    return height


def _row_html(row: Row) -> str:
    symbol, _, name = row.name.partition(" ")
    cells = [
        f'<span class="name line"><span class="sym">{esc(symbol)}</span>'
        f"{' ' if name else ''}{esc(name)}</span>"
    ]
    if row.entry is None:
        cells.append(f'<span class="incomplete muted">{esc(row.levels)}</span>')
    else:
        for value, longest in zip(
            (row.entry, row.stop, row.target), LONG_NUMBER, strict=True
        ):
            kind = "num long" if len(value or "") > longest else "num"
            cells.append(f'<span class="{kind}">{esc(value)}</span>')
    return f'<div class="row grid">{"".join(cells)}</div>'


def _us_html(content: Content) -> str:
    us = content.us
    title = "<h2>隔夜美股"
    if us.missing:
        title += f'<span class="status">{esc(us.missing)}</span>'
    if us.status:
        title += f'<span class="status">{esc(us.status)}</span>'
    if us.closed:
        title += f'<span class="closed">{esc(us.closed)}</span>'
    parts = [f'<section class="us">{title}</h2>']
    for index in us.rows:
        label = f'<span class="line">{esc(index.label)}</span>'
        kind = "row grid"
        if index.close is None:
            cells = f'{label}<span class="nodata muted">{esc(index.note)}</span>'
        else:
            tone = f' class="num {index.tone}"' if index.tone else ' class="num"'
            cells = (
                f'{label}<span class="num">{esc(index.close)}</span>'
                f"<span{tone}>{esc(index.change)}</span>"
            )
            if index.note.strip():
                # Its own line under the close and the change, not cut.
                kind += " noted"
                cells += f'<span class="note muted">{esc(index.note.strip())}</span>'
        parts.append(f'<div class="{kind}">{cells}</div>')
    if us.source:
        parts.append(f'<div class="source muted line">來源 {esc(us.source)}</div>')
    parts.append("</section>")
    return "".join(parts)


def card_html(content: Content) -> str:
    """The page: the head, a table per section, 「另 N 檔」, then the US block."""

    from .notify import day_label, sections

    head = [
        '<header><div class="title"><h1>今日名單</h1>',
        f'<span class="date">{esc(day_label(content.today))}</span>',
    ]
    if content.computed:
        head.append(f'<span class="count">{esc(content.count)} 檔</span>')
    head.append(f'</div><div class="sub muted line">{esc(content.sub)}</div>')
    if content.note:
        head.append(f'<div class="note muted">{esc(content.note)}</div>')
    head.append("</header>")
    body = head
    for _mark, title, members in sections(shown_rows(content)):
        body.append(
            f'<section><h2>{esc(title)}<span class="n">{len(members)} 檔</span></h2>'
            '<div class="thead grid"><span>代號 名稱</span><span>進場</span>'
            "<span>停損</span><span>目標</span></div>"
        )
        body += [_row_html(row) for row in members]
        body.append("</section>")
    more = more_count(content)
    if more:
        body.append(f'<div class="more muted">另 {more} 檔見今日名單頁</div>')
    body.append(_us_html(content))
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<style>{STYLE}</style></head><body>{''.join(body)}</body></html>"
    )


@dataclass(frozen=True)
class Rendered:
    png: bytes | None
    reason: str | None
    seconds: float
    width: int | None = None
    height: int | None = None


def png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's IHDR; None when DATA is no PNG."""

    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def find_browser(environ=os.environ) -> str | None:
    configured = environ.get(BROWSER_ENV, "").strip()
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    return next((path for path in DEFAULT_BROWSERS if os.access(path, os.X_OK)), None)


def browser_command(browser: str, work: Path, height: int) -> list[str]:
    return [
        browser,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--mute-audio",
        f"--user-data-dir={work / 'profile'}",
        f"--force-device-scale-factor={SCALE}",
        f"--window-size={WIDTH},{height}",
        f"--screenshot={work / 'card.png'}",
        (work / "card.html").as_uri(),
    ]


def browser_environment(work: Path, environ=os.environ) -> dict[str, str]:
    """The browser's environment: what it needs to run and draw, nothing else (no token,
    no credential of the env file, #754 review 6888784128)."""

    kept = {name: environ[name] for name in BROWSER_ENV_KEEP if name in environ}
    return {
        **kept,
        "HOME": str(work),
        "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_CACHE_HOME": str(work / "cache"),
        "TMPDIR": str(work),
    }


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError):
        process.kill()
    process.wait()


def render(
    content: Content,
    *,
    browser: str | None = None,
    timeout: float | None = None,
) -> Rendered:
    """CONTENT as a PNG, or the reason there is none."""

    started = time.monotonic()

    def done(png: bytes | None, reason: str | None) -> Rendered:
        size = png_size(png) if png else None
        return Rendered(
            png,
            reason,
            round(time.monotonic() - started, 2),
            *(size or (None, None)),
        )

    browser = browser or find_browser()
    if not browser:
        return done(None, "no_browser")
    work: Path | None = None
    try:
        work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        (work / "card.html").write_text(card_html(content), encoding="utf-8")
        extra = {}
        if sys.platform.startswith("linux"):
            # Killed with notify (serve's backstop, the OOM killer): its own session
            # keeps it out of notify's group, so the group kill would not reach it.
            from .job import _die_with_parent

            extra["preexec_fn"] = _die_with_parent(os.getpid())
        process = subprocess.Popen(
            browser_command(browser, work, card_height(content)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=work,
            env=browser_environment(work),
            start_new_session=True,
            **extra,
        )
        try:
            code = process.wait(
                timeout=RENDER_TIMEOUT_SECONDS if timeout is None else timeout
            )
        except subprocess.TimeoutExpired:
            _kill_group(process)
            return done(None, "timeout")
        # The browser's helpers (zygote, crashpad) share its group: none outlives it.
        _kill_group(process)
        if code != 0:
            return done(None, f"exit_{code}")
        try:
            png = (work / "card.png").read_bytes()
        except FileNotFoundError:
            return done(None, "empty_png")
        if not png_size(png):
            return done(None, "empty_png")
        return done(png, None)
    except Exception as exc:  # the text goes instead (notify._Run)
        return done(None, f"error:{type(exc).__name__}")
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
