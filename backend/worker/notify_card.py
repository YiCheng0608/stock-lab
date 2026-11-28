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
- the AI list as the text has it (#1146): the head with the list's date, a warning
  「MM/DD 的名單」 when it is not today's, its count and 「AI 推論，未經驗證」, the
  failure line when today has no list of its own; then one section with the accent bar
  and the badge of DESIGN_SYSTEM §7: the model and the prompt version, 大盤 and its first
  reason, 族群 one a line, and each pick's head (rank, code, name, 判讀方式 and 把握), its
  levels on two lines (the entry, then the stop, targets and RR; PR #1153 review 1) or the
  sentence in their place, its corporate-action note in ``--color-warning`` and
  its first reason (at most two lines, ``AI_REASON_H``; longer ones end with an ellipsis,
  the page has them whole). Then the rule list's count line and the US block.

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
    from .notify import Content, Pick

BROWSER_ENV = "SCREENSHOT_BROWSER"
DEFAULT_BROWSERS = ("/usr/bin/chromium",)
# Drawing a card in the scheduler image took about 0.5 to 0.8 s (#754 AC-3); a stuck one is
# killed well before serve's five minutes.
RENDER_TIMEOUT_SECONDS = 30.0
# CSS pixels; the PNG is SCALE times that (1080 px wide).
WIDTH = 540
SCALE = 2
# The picks shown: the AI list's cap (ai_list_reading.MAX_PICKS), as the text's.
MAX_ROWS = 10
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
HEAD_NOTE_H = 44  # a line of up to two lines (the failure line)
GAP = 16
US_TITLE_H = 36
US_ROW_H = 36
US_NOTE_H = 24  # a second line for 「（11/11 收盤） 非最新」
SOURCE_H = 28
# The AI list (#1146): its title, the model line, a head (大盤, 族群), a pick's head, its
# levels lines (entry, then stop／target／RR), its corporate-action note, a reason (two lines at most) and 「另 N 檔」/the
# rule list's line.
AI_TITLE_H = 36
AI_META_H = 24
AI_HEAD_H = 30
AI_LINE_H = 28
AI_LEVELS_H = 26
AI_NOTE_H = 22
AI_REASON_H = 42
MORE_H = 32

# docs/DESIGN_SYSTEM.md tokens (the frontend's tokens.css): the dark terminal layout.
STYLE = f"""
:root {{
  --color-bg: #0b0f1a; --color-bg-alt: #111827; --color-bg-card: #1f2937;
  --color-bg-elevated: #374151; --color-border: rgba(255, 255, 255, 0.10);
  --color-text: #f9fafb; --color-text-muted: #9ca3af; --color-text-subtle: #6b7280;
  --color-primary: #3b82f6; --color-warning: #f59e0b; --color-accent: #8b5cf6;
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
header .stale {{ font-size: 15px; font-weight: 600; color: var(--color-warning);
  border: 1px solid var(--color-warning); border-radius: 50px; padding: 0 8px; }}
header .note {{ height: {HEAD_NOTE_H}px; line-height: 22px; font-size: 15px;
  color: var(--color-warning); overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
section {{ margin-top: {GAP}px; background: var(--color-bg-card);
  border: 1px solid var(--color-border); border-radius: 12px; overflow: hidden; }}
section h2 {{ height: {US_TITLE_H}px; line-height: {US_TITLE_H}px; padding: 0 14px;
  font-size: 17px; font-weight: 700; background: var(--color-bg-alt);
  border-left: 3px solid var(--color-primary); }}
.grid {{ display: grid; column-gap: 8px; align-items: center; padding: 0 14px; }}
.row {{ border-top: 1px solid var(--color-border); font-size: 17px; }}
.more {{ margin-top: {GAP}px; height: {MORE_H}px; line-height: {MORE_H}px; font-size: 15px;
  padding: 0 2px; }}
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
.ai {{ border-left: 2px solid var(--color-accent); }}
.ai h2 {{ height: {AI_TITLE_H}px; line-height: {AI_TITLE_H}px; border-left: none;
  display: flex; align-items: center; gap: 10px; }}
.ai .badge {{ height: 24px; line-height: 22px; padding: 0 10px; font-size: 13px;
  font-weight: 600; border: 1px solid var(--color-accent); border-radius: 50px; }}
.ai .meta {{ height: {AI_META_H}px; line-height: {AI_META_H}px; font-size: 13px;
  padding: 0 14px; }}
.ai .head {{ height: {AI_HEAD_H}px; line-height: {AI_HEAD_H}px; font-size: 15px;
  font-weight: 700; padding: 0 14px; border-top: 1px solid var(--color-border); }}
.ai .head .v {{ font-weight: 600; margin-left: 8px; }}
.ai .pick {{ height: {AI_LINE_H}px; line-height: {AI_LINE_H}px; font-size: 16px;
  padding: 0 14px; display: flex; gap: 10px; border-top: 1px solid var(--color-border); }}
.ai .pick .name {{ font-weight: 700; flex: 0 0 auto; max-width: 60%; }}
.ai .pick .method {{ flex: 1 1 auto; text-align: right; }}
.ai .levels {{ height: {AI_LEVELS_H}px; line-height: {AI_LEVELS_H}px; font-size: 14px;
  padding: 0 14px 0 28px; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }}
.ai .levels.hidden {{ font-family: var(--font-body); }}
.ai .sector {{ height: {AI_LINE_H}px; line-height: {AI_LINE_H}px; font-size: 15px;
  padding: 0 14px 0 28px; }}
.ai .corp {{ height: {AI_NOTE_H}px; line-height: {AI_NOTE_H}px; font-size: 13px;
  padding: 0 14px 0 28px; color: var(--color-warning); }}
.ai .reason {{ height: {AI_REASON_H}px; line-height: 20px; font-size: 14px;
  padding: 0 14px 0 28px; overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
.ai .more {{ margin: 0; height: {MORE_H}px; line-height: {MORE_H}px;
  padding: 0 14px; border-top: 1px solid var(--color-border); }}
.source {{ height: {SOURCE_H}px; line-height: {SOURCE_H}px; font-size: 13px;
  padding: 0 14px; border-top: 1px solid var(--color-border); }}
"""

CSP = "default-src 'none'; style-src 'unsafe-inline'"


def esc(value: object) -> str:
    """Data text for the page (quotes too: nothing of the data goes in an attribute, but
    escaping them costs nothing)."""

    return html.escape(str(value), quote=True)


def shown_picks(content: Content) -> tuple[Pick, ...]:
    return content.ai.picks[:MAX_ROWS]


def more_count(content: Content) -> int:
    """「另 N 檔」: the picks the card leaves out."""

    return len(content.ai.picks) - len(shown_picks(content))


def card_height(content: Content) -> int:
    """The page's height in CSS px: the fixed heights in the order the page has them."""

    ai = content.ai
    height = 2 * PAD + HEAD_TITLE_H + HEAD_LINE_H
    if ai.failure:
        height += HEAD_NOTE_H
    if ai.line:
        height += HEAD_LINE_H
    height += ai_height(content)
    height += GAP + MORE_H  # the rule list's line
    us = content.us
    height += GAP + 2 + US_TITLE_H
    if us.rows:
        height += len(us.rows) * US_ROW_H
        height += sum(US_NOTE_H for row in us.rows if row.close and row.note.strip())
    if us.source:
        height += SOURCE_H
    return height


def ai_height(content: Content) -> int:
    """The AI list's section height (0 without a done list)."""

    ai = content.ai
    if not ai.done:
        return 0
    height = GAP + 2 + AI_TITLE_H + AI_META_H + AI_HEAD_H
    if ai.market_reason:
        height += AI_REASON_H
    if ai.sector_items:
        height += AI_HEAD_H + len(ai.sector_items) * AI_LINE_H
    if ai.empty:
        height += AI_REASON_H
    for pick in shown_picks(content):
        height += AI_LINE_H + len(pick.level_lines) * AI_LEVELS_H
        height += AI_NOTE_H if pick.note else 0
        height += AI_REASON_H if pick.reason else 0
    if more_count(content):
        height += MORE_H
    return height


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


def _pick_html(pick: Pick) -> str:
    parts = [
        f'<div class="pick"><span class="name line">{esc(pick.head)}</span>'
        f'<span class="method muted line">{esc(pick.method)}</span></div>',
        *(
            f'<div class="levels line{"" if pick.shown else " hidden muted"}">'
            f"{esc(line)}</div>"
            for line in pick.level_lines
        ),
    ]
    if pick.note:
        parts.append(f'<div class="corp line">{esc(pick.note)}</div>')
    if pick.reason:
        parts.append(f'<div class="reason muted">{esc(pick.reason)}</div>')
    return "".join(parts)


def _ai_html(content: Content) -> str:
    from .notify import AI_LIST_MARK, AI_LIST_TITLE

    ai = content.ai
    if not ai.done:
        return ""
    market = f'<div class="head line">大盤<span class="v">{esc(ai.market)}</span></div>'
    parts = [
        f'<section class="ai"><h2>{esc(AI_LIST_TITLE)}'
        f'<span class="badge">{esc(AI_LIST_MARK)}</span></h2>',
        f'<div class="meta muted line">{esc(ai.meta)}</div>',
        market,
    ]
    if ai.market_reason:
        parts.append(f'<div class="reason muted">{esc(ai.market_reason)}</div>')
    if ai.sector_items:
        # One line each (PR #1153 review 1: five on one line are cut).
        parts.append('<div class="head line">族群</div>')
        parts += [
            f'<div class="sector line">{esc(item)}</div>' for item in ai.sector_items
        ]
    if ai.empty:
        parts.append(f'<div class="reason">{esc(ai.empty)}</div>')
    parts += [_pick_html(pick) for pick in shown_picks(content)]
    more = more_count(content)
    if more:
        parts.append(f'<div class="more muted">另 {more} 檔見今日名單頁</div>')
    parts.append("</section>")
    return "".join(parts)


def card_html(content: Content) -> str:
    """The page: the head (the list's date, its 「MM/DD 的名單」 mark when it is not
    today's, the failure line), the AI list, the rule list's line, then the US block."""

    from .notify import AI_LIST_MARK, AI_LIST_TITLE, day_label

    ai = content.ai
    day = ai.session_date or content.today
    head = [
        f'<header><div class="title"><h1>{esc(AI_LIST_TITLE)}</h1>',
        f'<span class="date">{esc(day_label(day))}</span>',
    ]
    if ai.done and ai.session_date != content.today:
        head.append(f'<span class="stale">{esc(f"{day:%m/%d} 的名單")}</span>')
    if ai.done:
        head.append(f'<span class="count">{len(ai.picks)} 檔</span>')
    sub = f"開盤前產出 · {AI_LIST_MARK}" if ai.done else AI_LIST_MARK
    head.append(f'</div><div class="sub muted line">{esc(sub)}</div>')
    if ai.failure:
        head.append(f'<div class="note">{esc(ai.failure)}</div>')
    if ai.line:
        head.append(f'<div class="sub muted line">{esc(ai.line)}</div>')
    head.append("</header>")
    body = [*head, _ai_html(content)]
    body.append(f'<div class="more muted">{esc(content.rule_line)}</div>')
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
