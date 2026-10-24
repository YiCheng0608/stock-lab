"""Machine checks for the five main pages (Issue #243).

    python tools/verify/page_checks.py --api <API origin> --web <preview origin> \\
        --db <stock.db> --out <directory> [--fixture] [--pages today,news,...]

Runs every check that ``.claude/skills/verify-stock-lab/features/*.md`` labels
``CI`` against a running API and a vite preview that forwards ``/api`` to it:
fetches the page APIs, takes screenshots with ``tools/ops/screenshot.cjs``
(Chromium/Chrome/Edge; ``--browser`` or ``$SCREENSHOT_BROWSER``) and compares
the page text with the API and with ``db_facts.py`` on ``--db`` (read-only).
The origins also come from ``$VERIFY_API_URL`` and ``$VERIFY_WEB_URL``.

``--fixture`` is for the fixture database of ``tools/verify/fixture_db.py``: each
page also gets an ``API`` check comparing its APIs with
``fixture_data.EXPECTED``, and the stocks checks also run on the no-data stock
``fixture_data.NO_DATA_STOCK``.  It imports ``fixture_data``, so ``backend/``'s
requirements must be installed.

Writes ``<out>/api/*.json``, ``<out>/shots/*.png|txt|jsonl``,
``<out>/results.json``, ``<out>/summary.md`` and ``<out>/status.md`` (the same
tables without the evidence, for runs on private data) and prints one line per check.
Exit 0 when every check passed (a check in ``KNOWN_FAILURES`` may fail), 1 when
one failed, 2 when the features files and ``CHECKS`` disagree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "verify-stock-lab"
FEATURES = SKILL / "features"
SCREENSHOT = ROOT / "tools" / "ops" / "screenshot.cjs"
PAGES = ("today", "news", "themes", "stocks", "actions")
TAIPEI = timezone(timedelta(hours=8))

# A check that fails because of a known product defect: it is reported, but does
# not fail the run.  When it passes the run fails, so the entry is removed with the fix.
KNOWN_FAILURES: dict[tuple[str, str], str] = {
    ("today", "T6"): "https://github.com/YiCheng0608/stock-lab/issues/233",
}

API_ATTEMPTS = 3
API_TIMEOUT_S = 30
SHOT_ATTEMPTS = 2
SHOT_TIMEOUT_S = 240


# ---- features labels ----

CHECK_ROW = re.compile(r"^\| ([A-Z][0-9]+) \| ([^|]*?) \|", re.M)


def feature_checks(features: Path = FEATURES) -> dict[str, dict[str, str]]:
    """Page -> check code -> its 類型 cell (``CI`` or ``人工``) in the 檢查 table."""

    result = {}
    for page in PAGES:
        text = (features / f"{page}.md").read_text(encoding="utf-8")
        section = text.split("\n## 檢查\n", 1)[1].split("\n## ", 1)[0]
        result[page] = dict(CHECK_ROW.findall(section))
    return result


def registry_problems(
    labels: dict[str, dict[str, str]], checks: dict[str, dict[str, Any]]
) -> list[str]:
    """Every CI check needs an implementation, and every implementation a CI label."""

    problems = []
    for page in PAGES:
        page_labels = labels.get(page, {})
        for code, kind in page_labels.items():
            if kind not in ("CI", "人工"):
                problems.append(f"{page}.md {code}: 類型 is {kind!r}, not CI or 人工")
            elif kind == "CI" and code not in checks.get(page, {}):
                problems.append(f"{page}.md {code}: labeled CI but not implemented")
        for code in checks.get(page, {}):
            if page_labels.get(code) != "CI":
                problems.append(
                    f"{page} {code}: implemented but {page}.md does not label it CI"
                )
    return problems


# ---- page text ----


# Any whitespace but tab: U+3000, U+00A0 (a news title's NBSP shows as a plain
# space in the browser, Issue #249) and the other Unicode spaces.
SPACES = re.compile(r"[^\S\t]+")


def normalize(line: str) -> str:
    """The SKILL's whitespace rule: runs of non-tab whitespace become one space; tabs stay."""

    return SPACES.sub(" ", line).strip(" ")


def slash(day: str) -> str:
    """``YYYY-MM-DD`` (or a timestamp starting with it) -> ``YYYY/MM/DD``."""

    return day[:10].replace("-", "/")


TIME_LINE = re.compile(r"^(發布於|事件於|事件日) |^來源時間(待核實|未提供)$")
DATE_LINE = re.compile(r"^資料日 ([0-9]{4}/[0-9]{2}/[0-9]{2})$")
CANDIDATE_DISCLAIMER = (
    "由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。"
)


@dataclass
class Text:
    """One screenshot's page text: the non-blank lines, normalized, with line numbers."""

    name: str
    raw: str
    lines: list[str] = field(default_factory=list)
    numbers: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        for number, line in enumerate(self.raw.splitlines(), start=1):
            value = normalize(line)
            if value.strip():
                self.lines.append(value)
                self.numbers.append(number)

    # Expected lines come from API strings, so they get the same whitespace rule.
    def has(self, line: str) -> bool:
        return normalize(line) in self.lines

    def find(self, line: str, start: int = 0) -> int:
        """Index of the first whole line equal to ``line`` at or after ``start``; -1 if none."""

        try:
            return self.lines.index(normalize(line), start)
        except ValueError:
            return -1

    def find_where(self, predicate: Callable[[str], bool], start: int = 0) -> int:
        return next(
            (i for i in range(start, len(self.lines)) if predicate(self.lines[i])), -1
        )

    def after(self, index: int, offset: int = 1) -> str | None:
        """The ``offset``-th non-blank line after ``index``."""

        if index < 0 or index + offset >= len(self.lines):
            return None
        return self.lines[index + offset]

    def count(self, predicate: Callable[[str], bool]) -> int:
        return sum(1 for line in self.lines if predicate(line))

    def at(self, index: int) -> str:
        return f"{self.name} 第 {self.numbers[index]} 行" if index >= 0 else self.name


# ---- results ----


class Fail(Exception):
    """A failed check; the message is the evidence (expected vs actual)."""


class Undetermined(Fail):
    """A check that could not run: an API was not 200 or a screenshot was not ready."""

    def __str__(self) -> str:
        return f"無法判定：{super().__str__()}"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Fail(message)


@dataclass
class Result:
    page: str
    code: str
    ok: bool
    detail: str
    subject: str = ""
    known: str | None = None

    @property
    def status(self) -> str:
        if self.known:
            return "失敗（已知）" if not self.ok else "失敗（已知失敗卻通過）"
        return "通過" if self.ok else "失敗"

    @property
    def failed(self) -> bool:
        # A known failure that passes fails the run, so KNOWN_FAILURES stays current.
        return self.ok if self.known else not self.ok

    @property
    def label(self) -> str:
        return f"{self.code}（{self.subject}）" if self.subject else self.code


# ---- the run ----


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db_facts = _load(SKILL / "db_facts.py", "db_facts")


def slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-")


@dataclass
class Shot:
    name: str
    path: str  # under the preview origin, e.g. "/stocks/TWSE/9101"
    widths: tuple[int, ...] = (1280, 390)
    clicks: tuple[str, ...] = ()


@dataclass
class Stock:
    """The instrument a stocks check runs on, and its screenshot name prefix."""

    exchange: str
    symbol: str
    prefix: str = "stock"

    @property
    def label(self) -> str:
        return f"{self.exchange} {self.symbol}"


class Run:
    def __init__(
        self,
        api: str,
        web: str,
        db: Path,
        out: Path,
        browser: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.api_base = api.rstrip("/")
        self.web_base = web.rstrip("/")
        self.db = db
        self.out = out
        self.browser = browser
        self.now = now or datetime.now(TAIPEI)
        self.responses: dict[str, tuple[int, Any]] = {}
        self.shots: dict[str, dict[int, dict]] = {}
        self._facts: dict[tuple, dict] = {}
        for sub in ("api", "shots"):
            (out / sub).mkdir(parents=True, exist_ok=True)

    # -- API --

    def get(self, path: str, name: str | None = None) -> Any:
        """GET ``/api/<path>`` once per run (saved to api/<name>); Undetermined when not 200."""

        if path not in self.responses:
            self.responses[path] = self._fetch(path)
            status, payload = self.responses[path]
            target = self.out / "api" / (name or f"{slug(path)}.json")
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
                if status == 200
                else f"HTTP {status}\n{payload}",
                encoding="utf-8",
            )
        status, payload = self.responses[path]
        if status != 200:
            raise Undetermined(f"/api/{path} 回 {status}")
        return payload

    def _fetch(self, path: str) -> tuple[int, Any]:
        url = f"{self.api_base}/api/{path}"
        last: tuple[int, Any] = (0, "")
        for attempt in range(1, API_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(url, timeout=API_TIMEOUT_S) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                last = (error.code, error.read().decode("utf-8", "replace")[:2000])
                if error.code < 500:
                    return last
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last = (0, str(error))
            time.sleep(attempt)
        return last

    def facts(self, stock: Stock | None = None) -> dict:
        key = (stock.exchange, stock.symbol) if stock else ()
        if key not in self._facts:
            self._facts[key] = db_facts.facts(self.db, key or None)
            name = f"facts-{stock.prefix}.json" if stock else "facts.json"
            (self.out / name).write_text(
                json.dumps(self._facts[key], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return self._facts[key]

    # -- screenshots --

    def shoot(self, shot: Shot) -> dict[int, dict]:
        """Run screenshot.cjs once per shot (retried when a width is not ready)."""

        if shot.name in self.shots:
            return self.shots[shot.name]
        shots_dir = self.out / "shots"
        command = [
            "node",
            str(SCREENSHOT),
            "--url",
            f"{self.web_base}{shot.path}",
            "--out",
            str(shots_dir),
            "--name",
            shot.name,
            "--widths",
            ",".join(str(width) for width in shot.widths),
        ]
        for selector in shot.clicks:
            command += ["--click", selector]
        if self.browser:
            command += ["--browser", self.browser]
        results: dict[int, dict] = {}
        for attempt in range(1, SHOT_ATTEMPTS + 1):
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=SHOT_TIMEOUT_S,
                )
                stdout, stderr = completed.stdout, completed.stderr
            except subprocess.TimeoutExpired as error:
                stdout = error.stdout or ""
                stderr = f"screenshot.cjs timed out after {SHOT_TIMEOUT_S} s"
                stdout = stdout.decode() if isinstance(stdout, bytes) else stdout
            with open(shots_dir / f"{shot.name}.jsonl", "a", encoding="utf-8") as log:
                log.write(stdout)
            results = {}
            for line in stdout.splitlines():
                if line.startswith("{"):
                    meta = json.loads(line)
                    results[meta["width"]] = meta
            for width in shot.widths:
                results.setdefault(
                    width,
                    {"width": width, "ready": False, "error": stderr.strip()[-500:]},
                )
            if all(meta.get("ready") for meta in results.values()):
                break
            if attempt < SHOT_ATTEMPTS:
                print(
                    f"screenshot {shot.name}: not ready, retrying ({stderr.strip()[-200:]})",
                    file=sys.stderr,
                )
        self.shots[shot.name] = results
        return results

    def text(self, shot: Shot, width: int = 1280) -> Text:
        meta = self.shoot(shot)[width]
        if not meta.get("ready"):
            raise Undetermined(
                f"{shot.name}-{width} 未 ready"
                + (f"（{meta['error']}）" if meta.get("error") else "")
                + (
                    f"，missingClicks {meta['missingClicks']}"
                    if meta.get("missingClicks")
                    else ""
                )
            )
        path = Path(meta["txt"])
        return Text(f"{shot.name}-{width}.txt", path.read_text(encoding="utf-8"))

    # -- values passed between pages (features/README.md) --

    def dashboard(self) -> dict:
        return self.get("dashboard", "dashboard.json")

    def today_board(self) -> dict:
        return self.get("themes?board=industry&limit=10", "today-board.json")

    def D(self) -> str:
        as_of = self.dashboard().get("as_of")
        if not as_of:
            raise Undetermined("dashboard.json 沒有 as_of（D）")
        return as_of[:10]

    def B(self) -> str:
        day = self.today_board()["meta"].get("trading_date")
        if not day:
            raise Undetermined("today-board.json 沒有 meta.trading_date（B）")
        return day

    def T(self) -> tuple[str, str]:
        items = self.today_board().get("items") or []
        if not items:
            raise Undetermined("today-board.json 的 items 為空（T）")
        return items[0]["theme_id"], items[0]["display_name"]

    def theme_members(self) -> dict:
        theme_id, _ = self.T()
        return self.get(
            f"themes/{theme_id}/members?page=1&page_size=30&sort=price",
            "theme-members.json",
        )

    def path_stock(self) -> Stock:
        items = self.theme_members().get("items") or []
        if not items:
            raise Undetermined("theme-members.json 的 items 為空（E、S）")
        return Stock(items[0]["exchange"], items[0]["symbol"])


# ---- shots per page ----


def today_shots(run: Run) -> list[Shot]:
    return [Shot("today", "/")]


def news_shots(run: Run) -> list[Shot]:
    shots = [
        Shot("news", "/news"),
        Shot("news-international", "/news?tab=international", (1280,)),
        Shot("news-official", "/news?tab=official", (1280,)),
    ]
    try:
        shots.append(Shot("news-detail", f"/news/{news_detail_id(run)}"))
    except Fail:
        pass  # N6 reports the missing id
    return shots


def themes_shots(run: Run) -> list[Shot]:
    shots = [
        Shot("themes", "/themes"),
        Shot("themes-theme", "/themes?board=theme", (1280,)),
    ]
    try:
        shots.append(Shot("theme-detail", f"/themes/{run.T()[0]}"))
    except Fail:
        pass
    return shots


def stock_shots(stock: Stock) -> dict[str, Shot]:
    url = f"/stocks/{stock.exchange}/{stock.symbol}"
    tabs = {
        tab: Shot(f"{stock.prefix}-{tab}", url, (1280,), (f"#stock-tab-{tab}",))
        for tab in ("chips", "research", "news", "data")
    }
    return {"main": Shot(stock.prefix, url), **tabs}


def stocks_shots(run: Run, stocks: list[Stock]) -> list[Shot]:
    shots = [Shot("stocks", "/stocks")]
    for stock in stocks:
        shots += stock_shots(stock).values()
    return shots


def action_detail_shot(stock: Stock) -> Shot:
    return Shot(
        "action-detail",
        f"/actions/{stock.exchange}/{stock.symbol}",
        (1280,),
        ("#stock-tab-research",),
    )


def actions_shots(run: Run) -> list[Shot]:
    shots = [Shot("actions", "/actions")]
    try:
        shots.append(action_detail_shot(run.path_stock()))
    except Fail:
        pass
    return shots


def usable(run: Run, shots: list[Shot]) -> str:
    """T1/N1/G1/S1/A1: every width ready, no failed /api/, console error or overflow."""

    problems, count = [], 0
    for shot in shots:
        for width, meta in run.shoot(shot).items():
            count += 1
            where = f"{shot.name}-{width}"
            if not meta.get("ready"):
                problems.append(f"{where} 未 ready {meta.get('error', '')}".strip())
            for key in ("missingClicks", "httpErrors", "consoleErrors"):
                if meta.get(key):
                    problems.append(f"{where} {key} {meta[key]}")
            if meta.get("overflow"):
                problems.append(
                    f"{where} 橫向捲動 scrollWidth {meta['scrollWidth']} > clientWidth {meta['clientWidth']}"
                )
    expect(not problems, "；".join(problems))
    return f"{count} 張截圖 ready，無錯誤，無橫向捲動"


# ---- registry ----

CheckFn = Callable[..., str]
CHECKS: dict[str, dict[str, CheckFn]] = {page: {} for page in PAGES}
PER_STOCK: set[str] = set()  # stocks checks that run once per Stock


def check(page: str, code: str, per_stock: bool = False):
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[page][code] = fn
        if per_stock:
            PER_STOCK.add(code)
        return fn

    return register


# ---- today ----

TODAY = Shot("today", "/")


@check("today", "T1")
def t1(run: Run) -> str:
    return usable(run, today_shots(run))


@check("today", "T2")
def t2(run: Run) -> str:
    text, d = run.text(TODAY), run.D()
    expect(text.has(f"資料 {d}"), f"缺整行 `資料 {d}`（{text.name}）")
    latest = run.facts()["market_latest_trading_date"]
    expect(d == latest, f"D {d} ≠ facts market_latest_trading_date {latest}")
    return f"`資料 {d}` = facts {latest}"


@check("today", "T3")
def t3(run: Run) -> str:
    text, d = run.text(TODAY), run.D()
    i = text.find("資料截至")
    expect(i >= 0, f"缺整行 `資料截至`（{text.name}）")
    expect(
        text.after(i) == slash(d),
        f"`資料截至` 下一行是 {text.after(i)!r}，預期 {slash(d)!r}（{text.at(i)}）",
    )
    source = text.after(i, 2)
    label = (run.dashboard().get("market") or {}).get("source_label")
    expect(bool(source), f"`資料截至` 之後缺來源行（{text.at(i)}）")
    if label is not None:
        expect(source == label, f"來源行 {source!r} ≠ market.source_label {label!r}")
    return f"`資料截至` → {slash(d)} → {source}"


def first_data_line_after(text: Text, title: str) -> tuple[int, str | None]:
    i = text.find(title)
    expect(i >= 0, f"缺整行 `{title}`（{text.name}）")
    j = text.find_where(lambda line: line.startswith("資料 "), i + 1)
    return j, text.lines[j] if j >= 0 else None


@check("today", "T4")
def t4(run: Run) -> str:
    text, b = run.text(TODAY), run.B()
    j, line = first_data_line_after(text, "熱門族群")
    expect(
        line == f"資料 {slash(b)}",
        f"`熱門族群` 後第一個資料行是 {line!r}，預期 `資料 {slash(b)}`（{text.at(j)}）",
    )
    latest = run.facts()["group_scores_latest_trading_date"]
    expect(b == latest, f"B {b} ≠ facts group_scores_latest_trading_date {latest}")
    return f"`{line}`；B = facts {latest}"


def board_empty_message(board: dict) -> str:
    return (board.get("meta") or {}).get("empty_message") or "此榜目前沒有族群"


@check("today", "T5")
def t5(run: Run) -> str:
    text, board, b = run.text(TODAY), run.today_board(), run.B()
    items = board.get("items") or []
    if not items:
        message = board_empty_message(board)
        expect(text.has(message), f"items 空，缺空資料文案 `{message}`")
        return f"items 空，顯示 `{message}`"
    marker = f"資料 {slash(b)} · 相對加權指數"
    cards = text.count(lambda line: line == marker)
    expect(
        cards == min(10, len(items)),
        f"`{marker}` {cards} 行，預期 {min(10, len(items))}",
    )
    name = items[0]["display_name"]
    expect(text.has(name), f"缺整行 items[0].display_name `{name}`")
    return f"{cards} 張卡 `{marker}`；#1 `{name}`"


def usable_ai(ai: Any) -> bool:
    """The frontend's usableAi (features/news.md 陷阱)."""

    return (
        isinstance(ai, dict)
        and ai.get("status") == "done"
        and ai.get("inference") is True
    )


@check("today", "T6")
def t6(run: Run) -> str:
    text = run.text(TODAY)
    news = (run.dashboard().get("news") or [])[:3]
    if not news:
        message = "市場新聞區尚無可顯示內容。"
        expect(text.has(message), f"dashboard.news 空，缺 `{message}`")
        return f"dashboard.news 空，顯示 `{message}`"
    starts = []
    for item in news:
        i = text.find(item["title"])
        expect(i >= 0, f"缺新聞標題整行 `{item['title']}`（id {item['id']}）")
        starts.append(i)
    end = text.find("熱門族群")
    bounds = sorted(starts) + [end if end >= 0 else len(text.lines)]
    problems, marked = [], 0
    for item, start in zip(news, starts):
        detail = run.get(f"news/{item['id']}", f"news-{item['id']}.json")
        if not usable_ai(detail.get("ai")):
            continue
        stop = bounds[bounds.index(start) + 1]
        card = text.lines[start:stop]
        if "影響尚未判定" in card:
            problems.append(
                f"id {item['id']} 有 AI 判讀卻顯示 `影響尚未判定`（{text.at(start)}）"
            )
        elif "AI 推論" not in card:
            problems.append(f"id {item['id']} 有 AI 判讀但卡片沒有 `AI 推論`")
        else:
            marked += 1
    expect(not problems, "；".join(problems))
    return f"前 {len(news)} 則標題都在；有 AI 判讀的 {marked} 張卡有 `AI 推論`"


def candidates(run: Run) -> dict:
    return run.get("candidates", "candidates.json")


def source_lines(text: Text) -> list[int]:
    return [i for i, line in enumerate(text.lines) if line.startswith("來源：")]


@check("today", "T7")
def t7(run: Run) -> str:
    text, payload = run.text(TODAY), candidates(run)
    items = payload.get("items") or []
    if payload.get("status") == "not_computed":
        expect(text.has("尚無候選清單"), "status not_computed，缺 `尚無候選清單`")
        return "not_computed，顯示 `尚無候選清單`"
    if not items:
        expect(text.has("當日零候選"), "items 空，缺 `當日零候選`")
        return "items 空，顯示 `當日零候選`"
    c = payload["trading_date"]
    i = text.find("明日候選")
    expect(i >= 0, "缺整行 `明日候選`")
    expect(
        text.after(i) == f"資料 {slash(c)}",
        f"`明日候選` 下一行是 {text.after(i)!r}，預期 `資料 {slash(c)}`（{text.at(i)}）",
    )
    count_line = f"{payload['candidate_count']} 檔"
    expect(
        text.after(i, 2) == count_line,
        f"再下一行是 {text.after(i, 2)!r}，預期 `{count_line}`",
    )
    sources = len(source_lines(text))
    expect(sources == len(items), f"`來源：` 行 {sources}，items {len(items)}")
    latest = run.facts()["candidate_run_latest_trading_date"]
    expect(c == latest, f"C {c} ≠ facts candidate_run_latest_trading_date {latest}")
    return f"`資料 {slash(c)}`、`{count_line}`；來源行 {sources} = items；C = facts"


def news_inference(item: dict) -> bool:
    components = item.get("components") or {}
    return bool((components.get("news_sentiment") or {}).get("inference"))


@check("today", "T8")
def t8(run: Run) -> str:
    text, payload = run.text(TODAY), candidates(run)
    items = payload.get("items") or []
    if payload.get("status") == "not_computed" or not items:
        return "沒有候選，不適用"
    rows = source_lines(text)
    expect(len(rows) == len(items), f"`來源：` 行 {len(rows)}，items {len(items)}")
    problems = [
        f"#{n} {item['instrument']['symbol']} 來源行沒有以 `（推論）` 結尾（{text.at(row)}）"
        for n, (item, row) in enumerate(zip(items, rows), start=1)
        if news_inference(item) and not text.lines[row].endswith("（推論）")
    ]
    expect(not problems, "；".join(problems))
    notes = text.count(lambda line: line == "AI 推論")
    expect(notes >= len(items), f"`AI 推論` {notes} 行 < items {len(items)}")
    disclaimers = text.count(lambda line: line == CANDIDATE_DISCLAIMER)
    expect(disclaimers == len(items), f"免責句 {disclaimers} 行，items {len(items)}")
    inferred = sum(news_inference(item) for item in items)
    return f"{inferred} 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` {notes} 行；免責句 {disclaimers} 行"


@check("today", "T9")
def t9(run: Run) -> str:
    text = run.text(TODAY)
    k = text.count(lambda line: line == "查看個股詳情 →")
    if k == 0:
        message = (run.dashboard().get("empty_states") or {}).get(
            "actions"
        ) or "目前沒有可顯示的行動摘要。"
        expect(text.has(message), f"沒有卡片，缺空資料文案 `{message}`")
        return f"沒有卡片，顯示 `{message}`"
    dates = text.count(lambda line: bool(DATE_LINE.match(line)))
    expect(dates == k, f"`查看個股詳情 →` {k} 行，`資料日 YYYY/MM/DD` {dates} 行")
    return f"{k} 張卡各有 `資料日`"


# ---- news ----

NEWS_TABS = {
    "domestic": (
        "news?category=domestic&limit=20",
        "news-domestic.json",
        Shot("news", "/news"),
        "目前沒有符合條件的國內新聞。",
    ),
    "international": (
        "news?category=international&limit=20",
        "news-international.json",
        Shot("news-international", "/news?tab=international", (1280,)),
        "目前沒有符合條件的國際新聞。",
    ),
    "official": (
        "news?source_kind=official_disclosure&limit=20",
        "news-official.json",
        Shot("news-official", "/news?tab=official", (1280,)),
        "目前沒有符合條件的官方公告。",
    ),
}


def news_items(run: Run, tab: str) -> list[dict]:
    path, name, _shot, _empty = NEWS_TABS[tab]
    return run.get(path, name).get("items") or []


def news_text(run: Run, tab: str) -> Text:
    return run.text(NEWS_TABS[tab][2])


def news_source_label(source: str | None) -> str:
    """Same as newsSourceLabel in frontend/src/presentation.ts."""

    if not source:
        return "官方公告資料"
    value = source.strip()
    lowered = value.lower()
    if lowered == "mops" or lowered.startswith("mops_"):
        return "公開資訊觀測站公告"
    if lowered.startswith("tpex"):
        return "櫃買中心官方資料"
    if lowered.startswith("twse"):
        return "證交所官方資料"
    return value if "官方" in value else "官方公告資料"


def news_detail_id(run: Run) -> Any:
    items = news_items(run, "domestic")
    if not items:
        raise Undetermined("news-domestic.json 的 items 為空，沒有詳情 id")
    done = [item for item in items if (item.get("ai") or {}).get("status") == "done"]
    return (done or items)[0]["id"]


@check("news", "N1")
def n1(run: Run) -> str:
    return usable(run, news_shots(run))


def in_order(text: Text, wanted: list[str]) -> str | None:
    """None when every line appears whole and in order, else what is missing."""

    position = 0
    for line in wanted:
        i = text.find(line, position)
        if i < 0:
            return f"缺 `{line}`" + ("（或順序不對）" if text.has(line) else "")
        position = i + 1
    return None


@check("news", "N2")
def n2(run: Run) -> str:
    notes, problems = [], []
    for tab, (_path, _name, _shot, empty) in NEWS_TABS.items():
        items, text = news_items(run, tab), news_text(run, tab)
        if not items:
            if not text.has(empty):
                problems.append(f"{tab}：items 空，缺 `{empty}`")
            notes.append(f"{tab} 空")
            continue
        if tab == "official":
            wanted = []
            for item in items[:3]:
                wanted.append(news_source_label(item.get("source_name")))
                if item.get("event_date"):
                    wanted.append(f"事件日 {slash(item['event_date'])}")
        else:
            wanted = [item["title"] for item in items[:3]]
        missing = in_order(text, wanted)
        if missing:
            problems.append(f"{tab}：{missing}（{text.name}）")
        notes.append(f"{tab} 前 {min(3, len(items))} 則")
    expect(not problems, "；".join(problems))
    return "、".join(notes) + "依序出現"


@check("news", "N3")
def n3(run: Run) -> str:
    notes, problems = [], []
    for tab in NEWS_TABS:
        items, text = news_items(run, tab), news_text(run, tab)
        lines = text.count(lambda line: bool(TIME_LINE.match(line)))
        notes.append(f"{tab} {lines}／{len(items)}")
        if lines != len(items):
            problems.append(f"{tab}：時間行 {lines}，items {len(items)}")
    expect(not problems, "；".join(problems))
    return "時間行 " + "、".join(notes)


@check("news", "N4")
def n4(run: Run) -> str:
    notes, problems = [], []
    for tab in NEWS_TABS:
        items, text = news_items(run, tab), news_text(run, tab)
        done = sum(usable_ai(item.get("ai")) for item in items)
        marks = text.count(lambda line: line == "AI 推論")
        notes.append(f"{tab} {marks}／{done}")
        if marks != done:
            problems.append(f"{tab}：`AI 推論` {marks} 行，API 有 AI 判讀 {done} 則")
    expect(not problems, "；".join(problems))
    return "`AI 推論`／AI 判讀 " + "、".join(notes)


@check("news", "N5")
def n5(run: Run) -> str:
    latest = run.facts()["news_latest_published_at"]
    expect(latest is not None, "facts news_latest_published_at 為 null")
    published = datetime.fromisoformat(str(latest)[:19]) + timedelta(hours=8)
    now = run.now.astimezone(TAIPEI).replace(tzinfo=None)
    expect(published <= now, f"最新新聞 {published}（台北）晚於現在 {now:%F %T}")
    text = news_text(run, "domestic")
    i = text.find_where(lambda line: bool(TIME_LINE.match(line)))
    expect(i >= 0, "國內分頁沒有時間行")
    found = re.search(r"([0-9]{4})/([0-9]{2})/([0-9]{2})", text.lines[i])
    if found:
        day = datetime(*map(int, found.groups())).date()
        expect(day <= now.date(), f"國內第一則 {text.lines[i]!r} 晚於今天 {now.date()}")
    return f"最新新聞 {published:%F %H:%M}（台北）≤ 現在；國內第一則 `{text.lines[i]}`"


@check("news", "N6")
def n6(run: Run) -> str:
    news_id = news_detail_id(run)
    detail = run.get(f"news/{news_id}", "news-detail.json")
    text = run.text(Shot("news-detail", f"/news/{news_id}"))
    expect(text.has("來源事實"), "缺整行 `來源事實`")
    i = text.find("AI 摘要與判讀")
    expect(i >= 0, "缺整行 `AI 摘要與判讀`")
    expect(
        text.after(i) == "AI 推論",
        f"`AI 摘要與判讀` 下一行是 {text.after(i)!r}，預期 `AI 推論`",
    )
    ai = detail.get("ai") or {}
    if ai.get("status") == "done":
        prefix = f"模型 {ai.get('model')} · 提示版本 {ai.get('prompt_version')}"
        expect(
            text.find_where(lambda line: line.startswith(prefix)) >= 0,
            f"缺 `{prefix}` 開頭的行",
        )
        return f"id {news_id}：來源事實／AI 摘要與判讀分欄，`{prefix}`"
    expect(text.has("此則尚未產生 AI 摘要與判讀。"), "ai 未完成，缺空狀態文案")
    return f"id {news_id}：AI 未完成，顯示空狀態"


# ---- themes ----

THEMES = Shot("themes", "/themes")
THEMES_THEME = Shot("themes-theme", "/themes?board=theme", (1280,))


def board(run: Run, kind: str) -> dict:
    return run.get(f"themes?board={kind}&limit=100", f"themes-{kind}.json")


def theme_detail(run: Run) -> tuple[dict, Text]:
    theme_id, _ = run.T()
    payload = run.get(f"themes/{theme_id}", "theme-detail.json")
    return payload, run.text(Shot("theme-detail", f"/themes/{theme_id}"))


@check("themes", "G1")
def g1(run: Run) -> str:
    return usable(run, themes_shots(run))


@check("themes", "G2")
def g2(run: Run) -> str:
    latest = run.facts()["group_scores_latest_trading_date"]
    notes, problems = [], []
    for kind, title, shot in (
        ("industry", "產業榜", THEMES),
        ("theme", "題材榜", THEMES_THEME),
    ):
        payload, text = board(run, kind), run.text(shot)
        meta = payload.get("meta") or {}
        b = meta.get("trading_date")
        heading = f"{title} · 共 {meta.get('total')} 個族群"
        i = text.find(heading)
        if i < 0:
            problems.append(f"缺整行 `{heading}`（{text.name}）")
            continue
        if text.after(i) != f"資料 {slash(b or '')}":
            problems.append(
                f"`{heading}` 下一行是 {text.after(i)!r}，預期 `資料 {slash(b or '')}`（{text.at(i)}）"
            )
        if b != latest:
            problems.append(f"{title} B {b} ≠ facts {latest}")
        notes.append(f"`{heading}` → `資料 {slash(b or '')}`")
    expect(not problems, "；".join(problems))
    return "、".join(notes) + f"；= facts {latest}"


@check("themes", "G3")
def g3(run: Run) -> str:
    payload = board(run, "industry")
    items = payload.get("items") or []
    wide, narrow = run.text(THEMES), run.text(THEMES, 390)
    if not items:
        message = board_empty_message(payload)
        expect(wide.has(message), f"items 空，缺 `{message}`")
        return f"items 空，顯示 `{message}`"
    expect(
        wide.find_where(lambda line: line.startswith("排名\t族群")) >= 0,
        "1280 缺 `排名\\t族群` 開頭的表頭",
    )
    first, last = items[0]["display_name"], items[-1]["display_name"]
    for name in (first, last):
        expect(wide.has(name), f"1280 缺整行 `{name}`")
    i = narrow.find("#1")
    expect(i >= 0, "390 缺整行 `#1`")
    expect(
        narrow.after(i) == first,
        f"390 `#1` 下一行是 {narrow.after(i)!r}，預期 `{first}`",
    )
    return f"1280 表頭與 `{first}`…`{last}`；390 `#1` → `{first}`"


@check("themes", "G4")
def g4(run: Run) -> str:
    payload = run.get("theme-suggestions?limit=20", "theme-suggestions.json")
    items, text = payload.get("items") or [], run.text(THEMES)
    if not items:
        expect(text.has("目前沒有新聞題材建議"), "items 空，缺 `目前沒有新聞題材建議`")
        return "items 空，顯示 `目前沒有新聞題材建議`"
    pending = text.count(lambda line: line == "待核實")
    marks = text.count(lambda line: line == "AI 推論")
    expect(pending >= len(items), f"`待核實` {pending} 行 < items {len(items)}")
    expect(marks >= len(items), f"`AI 推論` {marks} 行 < items {len(items)}")
    total = f"{(payload.get('meta') or {}).get('total')} 個建議"
    expect(
        text.find_where(lambda line: line.startswith(total)) >= 0,
        f"缺 `{total}` 開頭的行",
    )
    return f"{len(items)} 個建議：`待核實` {pending}、`AI 推論` {marks} 行，`{total}`"


def members(run: Run) -> dict:
    return run.theme_members()


@check("themes", "G5")
def g5(run: Run) -> str:
    _payload, text = theme_detail(run)
    b = board(run, "industry")["meta"].get("trading_date") or ""
    for title in ("熱度走勢", "五分項"):
        i = text.find(title)
        expect(i >= 0, f"缺整行 `{title}`")
        expect(
            text.after(i) == f"資料 {slash(b)}",
            f"`{title}` 下一行是 {text.after(i)!r}，預期 `資料 {slash(b)}`（{text.at(i)}）",
        )
    m = (members(run).get("meta") or {}).get("data_as_of")
    expect(m is not None, "theme-members.json 沒有 meta.data_as_of（M）")
    line = f"成員資料截至 {slash(m)}"
    expect(
        text.find_where(lambda value: value.startswith(line)) >= 0, f"缺 `{line}` 這行"
    )
    return f"熱度走勢、五分項皆 `資料 {slash(b)}`；`{line}`"


@check("themes", "G6")
def g6(run: Run) -> str:
    _payload, text = theme_detail(run)
    header = "代號\t名稱\t市場\t角色\t收盤\t資料日期"
    expect(text.find_where(lambda line: line.startswith(header)) >= 0, "缺成員表頭")
    payload = members(run)
    items, total = (
        payload.get("items") or [],
        (payload.get("meta") or {}).get("total") or 0,
    )
    if items:
        symbol, name = items[0]["symbol"], items[0]["name"]
        expect(
            text.find_where(lambda line: symbol in line and name in line) >= 0,
            f"沒有同時含 `{symbol}` 與 `{name}` 的行",
        )
    pages = math.ceil(total / 30)
    # MemberPager (frontend/src/themes/ThemeViews.tsx) drops the page part for one page.
    pager = f"第 1／{pages} 頁 · 共 {total:,} 檔" if pages > 1 else f"共 {total:,} 檔"
    expect(text.has(pager), f"缺整行 `{pager}`")
    first = f"{items[0]['symbol']} {items[0]['name']}" if items else "（無成員）"
    return f"表頭、第一個成員 {first}、`{pager}`"


@check("themes", "G7")
def g7(run: Run) -> str:
    today = run.text(TODAY)
    start = today.find("熱門族群")
    i = today.find("#1", max(start, 0))
    expect(i >= 0, "今日頁 `熱門族群` 之後缺 `#1`")
    today_name = today.after(i)
    board_name = (board(run, "industry").get("items") or [{}])[0].get("display_name")
    payload, text = theme_detail(run)
    detail_name = (payload.get("theme") or {}).get("display_name")
    expect(
        today_name == board_name == detail_name,
        f"今日 #1 {today_name!r}、產業榜 #1 {board_name!r}、詳情 {detail_name!r} 不一致",
    )
    back = text.find_where(
        lambda line: line.startswith("← 回到") and line.endswith("榜")
    )
    expect(back >= 0, "詳情缺 `← 回到…榜`")
    stop = text.find_where(lambda line: line.startswith("排名"), back + 1)
    stop = stop if stop >= 0 else len(text.lines)
    expect(
        detail_name in text.lines[back + 1 : stop],
        f"詳情 `{text.lines[back]}` 與 `排名` 之間沒有整行 `{detail_name}`",
    )
    return f"今日 #1 = 產業榜 #1 = 詳情 = `{detail_name}`"


# ---- stocks ----


def stock_payload(run: Run, stock: Stock) -> dict:
    suffix = "" if stock.prefix == "stock" else stock.prefix[len("stock") :]
    return run.get(f"stocks/{stock.exchange}/{stock.symbol}", f"stock{suffix}.json")


def stock_bars(run: Run, stock: Stock) -> dict:
    suffix = "" if stock.prefix == "stock" else stock.prefix[len("stock") :]
    return run.get(
        f"stocks/{stock.exchange}/{stock.symbol}/bars?interval=day&limit=250",
        f"stock-bars{suffix}.json",
    )


def stock_news(run: Run, stock: Stock) -> dict:
    suffix = "" if stock.prefix == "stock" else stock.prefix[len("stock") :]
    return run.get(f"news?symbol={stock.symbol}&limit=50", f"stock-news{suffix}.json")


def stock_I(run: Run, stock: Stock) -> str:
    day = (run.facts(stock).get("instrument") or {}).get("latest_trading_date")
    if not day:
        raise Undetermined(f"facts-{stock.prefix}.json 沒有 latest_trading_date（I）")
    return day


def stock_text(run: Run, stock: Stock, tab: str = "main", width: int = 1280) -> Text:
    return run.text(stock_shots(stock)[tab], width)


@check("stocks", "S1", per_stock=True)
def s1(run: Run, stock: Stock) -> str:
    shots = list(stock_shots(stock).values())
    if stock.prefix == "stock":
        shots.insert(0, Shot("stocks", "/stocks"))
    return usable(run, shots)


@check("stocks", "S2")
def s2(run: Run, stock: Stock) -> str:
    payload = run.get("stocks?page=1&page_size=30", "stocks.json")
    text = run.text(Shot("stocks", "/stocks"))
    header = "代號\t名稱\t交易所\t類型\t最近收盤\t目前研究動作\t策略判斷資料"
    expect(text.has(header), "缺目錄表頭整行")
    items = payload.get("items") or []
    total = (payload.get("meta") or {}).get("total") or 0
    if items:
        symbol = items[0]["instrument"]["symbol"]
        expect(
            text.find_where(lambda line: line.startswith(symbol)) >= 0,
            f"缺 `{symbol}` 開頭的列",
        )
    else:
        expect(text.has("沒有符合條件的標的。"), "items 空，缺空資料文案")
    pager = f"第 1／{max(1, math.ceil(total / 30))} 頁 · 共 {total:,} 筆"
    expect(text.has(pager), f"缺整行 `{pager}`")
    return f"表頭、第一列、`{pager}`"


@check("stocks", "S3", per_stock=True)
def s3(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock), stock_I(run, stock)
    expect(text.has(stock.symbol), f"缺整行 `{stock.symbol}`")
    data = [n for n, line in enumerate(text.lines) if line.startswith("資料 ")]
    expect(len(data) >= 2, f"`資料 ` 開頭的行只有 {len(data)} 行")
    d = run.D()
    expect(
        text.lines[data[0]] == f"資料 {d}",
        f"第一個資料行 {text.lines[data[0]]!r}，預期導覽列 `資料 {d}`",
    )
    expect(
        text.lines[data[1]] == f"資料 {i}",
        f"第二個資料行 {text.lines[data[1]]!r}，預期 `資料 {i}`（{text.at(data[1])}）",
    )
    source = text.after(data[1]) or ""
    expect(
        source.startswith("來源 ") and source != "來源 尚無已核對的價格來源",
        f"頁首資料行下一行是 {source!r}",
    )
    bars_as_of = stock_bars(run, stock).get("data_as_of")
    expect(i == bars_as_of, f"I {i} ≠ stock-bars data_as_of {bars_as_of}")
    return f"頁首 `資料 {i}`、`{source}`；bars data_as_of {bars_as_of}"


@check("stocks", "S4", per_stock=True)
def s4(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock), stock_I(run, stock)
    k = text.find("K 線與技術指標")
    expect(k >= 0, "缺整行 `K 線與技術指標`")
    expect(
        text.after(k) == f"資料 {i}",
        f"`K 線與技術指標` 下一行是 {text.after(k)!r}，預期 `資料 {i}`",
    )
    for prefix in ("來源 ", "日線批次計算於"):
        expect(
            text.find_where(lambda line: line.startswith(prefix)) >= 0,
            f"缺 `{prefix}` 開頭的行",
        )
    return f"K 線卡 `資料 {i}`、來源與批次時間"


@check("stocks", "S5", per_stock=True)
def s5(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock, "research"), stock_I(run, stock)
    payload = stock_payload(run, stock)
    expect(text.has("研究動作"), "缺整行 `研究動作`")
    if payload.get("decision_summary") is None:
        expect(text.has("尚無行動摘要。"), "decision_summary null，缺 `尚無行動摘要。`")
        note = "decision_summary null，顯示 `尚無行動摘要。`"
    else:
        for prefix in (f"資料日期：{slash(i)}", f"資料日：{slash(i)} · 價位語意："):
            expect(
                text.find_where(lambda line: line.startswith(prefix)) >= 0,
                f"缺 `{prefix}` 開頭的行",
            )
        note = f"`資料日期：{slash(i)}`、`資料日：{slash(i)} · 價位語意：`"
    if payload.get("candidate") is not None:
        expect(text.has("明日候選"), "candidate 非 null，缺整行 `明日候選`")
        expect(text.has("AI 推論"), "candidate 非 null，缺 `AI 推論`")
        rows = source_lines(text)
        expect(rows, "candidate 非 null，缺 `來源：` 行")
        bad = [text.at(row) for row in rows if not text.lines[row].endswith("（推論）")]
        expect(not bad, f"`來源：` 行沒有以 `（推論）` 結尾：{'、'.join(bad)}")
        note += f"；候選 #{payload['candidate'].get('rank')}：`明日候選`、`AI 推論`、`（推論）`"
    return note


@check("stocks", "S6", per_stock=True)
def s6(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock, "news")
    title = f"{stock.symbol} 相關新聞"
    expect(text.has(title), f"缺整行 `{title}`")
    matched = sum(
        any(
            ref.get("exchange") == stock.exchange and ref.get("symbol") == stock.symbol
            for ref in item.get("instruments") or []
        )
        for item in stock_news(run, stock).get("items") or []
    )
    if matched == 0:
        message = "尚無與此股已核實關聯的新聞或公告。"
        expect(text.has(message), f"0 則相符新聞，缺 `{message}`")
        return f"0 則相符新聞，顯示 `{message}`"
    lines = text.count(lambda line: bool(TIME_LINE.match(line)))
    expect(lines >= 1, f"{matched} 則相符新聞，但沒有時間行")
    return f"{matched} 則相符新聞，時間行 {lines}"


@check("stocks", "S7", per_stock=True)
def s7(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock, "data"), stock_I(run, stock)
    k = text.find("K 線資料日期")
    expect(k >= 0, "缺整行 `K 線資料日期`")
    expect(text.after(k) == i, f"`K 線資料日期` 下一行是 {text.after(k)!r}，預期 `{i}`")
    s = text.find("行情來源")
    expect(s >= 0, "缺整行 `行情來源`")
    source = text.after(s)
    expect(bool(source) and source != "待核實", f"`行情來源` 下一行是 {source!r}")
    suffix = f"資料日 {slash(i)}"
    expect(
        text.find_where(lambda line: line.endswith(suffix)) >= 0,
        f"缺 `{suffix}` 結尾的行",
    )
    return f"K 線資料日期 {i}、行情來源 `{source}`、`…{suffix}`"


@check("stocks", "S8", per_stock=True)
def s8(run: Run, stock: Stock) -> str:
    instrument = run.facts(stock).get("instrument") or {}
    i = stock_I(run, stock)
    bars_as_of = stock_bars(run, stock).get("data_as_of")
    expect(i == bars_as_of, f"facts I {i} ≠ stock-bars data_as_of {bars_as_of}")
    expect(bool(instrument.get("source")), "facts instrument.source 為空")
    return f"facts I {i} = API；source `{instrument['source']}`"


@check("stocks", "S9", per_stock=True)
def s9(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock, "chips")
    for title in ("法人與融資", "券商／分點"):
        expect(text.has(title), f"缺整行 `{title}`")
    chips = stock_payload(run, stock).get("chips") or []
    if not chips:
        expect(
            text.has("尚無可核實的籌碼資料。"), "chips 空，缺 `尚無可核實的籌碼資料。`"
        )
        return "chips 空，顯示 `尚無可核實的籌碼資料。`"
    latest = f"{slash(chips[-1]['date'])}\t"
    expect(
        text.find_where(lambda line: line.startswith(latest)) >= 0,
        f"缺 `{latest.strip()}\\t` 開頭的行",
    )
    rows = text.count(lambda line: " · 資料截至：" in line)
    expect(
        rows == min(30, len(chips)),
        f"` · 資料截至：` {rows} 行，預期 {min(30, len(chips))}",
    )
    return f"最新一列 {latest.strip()}；來源行 {rows} = min(30, {len(chips)})"


# ---- actions ----

ACTIONS = Shot("actions", "/actions")


def actions_payload(run: Run) -> dict:
    return run.get("actions?limit=20", "actions.json")


@check("actions", "A1")
def a1(run: Run) -> str:
    return usable(run, actions_shots(run))


@check("actions", "A2")
def a2(run: Run) -> str:
    text = run.text(ACTIONS)
    items = (
        run.get("portfolio?page=1&page_size=20", "portfolio.json").get("items") or []
    )
    expect(text.has("我的庫存"), "缺整行 `我的庫存`")
    if not items:
        expect(text.has("尚未建立庫存。"), "items 空，缺 `尚未建立庫存。`")
        return "沒有庫存，顯示 `尚未建立庫存。`"
    rows = text.count(lambda line: line.startswith("記錄來源 "))
    expect(rows == len(items), f"`記錄來源 ` {rows} 行，items {len(items)}")
    return f"{rows} 筆庫存各有 `記錄來源`"


@check("actions", "A3")
def a3(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    items = payload.get("items") or []
    total = (payload.get("meta") or {}).get("total") or 0
    pager = f"第 1 頁 · 本頁 {len(items)} 筆 · 共 {total:,} 筆"
    expect(text.has(pager), f"缺整行 `{pager}`")
    return f"`{pager}`"


@check("actions", "A4")
def a4(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    k = text.count(lambda line: line == "查看個股詳情 →")
    dates = [m.group(1) for line in text.lines if (m := DATE_LINE.match(line))]
    expect(len(dates) == k, f"`查看個股詳情 →` {k} 行，`資料日` {len(dates)} 行")
    as_of = ((payload.get("meta") or {}).get("data_as_of") or "")[:10]
    expect(bool(as_of), "actions.json 沒有 meta.data_as_of")
    late = sorted({day for day in dates if day > slash(as_of)})
    expect(not late, f"卡片資料日 {late} 晚於 data_as_of {slash(as_of)}")
    latest = run.facts()["market_latest_trading_date"]
    expect(
        as_of == latest,
        f"data_as_of {as_of} ≠ facts market_latest_trading_date {latest}",
    )
    return f"{k} 張卡、{len(dates)} 行資料日 ≤ {slash(as_of)}；data_as_of = facts"


@check("actions", "A5")
def a5(run: Run) -> str:
    text = run.text(ACTIONS)
    hits = [
        text.at(i)
        for i, line in enumerate(text.lines)
        if "AI 推論" in line or "（推論）" in line
    ]
    expect(not hits, f"出現 LLM 推論標記：{'、'.join(hits)}")
    return "沒有 `AI 推論` 與 `（推論）`"


def action_detail(run: Run) -> tuple[Stock, dict, Text]:
    stock = run.path_stock()
    payload = run.get(f"actions/{stock.exchange}/{stock.symbol}", "action-detail.json")
    return stock, payload, run.text(action_detail_shot(stock))


@check("actions", "A6")
def a6(run: Run) -> str:
    stock, payload, text = action_detail(run)
    for line in (stock.symbol, "研究動作"):
        expect(text.has(line), f"缺整行 `{line}`")
    summary = payload.get("decision_summary")
    if summary is None:
        expect(text.has("尚無行動摘要。"), "decision_summary null，缺 `尚無行動摘要。`")
        return f"{stock.label}：顯示 `尚無行動摘要。`"
    i = text.find_where(lambda line: line.startswith("資料日："))
    expect(i >= 0, "缺 `資料日：` 開頭的行")
    want = slash(summary.get("data_cutoff") or "")
    got = text.lines[i][len("資料日：") :][:10]
    expect(got == want, f"`資料日：` 為 {got}，預期 data_cutoff {want}（{text.at(i)}）")
    return f"{stock.label}：`資料日：{got}` = data_cutoff"


@check("actions", "A7")
def a7(run: Run) -> str:
    stock, _payload, text = action_detail(run)
    instrument = stock_payload(run, stock).get("instrument") or {}
    symbol, name = instrument.get("symbol"), instrument.get("name")
    i = text.find(symbol or "")
    expect(i >= 0, f"缺整行 `{symbol}`")
    expect(
        text.after(i) == name,
        f"頁首 `{symbol}` 下一行是 {text.after(i)!r}，預期個股名稱 `{name}`（{text.at(i)}）",
    )
    return f"頁首 `{symbol}`／`{name}` = stock.json"


# ---- fixture expectations ----


def fixture_module():
    sys.path.insert(0, str(ROOT / "backend"))
    return _load(ROOT / "tools" / "verify" / "fixture_data.py", "fixture_data")


def expected_check(run: Run, fixture, page: str) -> str:
    """The page's APIs return fixture_data.EXPECTED (the fixture database only)."""

    problems = []
    for path, json_path, want in fixture.EXPECTED[page]:
        try:
            payload = run.get(path)
        except Fail as error:
            problems.append(str(error))
            continue
        got = fixture.actual_for(payload, json_path, want)
        if got != want:
            problems.append(f"/api/{path} {json_path}：預期 {want!r}，實際 {got!r}")
    expect(not problems, "；".join(problems))
    return f"{len(fixture.EXPECTED[page])} 項 = fixture_data.EXPECTED"


# ---- driver ----


def run_page(run: Run, page: str, stocks: list[Stock]) -> list[Result]:
    results = []
    for code, fn in CHECKS[page].items():
        subjects: list[Stock | None] = [None]
        if page == "stocks":
            subjects = list(stocks) if code in PER_STOCK else list(stocks[:1])
            if not subjects:
                try:
                    run.path_stock()
                except Fail as error:
                    results.append(Result(page, code, False, str(error)))
                continue
        for stock in subjects:
            label = stock.label if code in PER_STOCK and len(stocks) > 1 else ""
            try:
                detail = fn(run, stock) if page == "stocks" else fn(run)
                ok = True
            except Fail as error:
                detail, ok = str(error), False
            known = KNOWN_FAILURES.get((page, code))
            if known and ok:
                detail += f"；修好了就從 KNOWN_FAILURES 移除 {page} {code}"
            results.append(Result(page, code, ok, detail, label, known))
    return results


def stocks_for(run: Run, fixture) -> list[Stock]:
    try:
        stocks = [run.path_stock()]
    except Fail:
        return []  # run_page reports the missing E/S on every stocks check
    if fixture is not None:
        exchange, symbol = fixture.NO_DATA_STOCK
        stocks.append(Stock(exchange, symbol, f"stock-{exchange}-{symbol}"))
    return stocks


PAGE_SHOTS: dict[str, Callable[[Run, list[Stock]], list[Shot]]] = {
    "today": lambda run, stocks: today_shots(run),
    "news": lambda run, stocks: news_shots(run),
    "themes": lambda run, stocks: themes_shots(run),
    "stocks": stocks_shots,
    "actions": lambda run, stocks: actions_shots(run),
}


def prefetch(run: Run, pages: list[str], stocks: list[Stock], jobs: int) -> None:
    """Take every screenshot the pages need, ``jobs`` browsers at a time."""

    shots = {
        shot.name: shot for page in pages for shot in PAGE_SHOTS[page](run, stocks)
    }
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        list(pool.map(run.shoot, shots.values()))


def summary_markdown(
    results: list[Result], pages: list[str], head: str, evidence: bool = True
) -> str:
    """Per page tables; without ``evidence`` only each check's result (no page text)."""

    lines = [head, ""]
    names = {
        "today": "今日 `/`",
        "news": "新聞 `/news`",
        "themes": "族群 `/themes`",
        "stocks": "個股 `/stocks`",
        "actions": "行動 `/actions`",
    }
    for page in pages:
        rows = [r for r in results if r.page == page]
        verdict = "失敗" if any(r.failed for r in rows) else "通過"
        lines += [f"### {names[page]}：{verdict}", ""]
        if not evidence:
            lines += ["| 檢查 | 結果 |", "| --- | --- |"]
            lines += [f"| {r.label} | {r.status} |" for r in rows] + [""]
            continue
        lines += ["| 檢查 | 結果 | 證據 |", "| --- | --- | --- |"]
        for r in rows:
            detail = r.detail.replace("|", "\\|").replace("\t", "\\t")
            if r.known:
                detail += f"（已知：{r.known}）"
            lines.append(f"| {r.label} | {r.status} | {detail} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api", default=os.environ.get("VERIFY_API_URL"), help="API origin"
    )
    parser.add_argument(
        "--web", default=os.environ.get("VERIFY_WEB_URL"), help="preview origin"
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="the database the API reads"
    )
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--fixture", action="store_true", help="also compare with fixture_data.EXPECTED"
    )
    parser.add_argument(
        "--pages", default=",".join(PAGES), help="comma separated pages"
    )
    parser.add_argument("--browser", help="browser executable for screenshot.cjs")
    parser.add_argument("--jobs", type=int, default=4, help="screenshots taken at once")
    args = parser.parse_args(argv)
    if not args.api or not args.web:
        parser.error(
            "--api and --web (or $VERIFY_API_URL and $VERIFY_WEB_URL) are required"
        )
    pages = [page for page in args.pages.split(",") if page]
    unknown = sorted(set(pages) - set(PAGES))
    if unknown:
        parser.error(f"unknown pages: {unknown}")

    problems = registry_problems(feature_checks(), CHECKS)
    if problems:
        print("features 與 CHECKS 不一致：\n" + "\n".join(problems), file=sys.stderr)
        return 2

    started = time.monotonic()
    run = Run(args.api, args.web, args.db, args.out, args.browser)
    fixture = fixture_module() if args.fixture else None
    stocks = stocks_for(run, fixture)
    prefetch(run, pages, stocks, args.jobs)
    print(f"screenshots: {time.monotonic() - started:.1f} s", file=sys.stderr)
    results: list[Result] = []
    for page in pages:
        page_started = time.monotonic()
        if fixture is not None:
            try:
                detail, ok = expected_check(run, fixture, page), True
            except Fail as error:
                detail, ok = str(error), False
            results.append(Result(page, "API", ok, detail))
        results += run_page(run, page, stocks)
        for r in (r for r in results if r.page == page):
            print(
                f"{page} {r.label} {r.status} {r.detail}"
                + (f"（已知：{r.known}）" if r.known else "")
            )
        print(f"{page}: {time.monotonic() - page_started:.1f} s", file=sys.stderr)

    failed = [r for r in results if r.failed]
    head = (
        f"## verify 檢查結果（{run.now:%Y-%m-%d %H:%M} 台北）\n\n"
        f"- API `{args.api}`、前端 `{args.web}`、DB `{args.db.name}`"
        f"{'（假資料庫）' if fixture else ''}\n"
        f"- {len(results)} 項：通過 {sum(r.ok for r in results)}、"
        f"失敗 {len(failed)}、已知失敗 {sum(1 for r in results if r.known and not r.ok)}；"
        f"耗時 {time.monotonic() - started:.0f} 秒"
    )
    (args.out / "summary.md").write_text(
        summary_markdown(results, pages, head), encoding="utf-8"
    )
    (args.out / "status.md").write_text(
        summary_markdown(results, pages, head, evidence=False), encoding="utf-8"
    )
    (args.out / "results.json").write_text(
        json.dumps(
            [
                {
                    "page": r.page,
                    "code": r.code,
                    "subject": r.subject,
                    "status": r.status,
                    "failed": r.failed,
                    "detail": r.detail,
                    "known": r.known,
                }
                for r in results
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"{len(results)} checks, {len(failed)} failed"
        + (": " + ", ".join(f"{r.page} {r.label}" for r in failed) if failed else ""),
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
