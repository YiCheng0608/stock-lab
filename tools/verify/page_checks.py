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

Each check ends 通過, 失敗 or 無法判定 (Issue #251): 無法判定 when an API was not
200, a screenshot was not ready, or an upstream check (``OWNERS``, ``after``)
did not pass; 無法判定 is never counted as 失敗.  The stocks checks run on E/S
picked from today's #1 group, else candidate #1, else the first listed stock.
The checks that features label ``人工`` get their samples, picked by the rules
written in ``MANUAL``, in ``<out>/manual/<code>.json`` for an agent to judge.

Writes ``<out>/api/*.json``, ``<out>/shots/*.png|txt|jsonl``, ``<out>/manual/``,
``<out>/results.json``, ``<out>/summary.md`` and ``<out>/status.md`` (the same
tables without the evidence, for runs on private data) and prints one line per check.
Exit 0 when no check failed (a matching, unexpired ``KNOWN_FAILURES`` entry may
fail; with ``--fixture`` no check may be 無法判定 either), 1 when one did, 2 when the
features files and ``CHECKS``/``MANUAL`` disagree or ``--g7`` finds the program
is not the committed tip of G7_REF (the release branch).
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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "verify-stock-lab"
FEATURES = SKILL / "features"
SCREENSHOT = ROOT / "tools" / "ops" / "screenshot.cjs"
PAGES = ("today", "news", "themes", "stocks", "actions")
# The branch the scheduled jobs run during the V1 acceptance window (docs/ops/SCHEDULING.md).
G7_REF = "origin/release/v1"
TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Known:
    """A known product defect: the Issue, a fragment of the failure message it causes
    and the last Taipei day (ISO date) the entry counts."""

    issue: str
    match: str
    expires: str

    def expired(self, now: datetime) -> bool:
        return now.astimezone(TAIPEI).date() > date.fromisoformat(self.expires)


# A check that fails because of a known product defect: reported, but it does not
# fail the run.  Only a failure whose message contains ``match`` is the known one;
# any other failure of the check fails as usual (#251: T6 failed on U+00A0 while
# listed for #233).  When it passes the run fails, so the entry goes with the fix;
# after ``expires`` the entry no longer counts, so it cannot stay unfixed (#311).
# Registering: .claude/skills/verify-stock-lab/features/README.md (已知失敗).
KNOWN_FAILURES: dict[tuple[str, str], Known] = {}
KNOWN_ISSUE = re.compile(r"https://github\.com/YiCheng0608/stock-lab/issues/[0-9]+")
KNOWN_DAYS = 30  # the longest an entry counts after the day it was added
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def known_problems(
    entries: dict[tuple[str, str], Any], added: Callable[[tuple[str, str]], date]
) -> list[str]:
    """Each entry names a CI check, an Issue URL, a message fragment and an ISO
    ``expires`` at most ``KNOWN_DAYS`` after ``added(key)``, the day it was added."""

    problems = []
    for (page, code), entry in entries.items():
        name = f"KNOWN_FAILURES {page} {code}"
        if code not in CHECKS.get(page, {}):
            problems.append(f"{name}：不是 CHECKS 裡的檢查")
        if not KNOWN_ISSUE.fullmatch(str(getattr(entry, "issue", ""))):
            problems.append(f"{name}：issue 要是 stock-lab 的 Issue 連結")
        if not getattr(entry, "match", ""):
            problems.append(f"{name}：缺 match")
        expires = getattr(entry, "expires", None)
        try:
            if not ISO_DATE.fullmatch(expires):
                raise ValueError(expires)
            last = date.fromisoformat(expires)
        except (TypeError, ValueError):
            problems.append(f"{name}：缺 expires 或不是 YYYY-MM-DD（{expires!r}）")
            continue
        start = added((page, code))
        if not start <= last <= start + timedelta(days=KNOWN_DAYS):
            problems.append(
                f"{name}：expires {last} 要在加入日 {start} 起 {KNOWN_DAYS} 天內"
            )
    return problems


API_ATTEMPTS = 3
API_TIMEOUT_S = 30
SHOT_ATTEMPTS = 2
SHOT_TIMEOUT_S = 240
# Screenshots taken at once when --jobs is not given (#609): the fixture database answers
# fast, but four browsers on a real-data copy can exhaust the API's connection pool when
# another long container shares the host (#606: 35 pool timeouts, G1/S1/A1 failed).
FIXTURE_JOBS = 4
REAL_JOBS = 1


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
    labels: dict[str, dict[str, str]],
    checks: dict[str, dict[str, Any]],
    manual: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Every CI check needs an implementation and every 人工 check a sampler (``MANUAL``), and back."""

    manual = MANUAL if manual is None else manual
    problems = []
    for page in PAGES:
        page_labels = labels.get(page, {})
        for code, kind in page_labels.items():
            if kind not in ("CI", "人工"):
                problems.append(f"{page}.md {code}: 類型 is {kind!r}, not CI or 人工")
            elif kind == "CI" and code not in checks.get(page, {}):
                problems.append(f"{page}.md {code}: labeled CI but not implemented")
            elif kind == "人工" and code not in manual.get(page, {}):
                problems.append(f"{page}.md {code}: labeled 人工 but has no sampler")
        for code in checks.get(page, {}):
            if page_labels.get(code) != "CI":
                problems.append(
                    f"{page} {code}: implemented but {page}.md does not label it CI"
                )
        for code in manual.get(page, {}):
            if page_labels.get(code) != "人工":
                problems.append(
                    f"{page} {code}: sampled but {page}.md does not label it 人工"
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
AI_ENTRY, AI_ENTRY_NONE = "AI 推論 ▸", "AI 說明 ▸"  # candidateAiEntry (#276)


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


PASS, FAIL, UNDETERMINED = "通過", "失敗", "無法判定"


class CheckError(Exception):
    """A check that did not pass; the message is the evidence."""


class Fail(CheckError):
    """A failed check: expected vs actual."""


class Undetermined(CheckError):
    """A check that could not run: an API was not 200 or a screenshot was not ready."""

    def __str__(self) -> str:
        return f"無法判定：{super().__str__()}"


class Environment(Undetermined):
    """A check that could not run because the API answered 5xx or timed out (#609).

    For a screenshot: the shot still had an ``/api/`` 5xx after one serial retake and
    a direct GET of each such URL then answered 200, so the page was not at fault.
    """

    def __str__(self) -> str:
        return f"無法判定（環境）：{self.args[0]}"


class Upstream(Undetermined):
    """A check that could not run because its upstream check did not pass or has no value."""

    def __init__(self, upstream: str, reason: str) -> None:
        super().__init__(reason)
        self.upstream = upstream

    def __str__(self) -> str:
        return f"無法判定（上游 {self.upstream}）：{self.args[0]}"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Fail(message)


@dataclass
class Result:
    page: str
    code: str
    state: str  # PASS, FAIL or UNDETERMINED
    detail: str
    subject: str = ""
    known: str | None = None  # the Issue of the matching KNOWN_FAILURES entry
    upstream: str | None = None  # the upstream check an undetermined result waits on
    environment: bool = False  # undetermined: the API answered 5xx or timed out (#609)

    @property
    def status(self) -> str:
        if self.known:
            return "失敗（已知）" if self.state == FAIL else "失敗（已知失敗卻通過）"
        return self.state

    @property
    def failed(self) -> bool:
        # A known failure that passes fails the run, so KNOWN_FAILURES stays current.
        return self.state == PASS if self.known else self.state == FAIL

    @property
    def undetermined(self) -> bool:
        return self.state == UNDETERMINED

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


# A failed /api/ response a screenshot saw, as screenshot.cjs reports it:
# "504 http://web:8080/api/dashboard" -> status 504, path "dashboard".
API_5XX = re.compile(r"^(5\d\d) \S*?/api/(\S+)$")


def api_5xx(meta: dict) -> list[tuple[int, str]]:
    """The ``/api/`` 5xx responses of one screenshot width, as (status, path)."""

    hits = []
    for entry in meta.get("httpErrors") or []:
        match = API_5XX.match(entry)
        if match:
            hits.append((int(match[1]), match[2]))
    return hits


def http_complete(meta: dict) -> bool:
    """Whether ``httpErrors`` lists every failed response (screenshot.cjs caps the list
    and reports ``httpErrorCount``); a cut list may hide a 404 or a broken URL."""

    shown = len(meta.get("httpErrors") or [])
    return meta.get("httpErrorCount", shown) <= shown


def other_problems(meta: dict) -> list[str]:
    """A width's problems other than /api/ 5xx and not-ready, for the summary of a retake."""

    problems = []
    other = [e for e in meta.get("httpErrors") or [] if not API_5XX.match(e)]
    if other:
        problems.append(f"httpErrors {other}")
    if not http_complete(meta):
        problems.append(f"httpErrors 共 {meta['httpErrorCount']} 筆，清單截斷")
    if meta.get("consoleErrors"):
        problems.append(f"consoleErrors {meta['consoleErrors']}")
    if meta.get("overflow"):
        problems.append("橫向捲動")
    return problems


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
        # (page, code, stock label or "") -> result, as run_page records them
        self.done: dict[tuple[str, str, str], Result] = {}
        self._stock: Stock | CheckError | None = None
        self.picked = ""  # where E/S came from, for the summary
        # #609: the API's 5xx/timeouts seen during the run, the shots retaken for them
        # (name -> no /api/ 5xx left) and the direct GETs of the URLs still 5xx (path -> status).
        self.env_hits: list[dict] = []
        self.retaken: dict[str, bool] = {}
        self.rechecked: dict[str, int] = {}
        # A retaken shot that came back clean: the first take's other problems, for the summary.
        self.replaced: dict[str, list[str]] = {}
        # Off with --fixture: no other container competes there, so a 5xx is a signal
        # and fails as before (#609 review).
        self.env_checks = True
        for sub in ("api", "shots"):
            (out / sub).mkdir(parents=True, exist_ok=True)

    # -- API --

    def get(self, path: str, name: str | None = None) -> Any:
        """GET ``/api/<path>`` once per run (saved to api/<name>); Undetermined when not 200."""

        if path not in self.responses:
            self.responses[path] = self._fetch(path)
            status, payload = self.responses[path]
            if self.env_checks and (status >= 500 or status == 0):
                self.env_hits.append(
                    {
                        "source": "api",
                        "where": "run.get",
                        "status": status,
                        "path": path,
                    }
                )
            target = self.out / "api" / (name or f"{slug(path)}.json")
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
                if status == 200
                else f"HTTP {status}\n{payload}",
                encoding="utf-8",
            )
        status, payload = self.responses[path]
        if self.env_checks and (status >= 500 or status == 0):
            raise Environment(f"/api/{path} 回 {status}")
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

    def shoot(self, shot: Shot, attempts: int = SHOT_ATTEMPTS) -> dict[int, dict]:
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
        for attempt in range(1, attempts + 1):
            stdout, stderr = self._screenshot(command)
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
            if attempt < attempts:
                print(
                    f"screenshot {shot.name}: not ready, retrying ({stderr.strip()[-200:]})",
                    file=sys.stderr,
                )
        self.shots[shot.name] = results
        return results

    def _screenshot(self, command: list[str]) -> tuple[str, str]:
        """One screenshot.cjs run: its stdout (JSON lines) and stderr."""

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=SHOT_TIMEOUT_S,
            )
            return completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or ""
            stdout = stdout.decode() if isinstance(stdout, bytes) else stdout
            return stdout, f"screenshot.cjs timed out after {SHOT_TIMEOUT_S} s"

    def retake(self, shots: list[Shot]) -> None:
        """#609: retake, one at a time and once, each shot that saw an ``/api/`` 5xx;
        then GET each URL still 5xx directly, so ``env_reason`` can tell a busy host
        (the GET answers 200) from a broken API (it does not).  Not with --fixture."""

        if not self.env_checks:
            return
        for shot in shots:
            first = self.shoot(shot)
            if not any(api_5xx(meta) for meta in first.values()):
                continue
            self._record(shot, first, "截圖")
            self.shots.pop(shot.name, None)
            again = self.shoot(shot, attempts=1)
            self._record(shot, again, "重截")
            left = {path for meta in again.values() for _, path in api_5xx(meta)}
            self.retaken[shot.name] = not left
            other = [
                f"{shot.name}-{width} {problem}"
                for width, meta in first.items()
                for problem in other_problems(meta)
            ]
            if not left and other:
                self.replaced[shot.name] = other
            for path in sorted(left - set(self.rechecked)):
                self.rechecked[path] = self._fetch(path)[0]

    def _record(self, shot: Shot, metas: dict[int, dict], source: str) -> None:
        for width, meta in metas.items():
            for status, path in api_5xx(meta):
                self.env_hits.append(
                    {
                        "source": source,
                        "where": f"{shot.name}-{width}",
                        "status": status,
                        "path": path,
                    }
                )

    def env_reason(self, meta: dict) -> str | None:
        """The /api/ 5xx of a screenshot width when each answered 200 to a direct GET
        (the host was busy, #609); None when there is none, one is still not 200, the
        httpErrors list was cut (``http_complete``) or the run is on the fixture database."""

        hits = api_5xx(meta)
        if not self.env_checks or not http_complete(meta):
            return None
        if not hits or any(self.rechecked.get(path) != 200 for _, path in hits):
            return None
        seen = dict.fromkeys(f"{status} /api/{path}" for status, path in hits)
        return f"截圖時 API {'、'.join(seen)}，直接 GET 回 200"

    def environment(self, jobs: int, results: list[Result]) -> dict:
        """What summary.md opens with and environment.json holds (#609)."""

        counts: dict[tuple[str, int], int] = {}
        for hit in self.env_hits:
            key = (hit["path"], hit["status"])
            counts[key] = counts.get(key, 0) + 1
        return {
            "jobs": jobs,
            "hits": len(self.env_hits),
            "screenshot_hits": sum(h["source"] != "api" for h in self.env_hits),
            "api_hits": sum(h["source"] == "api" for h in self.env_hits),
            "retaken": sorted(self.retaken),
            "recovered": sorted(name for name, ok in self.retaken.items() if ok),
            "replaced_problems": dict(sorted(self.replaced.items())),
            "rechecked": dict(sorted(self.rechecked.items())),
            "urls": [
                {"path": path, "status": status, "count": count}
                for (path, status), count in sorted(
                    counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "checks": [f"{r.page} {r.label}" for r in results if r.environment],
            "events": self.env_hits,
        }

    def text(self, shot: Shot, width: int = 1280) -> Text:
        meta = self.shoot(shot)[width]
        if not meta.get("ready"):
            reason = self.env_reason(meta)
            if reason:
                raise Environment(f"{shot.name}-{width} 未 ready，{reason}")
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
        return self.get("themes?board=industry&limit=5", "today-board.json")

    def needs(self, value: str, found: Any, missing: str, subject: str = "") -> Any:
        """``found`` for a check that uses ``value``; Upstream when the owner did not pass or it is missing."""

        page, code = OWNERS[value]
        owner = self.done.get((page, code, subject))
        if owner is not None and owner.state != PASS:
            raise Upstream(owner.upstream or code, f"{code} {owner.status}")
        if not found:
            raise Upstream(code, missing)
        return found

    # The owners (T2, T4, T5) read the raw values and judge a missing one themselves.
    def raw_D(self) -> str | None:
        as_of = self.dashboard().get("as_of")
        return as_of[:10] if as_of else None

    def D(self) -> str:
        return self.needs("D", self.raw_D(), "dashboard.json 沒有 as_of（D）")

    def raw_B(self) -> str | None:
        return (self.today_board().get("meta") or {}).get("trading_date")

    def B(self) -> str:
        return self.needs(
            "B", self.raw_B(), "today-board.json 沒有 meta.trading_date（B）"
        )

    def T(self) -> tuple[str, str]:
        items = self.today_board().get("items") or []
        self.needs("T", items, "today-board.json 的 items 為空（T）")
        return items[0]["theme_id"], items[0]["display_name"]

    def theme_members(self) -> dict:
        theme_id, _ = self.T()
        return self.get(
            f"themes/{theme_id}/members?page=1&page_size=30&sort=turnover",
            "theme-members.json",
        )

    def stock(self) -> Stock:
        """E/S, picked once per run from the first source that has one (features/README.md)."""

        if self._stock is None:
            self._stock = self._pick()
        if isinstance(self._stock, CheckError):
            raise self._stock
        return self._stock

    def _pick(self) -> Stock | CheckError:
        skipped = []
        for source, pick in (
            ("今日榜", self._pick_from_board),
            ("今日名單", self._pick_from_candidates),
            ("市場列表", self._pick_from_list),
        ):
            try:
                stock, how = pick()
            except CheckError as error:
                skipped.append(f"{source}：{error.args[0]}")
                continue
            self.picked = how + (f"（略過 {'；'.join(skipped)}）" if skipped else "")
            return stock
        self.picked = "沒有可用的個股：" + "；".join(skipped)
        return Undetermined(self.picked)

    def _pick_from_board(self) -> tuple[Stock, str]:
        _theme_id, name = self.T()
        items = self.theme_members().get("items") or []
        if not items:
            raise Undetermined("theme-members.json 的 items 為空")
        stock = Stock(items[0]["exchange"], items[0]["symbol"])
        return stock, f"今日榜 #1 族群「{name}」的第一個成員"

    def _pick_from_candidates(self) -> tuple[Stock, str]:
        items = self.get("candidates", "candidates.json").get("items") or []
        if not items:
            raise Undetermined("candidates.json 的 items 為空")
        instrument = items[0]["instrument"]
        return Stock(instrument["exchange"], instrument["symbol"]), "今日名單 #1"

    def _pick_from_list(self) -> tuple[Stock, str]:
        items = self.get("stocks?page=1&page_size=30", "stocks.json").get("items") or []
        if not items:
            raise Undetermined("stocks.json 的 items 為空")
        instrument = items[0]["instrument"]
        return Stock(instrument["exchange"], instrument["symbol"]), "市場列表第一筆"


# The check that owns each value passed between checks (features/README.md 跨檔傳遞的值).
# A check using the value is 無法判定（上游 <owner>） when the value is missing or the
# owner did not pass, so one defect is one failure, not one per page (#251).
OWNERS: dict[str, tuple[str, str]] = {
    "D": ("today", "T2"),
    "B": ("today", "T4"),
    "T": ("today", "T5"),
    "I": ("stocks", "S8"),
}


# ---- shots per page ----


def today_shots(run: Run) -> list[Shot]:
    # The market page (/market, Issue 549) was split off the today page and is checked with it (features/today.md).
    return [TODAY, MARKET, MARKET_TPEX, MARKET_TX]


def news_shots(run: Run) -> list[Shot]:
    shots = [
        Shot("news", "/news"),
        Shot("news-international", "/news?tab=international", (1280,)),
        Shot("news-official", "/news?tab=official", (1280,)),
    ]
    try:
        shots.append(Shot("news-detail", f"/news/{news_detail_id(run)}"))
    except CheckError:
        pass  # N6 reports the missing id
    return shots


def themes_shots(run: Run) -> list[Shot]:
    shots = [
        Shot("themes", "/themes"),
        Shot("themes-theme", "/themes?board=theme", (1280,)),
    ]
    try:
        shots.append(Shot("theme-detail", f"/themes/{run.T()[0]}"))
    except CheckError:
        pass
    return shots


def stock_shots(stock: Stock) -> dict[str, Shot]:
    url = f"/stocks/{stock.exchange}/{stock.symbol}"
    tabs = {
        tab: Shot(f"{stock.prefix}-{tab}", url, (1280,), (f"#stock-tab-{tab}",))
        for tab in ("chips", "financials", "research", "news", "data")
    }
    return {"main": Shot(stock.prefix, url), **tabs}


def stocks_shots(run: Run, stocks: list[Stock]) -> list[Shot]:
    shots = [Shot("stocks", "/stocks")]
    for stock in stocks:
        shots += stock_shots(stock).values()
    return shots


def action_detail_shot(stock: Stock) -> Shot:
    """No click: /actions/E/S must land on the stock page's research tab (#278)."""

    return Shot("action-detail", f"/actions/{stock.exchange}/{stock.symbol}", (1280,))


def actions_shots(run: Run) -> list[Shot]:
    shots = [ACTIONS, ACTIONS_LEGACY]
    try:
        shots.append(action_detail_shot(run.stock()))
    except CheckError:
        pass
    return shots


def usable(run: Run, shots: list[Shot]) -> str:
    """T1/N1/G1/S1/A1: every width ready, no failed /api/, console error or overflow.

    #609: a width whose only problems are /api/ 5xx that answered 200 to a direct GET
    (``Run.env_reason``) and the not-ready / missing clicks they caused is
    無法判定（環境）; any other problem on any width still fails the check.
    """

    problems: list[tuple[str, bool]] = []  # (problem, explained by the environment)
    count = 0
    for shot in shots:
        for width, meta in run.shoot(shot).items():
            count += 1
            where = f"{shot.name}-{width}"
            env = run.env_reason(meta) is not None
            if not meta.get("ready"):
                problem = f"{where} 未 ready {meta.get('error', '')}".strip()
                problems.append((problem, env))
            if meta.get("missingClicks"):
                problems.append((f"{where} missingClicks {meta['missingClicks']}", env))
            http = meta.get("httpErrors") or []
            busy = [entry for entry in http if env and API_5XX.match(entry)]
            other = [entry for entry in http if entry not in busy]
            if busy:
                problems.append((f"{where} httpErrors {busy}", True))
            if other:
                problems.append((f"{where} httpErrors {other}", False))
            if not http_complete(meta):
                problem = f"{where} httpErrors 共 {meta['httpErrorCount']} 筆，清單只列 {len(http)} 筆（截斷，不認定環境）"
                problems.append((problem, False))
            if meta.get("consoleErrors"):
                problem = f"{where} consoleErrors {meta['consoleErrors']}"
                problems.append((problem, False))
            if meta.get("overflow"):
                problem = f"{where} 橫向捲動 scrollWidth {meta['scrollWidth']} > clientWidth {meta['clientWidth']}"
                problems.append((problem, False))
    message = "；".join(problem for problem, _ in problems)
    expect(all(env for _, env in problems), message)
    if problems:
        raise Environment(f"{message}（這些 /api/ 直接 GET 回 200）")
    return f"{count} 張截圖 ready，無錯誤，無橫向捲動"


# ---- registry ----

CheckFn = Callable[..., str]
CHECKS: dict[str, dict[str, CheckFn]] = {page: {} for page in PAGES}
PER_STOCK: set[str] = set()  # stocks checks that run once per Stock
NEEDS_STOCK: set[str] = set()  # of those, the ones that cannot run without E/S
# (page, code) -> same-page checks that must pass first; a failure is then 無法判定（上游 X）
AFTER: dict[tuple[str, str], tuple[str, ...]] = {}


def check(
    page: str,
    code: str,
    per_stock: bool = False,
    needs_stock: bool | None = None,
    after: tuple[str, ...] = (),
):
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[page][code] = fn
        if per_stock:
            PER_STOCK.add(code)
        if per_stock if needs_stock is None else needs_stock:
            NEEDS_STOCK.add(code)
        if after:
            AFTER[(page, code)] = after
        return fn

    return register


# ---- today ----

TODAY = Shot("today", "/")
MARKET = Shot("market", "/market")
# The shared chart of another row, selected through the URL (Issue 564): 1280 only, like the news tabs.
MARKET_TPEX = Shot("market-tpex", "/market?index=tpex", (1280,))
MARKET_TX = Shot("market-tx", "/market?index=tx", (1280,))
PENDING_DATE = "資料日期未提供"  # DateBadge without a date (#465: was 資料日期待核實)
TODAY_GROUPS = 5  # TODAY_BOARD_LIMIT in frontend/src/themes/themeBoards.ts (#276)
GROUP_RETURNS_NOTE = "1／5／20 日為相對加權指數的報酬"  # HOT_GROUP_RETURNS_NOTE (#510)


@check("today", "T1")
def t1(run: Run) -> str:
    return usable(run, today_shots(run))


@check("today", "T2")
def t2(run: Run) -> str:
    text, d = run.text(TODAY), run.raw_D()
    latest = run.facts()["market_latest_trading_date"]
    if not d:
        # #251: the DB has bars, so a page without a data date is a defect, not 無法判定.
        expect(
            latest is None,
            f"dashboard.as_of 為 null，但 DB market_bars 最新 {latest}",
        )
        expect(text.has(PENDING_DATE), f"as_of 為 null，缺整行 `{PENDING_DATE}`")
        return f"DB 與 dashboard 都沒有資料日，顯示 `{PENDING_DATE}`"
    # #270: every date badge reads YYYY/MM/DD, the navbar included.
    expect(text.has(f"資料 {slash(d)}"), f"缺整行 `資料 {slash(d)}`（{text.name}）")
    expect(d == latest, f"D {d} ≠ facts market_latest_trading_date {latest}")
    return f"`資料 {slash(d)}` = facts {latest}"


@check("today", "T3")
def t3(run: Run) -> str:
    """#276: one header line 「資料截至 <D/> · <source_label> · <mode>」 instead of the hero card."""

    text, d = run.text(TODAY), run.D()
    prefix = f"資料截至 {slash(d)} · "
    i = text.find_where(lambda line: line.startswith("資料截至 "))
    expect(i >= 0, f"缺 `資料截至 ` 開頭的頁首資料列（{text.name}）")
    line = text.lines[i]
    expect(
        line.startswith(prefix),
        f"頁首資料列是 {line!r}，預期以 `{prefix}` 開頭（{text.at(i)}）",
    )
    parts = line[len(prefix) :].split(" · ")
    label = (run.dashboard().get("market") or {}).get("source_label")
    expect(len(parts) >= 2 and all(parts), f"頁首資料列缺來源或模式：{line!r}")
    if label is not None:
        expect(parts[0] == label, f"來源 {parts[0]!r} ≠ market.source_label {label!r}")
    return f"`{line}`"


def first_data_line_after(text: Text, title: str) -> tuple[int, str | None]:
    i = text.find(title)
    expect(i >= 0, f"缺整行 `{title}`（{text.name}）")
    j = text.find_where(lambda line: line.startswith("資料 "), i + 1)
    return j, text.lines[j] if j >= 0 else None


@check("today", "T4")
def t4(run: Run) -> str:
    text, b = run.text(TODAY), run.raw_B()
    latest = run.facts()["group_scores_latest_trading_date"]
    if not b:
        expect(
            latest is None,
            f"today-board.json meta.trading_date 為 null，但 DB group_daily_scores 最新 {latest}",
        )
        expect(text.has(PENDING_DATE), f"B 為 null，缺整行 `{PENDING_DATE}`")
        return f"DB 與族群榜都沒有資料日，顯示 `{PENDING_DATE}`"
    j, line = first_data_line_after(text, "熱門族群")
    expect(
        line == f"資料 {slash(b)}",
        f"`熱門族群` 後第一個資料行是 {line!r}，預期 `資料 {slash(b)}`（{text.at(j)}）",
    )
    expect(b == latest, f"B {b} ≠ facts group_scores_latest_trading_date {latest}")
    return f"`{line}`；B = facts {latest}"


def board_empty_message(board: dict) -> str:
    return (board.get("meta") or {}).get("empty_message") or "此榜目前沒有族群"


def empty_board(run: Run, board: dict, text: Text, name: str) -> str:
    """An empty board passes only on its empty message and when no other source has scores (#251)."""

    day = (board.get("meta") or {}).get("trading_date")
    latest = run.facts()["group_scores_latest_trading_date"]
    elsewhere = []
    if latest and day in (None, latest):
        elsewhere.append(f"DB group_daily_scores {latest} 有名次")
    # The home page does not read groups; the dashboard ships them on request (#601).
    groups = run.get("dashboard?include=groups", "dashboard-groups.json")
    ranked = [
        group
        for group in groups.get("groups") or []
        if group.get("rank") is not None
        and group.get("trading_date") in {day or latest} - {None}
    ]
    if ranked:
        elsewhere.append(
            f"dashboard.groups 有 {len(ranked)} 個 {ranked[0]['trading_date']} 有名次的族群"
        )
    message = board_empty_message(board)
    expect(
        not elsewhere,
        f"{name} items 空（顯示 `{message}`），但 " + "、".join(elsewhere),
    )
    expect(text.has(message), f"{name} items 空，缺空資料文案 `{message}`")
    return f"items 空，DB 與 dashboard 也沒有名次，顯示 `{message}`"


@check("today", "T5")
def t5(run: Run) -> str:
    text, board = run.text(TODAY), run.today_board()
    items = board.get("items") or []
    if not items:
        run.needs(
            "B", True, ""
        )  # T4 failing on the same missing scores is the one failure
        return empty_board(run, board, text, "today-board.json")
    run.B()  # T4 checks the date line; a missing date is counted there
    # #510: the card says once what the returns are relative to; each row starts with its
    # own `#n` line, then the name line (HotGroupRow in frontend/src/themes/ThemeViews.tsx).
    expect(text.has(GROUP_RETURNS_NOTE), f"缺整行 `{GROUP_RETURNS_NOTE}`")
    # Hot groups is the last card of the page (Issue 625); the footer ends it.
    start = text.find("熱門族群")
    end = text.find(FOOTER_FIRST_LINE, start)
    end = end if end > start else len(text.lines)
    rows = [i for i in range(start + 1, end) if re.fullmatch(r"#[0-9]+", text.lines[i])]
    want = [item["display_name"] for item in items[:TODAY_GROUPS]]
    shown = [text.after(i) for i in rows]
    expect(shown == want, f"`熱門族群` 列 {shown}，預期 items 前 {len(want)} 名 {want}")
    return f"{len(rows)} 列（`#n` 與名稱）= items 前 {len(want)} 名；`{GROUP_RETURNS_NOTE}`"


def usable_ai(ai: Any) -> bool:
    """The frontend's usableAi (features/news.md 陷阱)."""

    return (
        isinstance(ai, dict)
        and ai.get("status") == "done"
        and ai.get("inference") is True
    )


# The first line of the Shell footer: the end of the last card of a page.
FOOTER_FIRST_LINE = "T 日收盤訊號 · 最早 T+1 執行 · T+5／T+20 追蹤"


def candidates(run: Run) -> dict:
    return run.get("candidates", "candidates.json")


def source_lines(text: Text) -> list[int]:
    return [i for i, line in enumerate(text.lines) if line.startswith("來源：")]


# An action-list row (我的追蹤, tier 1) starts with its rank cell and a tab (#276): `#1<TAB>…`.
# Cards put `#1` on a line of its own, so the tab tells a table row from a card.
RANK_ROW = re.compile(r"^#([0-9]+)\t")
# A 今日名單 row starts with its title line (#493, #510): `#1 2330 台積電 上市 · 族群` (rank,
# symbol, name on one line). The hot group rows put `#1` on a line of its own, so the symbol
# after the rank tells a candidate row.
CANDIDATE_ROW = re.compile(r"^#([0-9]+) [0-9A-Z]+ ")
# CandidatesSection in frontend/src/candidates/CandidateViews.tsx (#510: no eyebrow); the
# navbar has a 今日名單 link too and comes first, so the title is the last line that reads it.
CANDIDATES_TITLE = "今日名單"


def candidates_title(text: Text) -> int:
    """The 今日名單 section title, not the navbar link; -1 when it is missing."""

    found = [n for n, line in enumerate(text.lines) if line == CANDIDATES_TITLE]
    return found[-1] if found else -1


def candidate_ranks(text: Text) -> list[int]:
    """Rank cells between 今日名單 and 熱門族群 (the group rows have their own `#n`)."""

    start, end = candidates_title(text), text.find("熱門族群")
    end = end if end > start else len(text.lines)
    return [
        int(match.group(1))
        for line in text.lines[start + 1 : end]
        if (match := CANDIDATE_ROW.match(line))
    ]


@check("today", "T7")
def t7(run: Run) -> str:
    text, payload = run.text(TODAY), candidates(run)
    items = payload.get("items") or []
    if payload.get("status") == "not_computed" or not items:
        # #251: an empty list passes only when the DB has no candidates for that day either.
        facts = run.facts()
        latest, count = (
            facts["candidate_run_latest_trading_date"],
            facts["candidate_count_latest"],
        )
        day = payload.get("trading_date")
        expect(
            not (count and day in (None, latest)),
            f"candidates.json {payload.get('status')}、items {len(items)}，"
            f"但 DB candidate_runs {latest} 有 {count} 檔",
        )
    if payload.get("status") == "not_computed":
        expect(text.has("尚無候選清單"), "status not_computed，缺 `尚無候選清單`")
        return "not_computed，DB 也沒有當日候選，顯示 `尚無候選清單`"
    if not items:
        expect(text.has("當日零候選"), "items 空，缺 `當日零候選`")
        return "items 空，DB 也是 0 檔，顯示 `當日零候選`"
    c = payload["trading_date"]
    i = candidates_title(text)
    expect(i >= 0, f"缺整行 `{CANDIDATES_TITLE}`")
    expect(
        text.after(i) == f"資料 {slash(c)}",
        f"`{CANDIDATES_TITLE}` 下一行是 {text.after(i)!r}，預期 `資料 {slash(c)}`（{text.at(i)}）",
    )
    count_line = f"{payload['candidate_count']} 檔"
    expect(
        text.after(i, 2) == count_line,
        f"再下一行是 {text.after(i, 2)!r}，預期 `{count_line}`",
    )
    ranks = candidate_ranks(text)
    want = [item["rank"] for item in items]
    expect(ranks == want, f"`#n` 名次列 {ranks}，預期依 items {want}")
    sources = len(source_lines(text))
    expect(sources == len(items), f"`來源：` 行 {sources}，items {len(items)}")
    latest = run.facts()["candidate_run_latest_trading_date"]
    expect(c == latest, f"C {c} ≠ facts candidate_run_latest_trading_date {latest}")
    return f"`資料 {slash(c)}`、`{count_line}`；名次列 {len(ranks)}、來源行 {sources} = items；C = facts"


def news_inference(item: dict) -> bool:
    components = item.get("components") or {}
    return bool((components.get("news_sentiment") or {}).get("inference"))


# T8 counts the same 來源 rows as T7, so a T7 failure is not counted twice.
@check("today", "T8", after=("T7",))
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
    # #276: each row's AI entry says whether a note exists (done or pending) or not.
    with_note = sum(bool(item.get("llm_note")) for item in items)
    entries = sum(line.count(AI_ENTRY) for line in text.lines)
    plain = sum(line.count(AI_ENTRY_NONE) for line in text.lines)
    expect(
        (entries, plain) == (with_note, len(items) - with_note),
        f"`{AI_ENTRY}` {entries} 個、`{AI_ENTRY_NONE}` {plain} 個，"
        f"預期 {with_note}／{len(items) - with_note}（llm_note 存在的檔數）",
    )
    inferred = sum(news_inference(item) for item in items)
    return (
        f"{inferred} 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` {notes} 行；"
        f"免責句 {disclaimers} 行；入口 `{AI_ENTRY}` {entries}、`{AI_ENTRY_NONE}` {plain}"
    )


@check("today", "T9")
def t9(run: Run) -> str:
    """#493: 今日名單 keeps one list; 關注標的 moved to 我的追蹤 and every home link to it is /watch."""

    text = run.text(TODAY)
    for line in ("關注標的", "查看個股詳情 →", "查看行動中心 →", "明日候選"):
        expect(not text.has(line), f"首頁仍有整行 `{line}`")
    alert = text.has("查看我的追蹤 →")
    return "首頁沒有 `關注標的`、`明日候選`；" + (
        "持倉風險提示列連到 `查看我的追蹤 →`" if alert else "沒有持倉風險提示列"
    )


# ---- T11 market overview, on the market page since Issue 549 (#276, UI_COPY_SPEC §11) ----

OVERVIEW_EXCHANGES = (("TWSE", "上市"), ("TPEx", "上櫃"))
OVERVIEW_TITLE = "大盤概況"  # MarketOverviewPanel's h2
# SHORT_SCOPE_LABELS in frontend/src/market/marketOverview.ts; other scopes show scope_label.
SHORT_SCOPES = {"twse_all_securities": "集中市場總計", "tpex_stocks": "上櫃股票"}


def fixed(value: float, digits: int, signed: bool = False) -> str:
    """formatFixed in frontend/src/units.ts: thousands separators, `-` or (signed) `+`.

    It rounds like JS ``toFixed``: the float's exact binary value, a tie away from
    zero (``Decimal(float)`` is exact; ROUND_HALF_UP rounds a tie away from zero).
    Python ``round()`` keeps a tie even and would make T11 fail on a correct page.
    """

    rounded = Decimal(value).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
    text = f"{abs(rounded):,.{digits}f}"
    if rounded < 0:
        return "-" + text
    return "+" + text if signed and rounded > 0 else text


def dash(value: Any) -> str:
    return "—" if value is None else fixed(value, 0)


def overview_lines(exchange: dict, label: str) -> list[str]:
    """The lines the four widgets show for one available exchange (market/MarketViews.tsx)."""

    index, turnover = exchange.get("index") or {}, exchange.get("turnover") or {}
    breadth = exchange.get("breadth") or {}
    lines = []
    if index.get("close") is not None:
        lines.append(fixed(index["close"], 2))
    if index.get("change") is not None and index.get("change_pct") is not None:
        lines.append(
            f"{fixed(index['change'], 2, True)}（{fixed(index['change_pct'] * 100, 2, True)}%）"
        )
    if turnover.get("value") is not None:
        # The short scope stays next to the amount (#276 review L6, UI_COPY_SPEC §11).
        short = SHORT_SCOPES.get(turnover.get("scope")) or turnover.get("scope_label")
        amount = f"{label} {fixed(turnover['value'] / 1e8, 2)}"
        lines.append(f"{amount} {short}" if short else amount)
    limits = (
        ""
        if breadth.get("limit_up") is None and breadth.get("limit_down") is None
        else f"（{dash(breadth.get('limit_up'))}／{dash(breadth.get('limit_down'))}）"
    )
    lines.append(
        f"{label} 上漲 {dash(breadth.get('advancers'))} · 下跌 {dash(breadth.get('decliners'))}"
        f" · 平盤 {dash(breadth.get('unchanged'))}{limits}"
    )
    return lines


SUMMARY_FIELDS = {
    "index_close": ("index", "close"),
    "index_change": ("index", "change"),
    "turnover": ("turnover", "value"),
    "advancers": ("breadth", "advancers"),
    "decliners": ("breadth", "decliners"),
}


@check("today", "T11")
def t11(run: Run) -> str:
    """Market page overview = dashboard.market_overview and the DB rows; its date badge; scope labels in 資料說明."""

    text, overview = run.text(MARKET), run.dashboard().get("market_overview") or {}
    rows = {item.get("exchange"): item for item in overview.get("exchanges") or []}
    latest = run.facts().get("market_summary_latest") or {}
    day = overview.get("trading_date")
    problems, shown, scopes = [], [], []
    # Issue 549: the block has its own title and date badge (DESIGN_SYSTEM §4 大盤頁).
    i = text.find(OVERVIEW_TITLE)
    want = f"資料 {slash(day)}" if day else PENDING_DATE
    if i < 0:
        problems.append(f"缺整行 `{OVERVIEW_TITLE}`")
    elif text.after(i) != want:
        problems.append(
            f"`{OVERVIEW_TITLE}` 下一行是 {text.after(i)!r}，預期日期 badge `{want}`"
        )
    for code, label in OVERVIEW_EXCHANGES:
        exchange, stored = rows.get(code) or {}, latest.get(code)
        if exchange.get("status") != "available":
            # #251: an unavailable exchange passes only when the DB has no row of that day either.
            if stored and day and stored.get("trading_date") == day:
                problems.append(
                    f"{code} 為 unavailable，但 DB market_summaries 有 {day} 的列"
                )
            missing = f"{label}大盤資料未取得"
            if not text.has(missing):
                problems.append(f"{code} unavailable，缺整行 `{missing}`")
            shown.append(f"{code} 未取得")
            continue
        if not stored or stored.get("trading_date") != day:
            problems.append(
                f"{code} available {day}，但 DB 最新列 {stored and stored.get('trading_date')}"
            )
        else:
            for field, (group, key) in SUMMARY_FIELDS.items():
                if stored.get(field) != (exchange.get(group) or {}).get(key):
                    problems.append(
                        f"{code} {group}.{key} {(exchange.get(group) or {}).get(key)!r} ≠ DB {field} {stored.get(field)!r}"
                    )
        for line in overview_lines(exchange, label):
            if not text.has(line):
                problems.append(f"{code} 缺整行 `{line}`")
        scope = (exchange.get("turnover") or {}).get("scope_label")
        if scope:
            scopes.append(f"{label}為{scope}")
        shown.append(
            f"{code} {fixed((exchange.get('index') or {}).get('close') or 0, 2)}"
        )
    if scopes:
        line = "成交金額範圍：" + "；".join(scopes)
        if not text.has(line):
            problems.append(f"資料說明缺整行 `{line}`")
    expect(not problems, "；".join(problems))
    return (
        f"{day}："
        + "、".join(shown)
        + (f"；範圍 `{'；'.join(scopes)}`" if scopes else "")
    )


@check("today", "T12")
def t12(run: Run) -> str:
    """#276: candidates come before the groups; the news card is gone (Issue 625)."""

    text = run.text(TODAY)
    found = {
        CANDIDATES_TITLE: candidates_title(text),
        "熱門族群": text.find("熱門族群"),
    }
    missing = [title for title, i in found.items() if i < 0]
    expect(not missing, "缺整行 " + "、".join(f"`{title}`" for title in missing))
    expect(
        found[CANDIDATES_TITLE] < found["熱門族群"],
        f"區塊順序 `熱門族群` → `{CANDIDATES_TITLE}`，預期 `{CANDIDATES_TITLE}` 在前",
    )
    expect(not text.has("重點新聞"), "首頁仍有整行 `重點新聞`（#625 已移除）")
    return "`今日名單`（{0}）→ `熱門族群`（{1}）；沒有 `重點新聞`".format(
        *(text.at(i) for i in found.values())
    )


ADD_PLAN, TRACKED_PLAN = "加入追蹤", "已在追蹤"  # frontend/src/tracking/tracking.ts


# One button or link per card, counted on the same cards as T7 (#253).
@check("today", "T13", after=("T7",))
def t13(run: Run) -> str:
    text, payload = run.text(TODAY), candidates(run)
    items = payload.get("items") or []
    add = text.count(lambda line: line == ADD_PLAN)
    tracked = text.count(lambda line: line == TRACKED_PLAN)
    if payload.get("status") == "not_computed" or not items:
        expect(
            add + tracked == 0,
            f"沒有候選，卻有 `{ADD_PLAN}` {add} 行、`{TRACKED_PLAN}` {tracked} 行",
        )
        return "沒有候選，也沒有加入追蹤按鈕"
    expect(
        add + tracked == len(items),
        f"`{ADD_PLAN}` {add} 行＋`{TRACKED_PLAN}` {tracked} 行，items {len(items)}",
    )
    want = sum(item.get("open_plan_id") is not None for item in items)
    expect(
        tracked == want,
        f"`{TRACKED_PLAN}` {tracked} 行，open_plan_id 非 null {want} 筆",
    )
    return f"{len(items)} 張卡：`{ADD_PLAN}` {add}、`{TRACKED_PLAN}` {tracked} = open_plan_id 非 null"


# Issue 608: at 390 the row's close, RR and total sat in a column narrower than they were, ran under the AI
# button and past the list's overflow: hidden, with no page scroll for T1 to see. screenshot.cjs measures each
# shown row (candidateRows, after every <details> is open, so the rest of the list too).
@check("today", "T17")
def t17(run: Run) -> str:
    meta = run.shoot(TODAY)[390]
    if not meta.get("ready"):
        raise Undetermined(f"{TODAY.name}-390 未 ready {meta.get('error', '')}".strip())
    payload = candidates(run)
    items = (
        [] if payload.get("status") == "not_computed" else payload.get("items") or []
    )
    rows = meta.get("candidateRows")
    expect(rows is not None, f"{TODAY.name}-390 沒有 candidateRows 量測")
    ranks = [row["rank"] for row in rows]
    want = [item["rank"] for item in items]
    expect(ranks == want, f"量到的候選列 {ranks}，預期依 items {want}")
    problems = []
    for row in rows:
        where = f"#{row['rank']}"
        if row["numsScrollWidth"] is None:
            problems.append(f"{where} 沒有 .candidate-row-nums")
        elif row["numsScrollWidth"] > row["numsClientWidth"]:
            problems.append(
                f"{where} 數字區 scrollWidth {row['numsScrollWidth']} > clientWidth {row['numsClientWidth']}"
            )
        if row["covered"]:
            problems.append(f"{where} 被 AI 按鈕蓋住：{'、'.join(row['covered'])}")
        if row["clipped"]:
            problems.append(f"{where} 超出列邊被切：{'、'.join(row['clipped'])}")
    expect(not problems, "；".join(problems))
    if not rows:
        return "沒有候選列"
    return f"390：{len(rows)} 列數字區不溢出、不被 AI 按鈕蓋住、沒有超出列邊"


# ---- T14 / T15: the today summary line and the market page's daily chart (Issue 549, UI_COPY_SPEC §11) ----

SUMMARY_NAMES = (
    ("TWSE", "加權"),
    ("TPEx", "櫃買"),
)  # EXCHANGES[].short in market/marketOverview.ts
MARKET_LINK = "看大盤 →"
# MarketPage draws one chart, the selected row's, with the stock page's StockBarsChart and STOCK_BARS_LIMIT (Issue
# 549, decision 6715021190; Issue 552/564): 加權指數 by default (MARKET), the others through ?index= (screenshots of
# their own). (shot, title, bars path, saved name, price decimals).
MARKET_CHARTS = (
    (
        MARKET,
        "加權指數日線",
        "stocks/TWSE/TAIEX/bars?interval=day&limit=250",
        "taiex-bars.json",
        2,
    ),
    (
        MARKET_TPEX,
        "櫃買指數日線",
        "stocks/TPEx/TPEX/bars?interval=day&limit=250",
        "tpex-bars.json",
        2,
    ),
    (
        MARKET_TX,
        "台指期近月日線",
        "stocks/TAIFEX/TX/bars?interval=day&limit=250",
        "tx-bars.json",
        0,
    ),
)
# chartTitle of every INDEX_SPECS row in market/marketOverview.ts: a screenshot shows exactly one of them.
CHART_TITLES = (
    "加權指數日線",
    "櫃買指數日線",
    "台指期近月日線",
    "S&P 500日線",
    "NASDAQ 綜合指數日線",
    "道瓊工業指數日線",
    "費城半導體指數日線",
)
NO_BARS = "來源未提供日線"
# TAIFEX_ATTRIBUTION in market/marketOverview.ts (政府資料開放授權條款第1版 第三條).
TAIFEX_ATTRIBUTION = (
    "資料來源：臺灣期貨交易所（政府資料開放平臺，政府資料開放授權條款第1版）"
)


def drawable(bar: dict) -> bool:
    """isDrawableBar in frontend/src/stock/stockBars.ts: a traded day with positive, self-consistent OHLC."""

    values = [bar.get(key) for key in ("open", "high", "low", "close")]
    if bar.get("is_suspended") or not all(
        isinstance(v, (int, float)) and v > 0 for v in values
    ):
        return False
    open_, high, low, close = values
    return high >= max(open_, close) and low <= min(open_, close)


def summary_line(exchange: dict, name: str) -> str:
    """The summary item for one exchange (summaryItems in market/marketOverview.ts)."""

    index = exchange.get("index") or {}
    if exchange.get("status") != "available" or index.get("close") is None:
        return f"{name} 未取得"
    pct = index.get("change_pct")
    shown = "—" if pct is None else f"{fixed(pct * 100, 2, True)}%"
    return f"{name} {fixed(index['close'], 2)} {shown}"


@check("today", "T14")
def t14(run: Run) -> str:
    """The today page keeps one market line (加權, 櫃買, the date, 看大盤 →), not the four widgets."""

    text, overview = run.text(TODAY), run.dashboard().get("market_overview") or {}
    rows = {item.get("exchange"): item for item in overview.get("exchanges") or []}
    day = overview.get("trading_date")
    lines = [summary_line(rows.get(code) or {}, name) for code, name in SUMMARY_NAMES]
    lines += [f"資料 {slash(day)}" if day else PENDING_DATE, MARKET_LINK]
    # One line of the page per part, in order (the navbar has its own 資料 badge, so search from the first item).
    start = text.find(lines[0])
    expect(start >= 0, f"缺整行 `{lines[0]}`（{text.name}）")
    got = [text.after(start, k) for k in range(len(lines))]
    expect(
        got == lines,
        "摘要列是 "
        + "、".join(f"`{line}`" for line in got if line is not None)
        + "，預期 "
        + "、".join(f"`{line}`" for line in lines),
    )
    candidates_at = candidates_title(text)
    expect(
        candidates_at < 0 or start < candidates_at,
        f"摘要列在 `{CANDIDATES_TITLE}` 之後",
    )
    # The overview moved to /market: its widgets' own lines are not on the today page.
    old = [line for line in ("漲跌家數（股票）", "括號為漲停／跌停") if text.has(line)]
    expect(
        not old, "今日名單頁仍有大盤概況的 " + "、".join(f"`{line}`" for line in old)
    )
    return "、".join(f"`{line}`" for line in lines) + f"（{text.at(start)}）"


@check("today", "T15")
def t15(run: Run) -> str:
    """The shared daily K chart (the stock page's K-line card) of 加權指數 by default and of the TPEX / TX rows
    selected through ?index=: one chart per page, its badge, count and newest row; TX with its attribution."""

    found = []
    for shot, title, path, name, digits in MARKET_CHARTS:
        text = run.text(shot)
        try:
            payload = run.get(path, name)
        except Undetermined as exc:
            # No instrument yet (TPEX / TX before their first collect): the page
            # shows the chart without daily bars (MarketPage notFound).
            if "回 404" not in str(exc):
                raise
            payload = {"bars": []}
        i = text.find(title)
        expect(i >= 0, f"缺整行 `{title}`（{text.name}）")
        others = [other for other in CHART_TITLES if other != title and text.has(other)]
        expect(
            not others,
            f"{text.name} 只該有 `{title}` 一張圖，另有 "
            + "、".join(f"`{other}`" for other in others),
        )
        expect(
            text.find(INDEX_TABLE_TITLE) < i,
            f"`{title}` 不在 `{INDEX_TABLE_TITLE}` 之後（{text.name}）",
        )
        if digits == 0:
            expect(
                text.find(TAIFEX_ATTRIBUTION, i) >= 0,
                f"台指期之後缺整行 `{TAIFEX_ATTRIBUTION}`（{text.name}）",
            )
        if not payload.get("bars"):
            expect(
                text.find(NO_BARS, i) >= 0,
                f"`{title}`：API 沒有日線，缺整行 `{NO_BARS}`",
            )
            found.append(f"`{title}` `{NO_BARS}`")
            continue
        bars = [bar for bar in payload["bars"] if drawable(bar)]
        expect(bool(bars), f"`{title}`：API 的日線沒有一根可畫的 K 棒")
        as_of = payload.get("data_as_of")
        badge = f"資料 {slash(as_of)}" if as_of else PENDING_DATE
        expect(
            text.after(i) == badge,
            f"`{title}` 下一行是 {text.after(i)!r}，預期 `{badge}`",
        )
        count = f"最近 {payload.get('count')} 根日線；缺日不補、停牌不畫 K 線"
        expect(text.find(count, i) >= 0, f"`{title}`：缺整行 `{count}`")
        # The data table (newest first): date, then 開 高 低 收 in 點, tab separated.
        newest = bars[-1]
        row = f"{slash(newest['date'])}\t" + "\t".join(
            fixed(newest[key], digits) for key in ("open", "high", "low", "close")
        )
        k = text.find_where(lambda line: line.startswith(row), i)
        expect(k >= 0, f"`{title}`：資料表缺最新一根 `{row}`")
        found.append(f"`{title}` `{badge}`、`{count}`、最新 `{row}`")
    return "；".join(found)


# ---- T16: the market page's index table (Issue 564; 547's dates, 561's MA60; UI_COPY_SPEC §11) ----

INDEX_TABLE_TITLE = "指數總表"  # INDEX_TABLE_TITLE in market/marketOverview.ts
OVERVIEW_TITLE = "大盤概況"
# INDEX_SPECS in market/marketOverview.ts: the row key -> (name shown, price decimals), in table order.
# Issue 633: the page lists the Taiwan rows only; the API still returns the four US rows after them.
INDEX_SPECS = {
    "taiex": ("加權指數", 2),
    "tpex": ("櫃買指數", 2),
    "tx": ("台指期近月", 0),
}
# What the US rows and their notes read before Issue 633; none of these is a line of the page now.
US_LINES = ("美股", "美股（前一交易日）", "資料來源：FinMind（個人非商業使用）")
US_NAMES = ("S&P 500", "NASDAQ 綜合指數", "道瓊工業指數", "費城半導體指數")
INDEX_MA60_POSITION = {"above": "之上", "below": "之下", "equal": "持平"}


def index_missing_text(row: dict) -> str:
    """indexMissingText in market/marketOverview.ts."""

    if row.get("reason") == "no_verified_session":
        return "無資料：尚無已驗證的資料日"
    if row.get("reason") == "fetch_failed":
        day = row.get("last_attempt_date")
        return f"無資料：最近一次擷取失敗{f'（{slash(day)}）' if day else ''}"
    return "無資料：尚未收集"


def index_ma60_text(row: dict, digits: int) -> str:
    """indexMa60Cell in market/marketOverview.ts, as the cell's text."""

    item = row.get("ma60") if row.get("status") == "available" else None
    if not item:
        return "—"
    position = INDEX_MA60_POSITION.get(item.get("position") or "")
    if item.get("status") == "available" and item.get("ma60") is not None and position:
        return f"{position} 季線 {fixed(item['ma60'], digits)}"
    if item.get("status") == "insufficient":
        count = item.get("close_count")
        shown = "—" if count is None else fixed(count, 0)
        return f"資料不足（{shown}／{item.get('required_closes')} 日）"
    reasons = {
        "not_collected": "日線未收集",
        "row_date_mismatch": f"日線最新為 {slash(item.get('latest_trading_date') or '—')}",
        "indicator_not_computed": "季線尚未計算",
    }
    reason = reasons.get(item.get("reason") or "")
    return f"無資料：{reason}" if reason else "無資料"


def index_row_line(row: dict) -> str:
    """One table row as the page text has it (cells tab-separated; IndexTableView in market/MarketViews.tsx)."""

    name, digits = INDEX_SPECS[row["key"]]
    month = row.get("contract_month") if row.get("status") == "available" else None
    if month:
        shown = f"{month[:4]}/{month[4:]}" if re.fullmatch(r"\d{6}", month) else month
        name += f" 合約 {shown}"
    source = (row.get("source") or {}).get("label") or "—"
    if row.get("status") != "available" or not row.get("trading_date"):
        return "\t".join([name, "—", "—", "—", index_missing_text(row), "—", source])
    close, change, pct = row.get("close"), row.get("change"), row.get("change_pct")
    roll = row.get("change_status") == "contract_roll"
    date = slash(row["trading_date"])
    if row.get("freshness") == "stale":
        date += " 非最新"
    return "\t".join(
        [
            name,
            "—" if close is None else fixed(close, digits),
            "換月" if roll else "—" if change is None else fixed(change, digits, True),
            "換月" if roll else "—" if pct is None else f"{fixed(pct * 100, 2, True)}%",
            date,
            index_ma60_text(row, digits),
            source,
        ]
    )


@check("today", "T16")
def t16(run: Run) -> str:
    """The index table between 大盤概況 and the chart: the three Taiwan rows, no US rows (Issue 633)."""

    text = run.text(MARKET)
    overview = run.dashboard().get("market_overview") or {}
    rows = [
        row for row in overview.get("indexes") or [] if row.get("key") in INDEX_SPECS
    ]
    expect(
        [row.get("key") for row in rows] == list(INDEX_SPECS),
        f"dashboard.market_overview.indexes 的台股列是 {[row.get('key') for row in rows]}，預期 {list(INDEX_SPECS)}",
    )
    start, chart = text.find(INDEX_TABLE_TITLE), text.find(CHART_TITLES[0])
    expect(
        text.find(OVERVIEW_TITLE) < start
        and start >= 0
        and (chart < 0 or start < chart),
        f"缺整行 `{INDEX_TABLE_TITLE}`，或不在 `{OVERVIEW_TITLE}` 與 `{CHART_TITLES[0]}` 之間",
    )
    found, at = [], start
    for row in rows:
        line = index_row_line(row)
        k = text.find(line, at + 1)
        expect(k > at, f"{row['key']}：缺整行 `{line}`，或不在前一列之後")
        at = k
        found.append(f"`{line}`")
    expect(
        text.find(TAIFEX_ATTRIBUTION, start) >= 0,
        f"`{INDEX_TABLE_TITLE}` 之後缺整行 `{TAIFEX_ATTRIBUTION}`（資料說明）",
    )
    shown = [line for line in US_LINES if text.has(line)] + [
        name
        for name in US_NAMES
        if text.find_where(lambda line, name=name: line.startswith(name + "\t")) >= 0
    ]
    expect(not shown, "大盤頁仍有美股的 " + "、".join(f"`{line}`" for line in shown))
    return "；".join(found) + "；沒有美股列"


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


# Same as cleanNewsLead in frontend/src/news/newsView.ts (#523, NEWS_SPEC §6): the pages
# show a title without its leading marks and byline; the API keeps the source title.
LEAD_MARKS = re.compile(r"^[\s■□▪▫◆◇◈●○◎◉•・‧∙★☆▲△▶►▸▷※]+")
LEAD_BRACKET = re.compile(r"^[\[［【〔(（]([^\]］】〕)）]{1,30})[\]］】〕)）]")
BYLINE_BRACKET = re.compile(r"記者|報導$|電$|新聞網|新聞$")
LEAD_REPORTER = re.compile(
    r"^(?:實習)?記者[^／/╱\s]{1,12}[／/╱][^，。；、\s]{0,10}?報導"
)


def display_title(title: str | None) -> str:
    text = re.sub(r"\s+", " ", title or "").strip()
    if not text:
        return "標題未提供"
    rest = text
    for _ in range(4):
        before = rest
        rest = LEAD_MARKS.sub("", rest)
        bracket = LEAD_BRACKET.match(rest)
        if bracket and BYLINE_BRACKET.search(bracket.group(1).strip()):
            rest = rest[bracket.end() :]
        rest = LEAD_REPORTER.sub("", rest).lstrip()
        if rest == before:
            break
    return rest or text


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
            wanted = [display_title(item["title"]) for item in items[:3]]
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


def taipei_minute(value: Any) -> str | None:
    """Same as formatTaipeiInstant in frontend/src/news/newsView.ts: None without a zone."""

    if not isinstance(value, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return f"{parsed.astimezone(TAIPEI):%Y/%m/%d %H:%M}"


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
        line = text.find_where(lambda line: line.startswith(prefix))
        expect(line >= 0, f"缺 `{prefix}` 開頭的行")
        generated = taipei_minute(ai.get("generated_at"))
        expect(
            generated is not None,
            f"ai.generated_at {ai.get('generated_at')!r} 沒有時區",
        )
        stamp = f"產生時間 {generated}"
        expect(
            stamp in text.lines[line],
            f"{text.at(line)} 沒有 `{stamp}`：{text.lines[line]!r}",
        )
        return f"id {news_id}：來源事實／AI 摘要與判讀分欄，`{prefix} · {stamp}`"
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


# G2 failing on a board without a date already counts the missing scores once.
@check("themes", "G3", after=("G2",))
def g3(run: Run) -> str:
    payload = board(run, "industry")
    items = payload.get("items") or []
    wide, narrow = run.text(THEMES), run.text(THEMES, 390)
    if not items:
        return empty_board(run, payload, wide, "themes-industry.json")
    expect(
        wide.find_where(lambda line: line.startswith("排名\t族群")) < 0,
        "1280 仍有 `排名\\t族群` 表頭：族群榜應是兩行清單，不是表格（Issue 522）",
    )
    for text in (wide, narrow):
        for item in (items[0], items[-1]):
            board_row(text, item)
    first, last = items[0]["display_name"], items[-1]["display_name"]
    return f"1280 與 390：`#1` → `{first}`…`#{items[-1]['rank']}` → `{last}`，五分項與成員數同 API"


# BOARD_COMPONENTS in frontend/src/themes/themeBoards.ts, in the page's order.
BOARD_COMPONENTS = (
    ("relative_return", "相對報酬"),
    ("breadth", "廣度"),
    ("volume_strength", "量能"),
    ("institutional_flow", "法人"),
    ("catalyst", "催化劑"),
)


def board_component(value: float | None) -> str:
    """formatComponent: a 0–1 percentile on 0–100, no data 「—」."""
    return "—" if value is None else fixed(value * 100, 0)


def board_count(value: int | None) -> str:
    return "—" if value is None else str(value)


def board_row(text: Text, item: dict) -> None:
    """One board row (Issue 522, BoardRow in ThemeViews.tsx): `#<rank>`, the name, then after the
    `分數 …` line and the 五分項 button the folded components (screenshot.cjs opens every <details>)
    as label and value lines, and 成員（檔） eligible／total."""

    rank, name = item["rank"], item["display_name"]
    i = text.find(f"#{rank}")
    expect(i >= 0, f"{text.name} 缺整行 `#{rank}`")
    expect(
        text.after(i) == name,
        f"{text.name} `#{rank}` 下一行是 {text.after(i)!r}，預期 `{name}`（{text.at(i)}）",
    )
    j = text.find_where(lambda line: line.startswith("分數 "), i)
    expect(j >= 0, f"{text.name} `#{rank}` 之後缺 `分數 …` 行")
    components = item.get("components") or {}
    want = [
        part
        for key, label in BOARD_COMPONENTS
        for part in (label, board_component(components.get(key)))
    ]
    members = f"{board_count(item.get('eligible_members'))}／{board_count(item.get('member_count'))}"
    want += ["成員（檔）", members]
    got = text.lines[j + 2 : j + 2 + len(want)]
    expect(
        got == want,
        f"{text.name} `#{rank}` 的五分項是 {got}，預期 {want}（{text.at(j)}）",
    )


@check("themes", "G4")
def g4(run: Run) -> str:
    """Issue 627: the page no longer lists the news theme suggestions."""

    text = run.text(THEMES)
    gone = ["新聞題材建議", "新聞聚合 · AI 推論", "目前沒有新聞題材建議"]
    shown = [line for line in gone if text.has(line)]
    expect(not shown, "族群頁仍有 " + "、".join(f"`{line}`" for line in shown))
    return "族群頁沒有新聞題材建議區"


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
    # The theme board appends 證據 (UI_COPY_SPEC §8.5).
    header = "代號\t名稱\t市場\t收盤（元）\t漲跌幅（%）\t成交金額（億元）\t5 日相對（%）\t20 日相對（%）"
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
    payload, text = theme_detail(run)  # T first: without it there is no path to compare
    today = run.text(TODAY)
    start = today.find("熱門族群")
    i = today.find("#1", max(start, 0))
    expect(i >= 0, "今日頁 `熱門族群` 之後缺 `#1`")
    today_name = today.after(i)
    board_name = (board(run, "industry").get("items") or [{}])[0].get("display_name")
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


def turnover_order(item: dict) -> tuple:
    """The API's sort=turnover key: largest first, null last, then symbol (#280)."""

    value = item.get("turnover")
    return (value is None, -(value or 0), item["symbol"], item.get("exchange") or "")


@check("themes", "G8")
def g8(run: Run) -> str:
    _payload, text = theme_detail(run)
    items = members(run).get("items") or []
    symbols = [item["symbol"] for item in items]
    expected = [item["symbol"] for item in sorted(items, key=turnover_order)]
    expect(
        symbols == expected,
        f"theme-members.json 不是依成交金額由大到小：{'、'.join(symbols)}，預期 {'、'.join(expected)}",
    )
    # Member rows of the 1280 table start with the symbol cell.
    shown = [
        symbol
        for line in text.lines
        for symbol in symbols
        if line.startswith(f"{symbol}\t")
    ]
    expect(
        shown == symbols,
        f"頁面成員順序 {'、'.join(shown) or '（無）'} ≠ sort=turnover 的 {'、'.join(symbols)}",
    )
    return f"成員依成交金額：{'、'.join(symbols) or '（無成員）'}"


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


def raw_I(run: Run, stock: Stock) -> str | None:
    return (run.facts(stock).get("instrument") or {}).get("latest_trading_date")


def stock_I(run: Run, stock: Stock) -> str:
    missing = f"facts-{stock.prefix}.json 沒有 latest_trading_date（I）"
    return run.needs("I", raw_I(run, stock), missing, stock.label)


def stock_text(run: Run, stock: Stock, tab: str = "main", width: int = 1280) -> Text:
    return run.text(stock_shots(stock)[tab], width)


STOCKS = Shot("stocks", "/stocks")
# backend/app/api.py STOCK_TYPE_ORDER, mirrored: verify does not import the app.
STOCK_TYPE_RANK = {"stock": 0, "etf": 1, "ipo": 2}


# The directory /stocks needs no E/S (#251); without one only the stock pages go unchecked.
@check("stocks", "S1", per_stock=True, needs_stock=False)
def s1(run: Run, stock: Stock | None) -> str:
    if stock is None:
        detail = usable(run, [STOCKS])
        return f"{detail}（只驗 /stocks；未選到個股：{run.picked}）"
    shots = list(stock_shots(stock).values())
    if stock.prefix == "stock":
        shots.insert(0, STOCKS)
    return usable(run, shots)


@check("stocks", "S2")
def s2(run: Run, stock: Stock | None) -> str:
    payload = run.get("stocks?page=1&page_size=30", "stocks.json")
    text = run.text(STOCKS)
    header = "代號\t名稱\t交易所\t類型\t最近收盤（元）\t目前研究動作"
    expect(text.has(header), "缺目錄表頭整行")
    items = payload.get("items") or []
    total = (payload.get("meta") or {}).get("total") or 0
    if items:
        symbol = items[0]["instrument"]["symbol"]
        expect(
            text.find_where(lambda line: line.startswith(symbol)) >= 0,
            f"缺 `{symbol}` 開頭的列",
        )
        # The default order (#602): stocks, then ETFs, then new listings, each by symbol.
        keys = [
            (
                STOCK_TYPE_RANK.get(
                    item["instrument"]["instrument_type"], len(STOCK_TYPE_RANK)
                ),
                item["instrument"]["symbol"],
            )
            for item in items
        ]
        expect(keys == sorted(keys), f"預設順序不是類型→代號：{keys[:5]}…")
    else:
        expect(text.has("沒有符合條件的標的。"), "items 空，缺空資料文案")
    pager = f"第 1／{max(1, math.ceil(total / 30))} 頁 · 共 {total:,} 筆"
    expect(text.has(pager), f"缺整行 `{pager}`")
    return f"表頭、第一列、類型→代號順序、`{pager}`"


@check("stocks", "S3", per_stock=True)
def s3(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock), stock_I(run, stock)
    expect(text.has(stock.symbol), f"缺整行 `{stock.symbol}`")
    data = [n for n, line in enumerate(text.lines) if line.startswith("資料 ")]
    expect(len(data) >= 2, f"`資料 ` 開頭的行只有 {len(data)} 行")
    d = run.D()
    expect(
        text.lines[data[0]] == f"資料 {slash(d)}",
        f"第一個資料行 {text.lines[data[0]]!r}，預期導覽列 `資料 {slash(d)}`",
    )
    expect(
        text.lines[data[1]] == f"資料 {slash(i)}",
        f"第二個資料行 {text.lines[data[1]]!r}，預期 `資料 {slash(i)}`（{text.at(data[1])}）",
    )
    source = text.after(data[1]) or ""
    expect(
        source.startswith("來源 ") and source != "來源 尚無已核對的價格來源",
        f"頁首資料行下一行是 {source!r}",
    )
    bars_as_of = stock_bars(run, stock).get("data_as_of")
    expect(i == bars_as_of, f"I {i} ≠ stock-bars data_as_of {bars_as_of}")
    return f"頁首 `資料 {slash(i)}`、`{source}`；bars data_as_of {bars_as_of}"


@check("stocks", "S4", per_stock=True)
def s4(run: Run, stock: Stock) -> str:
    text, i = stock_text(run, stock), stock_I(run, stock)
    k = text.find("K 線與技術指標")
    expect(k >= 0, "缺整行 `K 線與技術指標`")
    expect(
        text.after(k) == f"資料 {slash(i)}",
        f"`K 線與技術指標` 下一行是 {text.after(k)!r}，預期 `資料 {slash(i)}`",
    )
    for prefix in ("來源 ", "日線批次計算於"):
        expect(
            text.find_where(lambda line: line.startswith(prefix)) >= 0,
            f"缺 `{prefix}` 開頭的行",
        )
    return f"K 線卡 `資料 {slash(i)}`、來源與批次時間"


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
    # The candidate row of the strategy board (#274): only the board's as-of candidate.
    if (payload.get("strategy_board") or {}).get("candidate") is not None:
        expect(text.has("每日候選"), "策略總表有候選，缺整行 `每日候選`")
        expect(text.has("AI 推論"), "策略總表有候選，缺 `AI 推論`")
        rows = source_lines(text)
        expect(rows, "策略總表有候選，缺 `來源：` 行")
        bad = [text.at(row) for row in rows if not text.lines[row].endswith("（推論）")]
        expect(not bad, f"`來源：` 行沒有以 `（推論）` 結尾：{'、'.join(bad)}")
        note += f"；候選 #{payload['candidate'].get('rank')}：`每日候選`、`AI 推論`、`（推論）`"
    return note


# frontend/src/stock/strategyBoard.ts STATUS_LABELS and OBSERVATION_LABEL (#274).
BOARD_STATUS = {
    "conditional": "成立",
    "observation": "觀察",
    "data_incomplete": "資料不足",
    "not_applicable": "不適用",
}
OBSERVATION_LABEL = "條件未成立・觀察價位"


@check("stocks", "S10", per_stock=True)
def s10(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock, "research")
    board = stock_payload(run, stock).get("strategy_board")
    expect(isinstance(board, dict), "stock.json 沒有 strategy_board")
    k = text.find("策略總表")
    expect(k >= 0, "缺整行 `策略總表`")
    as_of = board.get("as_of")
    if as_of:
        expect(
            text.after(k) == f"資料 {slash(as_of)}",
            f"`策略總表` 下一行是 {text.after(k)!r}，預期 `資料 {slash(as_of)}`",
        )
    else:
        expect(
            text.has("此股尚無策略判定資料。"),
            "as_of null，缺 `此股尚無策略判定資料。`",
        )
    rows = board.get("strategies") or []
    expect(bool(rows), "strategy_board.strategies 是空的")
    # The 1280 text is the desktop table (the phone cards are display:none): each
    # strategy's row starts with its label cell, the status badge opens the next line.
    starts = []
    for row in rows:
        i = text.find(f"{row['label']}\t")
        expect(i >= 0, f"缺 `{row['label']}<TAB>` 開頭的表格列")
        status = BOARD_STATUS.get(row["status"], "?")
        line = text.after(i) or ""
        # A passed row puts its earliest execution date under the badge.
        expect(
            line == status or line.startswith(f"{status}\t"),
            f"{row['label']} 的狀態行是 {line!r}，預期是 `{status}` 或以 `{status}<TAB>` 開頭（{text.at(i)}）",
        )
        starts.append(i)
    observed = [
        row for row in rows if (row.get("levels") or {}).get("kind") == "observation"
    ]
    # #519: the summary card above the tabs repeats the closest strategy's observation
    # levels, so only the labels from `策略總表` on are the board's.
    labels = text.lines[k:].count(OBSERVATION_LABEL)
    expect(
        labels == len(observed),
        f"`{OBSERVATION_LABEL}` {labels} 行，API 有 {len(observed)} 列觀察價位",
    )
    # Actionable levels never sit under the observation label.
    for row, start in zip(rows, starts):
        if row["status"] != "conditional":
            continue
        end = min((s for s in starts if s > start), default=len(text.lines))
        segment = text.lines[start:end]
        expect(
            OBSERVATION_LABEL not in segment,
            f"{row['label']} 成立，但它的列有 `{OBSERVATION_LABEL}`",
        )
    candidate = board.get("candidate")
    if candidate:
        line = f"第 {candidate['rank']} 名 · 總分 {round(candidate['total_score'] * 100)} · "
        expect(
            text.find_where(lambda value: value.startswith(line)) >= 0,
            f"候選列缺 `{line}…`",
        )
    else:
        expect(not text.has("每日候選"), "策略總表沒有候選，卻有 `每日候選`")
    statuses = "、".join(
        f"{row['label']} {BOARD_STATUS.get(row['status'])}" for row in rows
    )
    return f"`策略總表` 資料 {as_of}；{statuses}；觀察價位 {len(observed)} 列；" + (
        f"候選第 {candidate['rank']} 名" if candidate else "非候選"
    )


# The summary card under the stock header (#519, UI_COPY_SPEC §8.2 摘要卡): StockSummaryCard
# and stockVerdict in frontend/src/stock/.
SUMMARY_COLUMNS = ("目前判斷", "最接近成立", "規則價位")
SUMMARY_LINK = "完整條件 →"
INCOMPLETE_ACTIONS = ("data_insufficient", "data_incomplete", "insufficient_data")
CANDIDATE_STRATEGY = {
    f"{kind}_v{n}": label
    for kind, label in (("breakout", "突破條件"), ("pullback", "回踩條件"))
    for n in (1, 2, 3)
}  # candidateStrategyLabel


def summary_verdict(payload: dict) -> tuple[str, str | None]:
    """The verdict badge and, where the API alone gives it, the reason sentence."""

    board = payload.get("strategy_board") or {}
    action = payload.get("decision_summary") or {}
    rows = board.get("strategies") or []
    state = action.get("action_state")
    candidate = board.get("candidate")
    if not board and not action:
        return "無資料", "尚無行動摘要。"
    if state == "reduce_exit":
        return "持倉風險", None
    if candidate:
        strategy = CANDIDATE_STRATEGY.get(candidate.get("strategy"), "策略條件")
        score = round(candidate["total_score"] * 100)
        # 條件成立, not 可買: 今日名單 is not a recommendation (#581).
        return (
            "條件成立",
            f"每日候選第 {candidate['rank']} 名 · 總分 {score} · {strategy}",
        )
    if state == "hold_observe":
        return "持倉觀察", None
    if state == "manual_review":
        return "需人工判讀", None
    if rows and all(row.get("status") == "not_applicable" for row in rows):
        return "不適用", None
    if state in INCOMPLETE_ACTIONS:
        gaps = [g["label"] for g in action.get("gap_reasons") or [] if g.get("label")]
        return "資料不足", "；".join(gaps) if gaps else None
    if any(row.get("status") == "conditional" for row in rows):
        return "條件成立", None
    reason = (action.get("primary_reason") or {}).get("label")
    return "觀察", reason


@check("stocks", "S11", per_stock=True)
def s11(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock)
    payload = stock_payload(run, stock)
    verdict, reason = summary_verdict(payload)
    k = text.find(SUMMARY_COLUMNS[0])
    expect(k >= 0, f"缺整行 `{SUMMARY_COLUMNS[0]}`（摘要卡）")
    tabs = text.find("走勢", k)
    expect(tabs > k, "摘要卡之後缺分頁籤 `走勢`")
    card = text.lines[k:tabs]
    expect(
        verdict in card[1:4],
        f"`目前判斷` 後三行 {card[1:4]}，預期判斷 `{verdict}`（{text.at(k)}）",
    )
    v = card.index(verdict)
    if reason is not None:
        shown = card[v + 1] if v + 1 < len(card) else None
        expect(shown == reason, f"判斷 `{verdict}` 下一行是 {shown!r}，預期 `{reason}`")
    rows = (payload.get("strategy_board") or {}).get("strategies") or []
    columns = SUMMARY_COLUMNS if rows else SUMMARY_COLUMNS[:2]
    for label in columns[1:]:
        expect(label in card[v:], f"摘要卡缺整行 `{label}`")
    expect(SUMMARY_LINK in card, f"摘要卡缺整行 `{SUMMARY_LINK}`")
    return (
        f"摘要卡 `{verdict}`"
        + (f"：`{reason}`" if reason else "")
        + f"；{'、'.join(columns)}、`{SUMMARY_LINK}`"
    )


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
    expect(
        text.after(k) == slash(i),
        f"`K 線資料日期` 下一行是 {text.after(k)!r}，預期 `{slash(i)}`",
    )
    s = text.find("行情來源")
    expect(s >= 0, "缺整行 `行情來源`")
    source = text.after(s)
    expect(bool(source) and source != "待核實", f"`行情來源` 下一行是 {source!r}")
    suffix = f"資料日 {slash(i)}"
    expect(
        text.find_where(lambda line: line.endswith(suffix)) >= 0,
        f"缺 `{suffix}` 結尾的行",
    )
    return f"K 線資料日期 {slash(i)}、行情來源 `{source}`、`…{suffix}`"


@check("stocks", "S8", per_stock=True)
def s8(run: Run, stock: Stock) -> str:
    instrument = run.facts(stock).get("instrument") or {}
    i = raw_I(run, stock)
    if not i:
        raise Undetermined(f"facts-{stock.prefix}.json 沒有 latest_trading_date（I）")
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
    shown = min(30, len(chips))
    counts = []
    # One line per value group (#395); the first of each is the latest row.
    for label, key in (("法人", "institutional"), ("融資", "margin")):
        rows = text.count(lambda line, label=label: line.startswith(f"{label}："))
        expect(rows == shown, f"`{label}：` 開頭 {rows} 行，預期 {shown}")
        group = chips[-1].get(key)
        first = text.lines[
            text.find_where(lambda line, label=label: line.startswith(f"{label}："))
        ]
        if group is None:
            expect(
                first == f"{label}：無資料",
                f"最新一列 `{first}`，預期 `{label}：無資料`",
            )
        else:
            part = f"（{group['source']}） · 資料截至：{slash(group['data_as_of'])} · 收集："
            expect(part in first, f"最新一列 `{first}` 缺 `{part}`")
        counts.append(f"{label} {rows}")
    return (
        f"最新一列 {latest.strip()}；來源行 {'、'.join(counts)} = min(30, {len(chips)})"
    )


# The 財務 tab (#528; UI_COPY_SPEC §8.2 財務分頁), frontend/src/stock/stockFundamentals.ts.
FUNDAMENTALS_TITLE, NOT_PROVIDED = "季報營收與 EPS", "來源未提供"
FUNDAMENTALS_EMPTY = {
    "etf": "ETF 沒有公司財報，不適用。",
    "ipo": "新上市公司尚未有已收集的季報：官方季報快照與彙總報表都還沒有這檔。",
}
FUNDAMENTALS_EMPTY_STOCK = "尚未收集到這檔的季報：官方季報快照與彙總報表都沒有這檔。"
QUARTER = re.compile(r"^(\d{4})-\d{2}-\d{2}$")


def fundamental_row_prefix(row: dict) -> str:
    """The page's first cells of one row: 期別, 累計營收（億元）, 累計 EPS, ROE, 可得日."""

    year = QUARTER.match(row["period_end"] or "")
    period = row["fiscal_period"] or ""
    if year and re.fullmatch(r"Q[1-4]", period):
        label = f"{year.group(1)} 年第 {period[1]} 季"
    elif year and re.fullmatch(r"M(0[1-9]|1[0-2])", period):
        label = f"{year.group(1)} 年 {int(period[1:])} 月"
    else:
        label = slash(row["period_end"])

    def cell(value: Any, scale: float = 1) -> str:
        if isinstance(value, (int, float)) and math.isfinite(value):
            return fixed(value / scale, 2)
        return NOT_PROVIDED

    announced = slash(row["announcement_date"]) if row["announcement_date"] else None
    return "\t".join(
        [
            label,
            cell(row["revenue"], 100_000),
            cell(row["eps"]),
            cell(row["roe"]),
            announced or NOT_PROVIDED,
        ]
    )


@check("stocks", "S12", per_stock=True)
def s12(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock, "financials")
    payload = stock_payload(run, stock)
    rows = payload.get("fundamentals") or []
    title = text.find(FUNDAMENTALS_TITLE)
    expect(title >= 0, f"缺整行 `{FUNDAMENTALS_TITLE}`")
    if not rows:
        kind = ((payload.get("instrument") or {}).get("instrument_type") or "").lower()
        reason = FUNDAMENTALS_EMPTY.get(kind, FUNDAMENTALS_EMPTY_STOCK)
        expect(text.has(reason), f"fundamentals 空，缺 `{reason}`")
        expect(
            text.find_where(lambda line: "年第" in line and "\t" in line) < 0,
            "fundamentals 空卻有期別列",
        )
        return f"fundamentals 空，顯示 `{reason}`"
    latest = max(row["data_as_of"] or row["period_end"] for row in rows)
    badge = f"資料 {slash(latest)}"
    expect(text.find(badge, title) >= 0, f"`{FUNDAMENTALS_TITLE}` 之後缺 `{badge}`")
    found = []
    for row in rows:
        prefix = fundamental_row_prefix(row) + "\t"
        at = text.find_where(lambda line, p=prefix: line.startswith(p), title)
        expect(at >= 0, f"缺 `{prefix.strip()}` 開頭的列")
        found.append(at)
    expect(found == sorted(found), f"列的順序不是 API 的順序：{found}")
    expect(
        text.find_where(lambda line: line.startswith("來源："), title) >= 0,
        "表格下缺 `來源：` 行",
    )
    return f"{len(rows)} 列與 API 相同（第一列 `{fundamental_row_prefix(rows[0])}`）；{badge}"


# The 月營收 card under the quarterly table (#530; UI_COPY_SPEC §8.2 財務分頁),
# frontend/src/stock/stockFundamentals.ts.
MONTHLY_TITLE = "月營收"
MONTHLY_EMPTY = {
    "etf": "ETF 不申報月營收，不適用。",
    "ipo": "新上市公司尚未有已收集的月營收：官方月營收快照與營業收入統計表都還沒有這檔。",
}
MONTHLY_EMPTY_STOCK = (
    "尚未收集到這檔的月營收：官方月營收快照與營業收入統計表都沒有這檔。"
)
REVENUE_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def monthly_row_prefix(row: dict) -> str:
    """The page's first cells of one month: 月份, 營收（億元）, 年增率（%）, 可得日."""

    month = REVENUE_MONTH.match(row["revenue_month"] or "")
    label = (
        f"{month.group(1)} 年 {int(month.group(2))} 月"
        if month
        else row["revenue_month"]
    )

    def cell(value: Any, scale: float, digits: int, signed: bool = False) -> str:
        if isinstance(value, (int, float)) and math.isfinite(value):
            return fixed(value / scale, digits, signed)
        return NOT_PROVIDED

    announced = slash(row["announcement_date"]) if row["announcement_date"] else None
    return "\t".join(
        [
            label,
            cell(row["revenue"], 100_000, 2),
            cell(row["yoy"], 1, 1, signed=True),
            announced or NOT_PROVIDED,
        ]
    )


@check("stocks", "S13", per_stock=True)
def s13(run: Run, stock: Stock) -> str:
    text = stock_text(run, stock, "financials")
    payload = stock_payload(run, stock)
    rows = payload.get("monthly_revenues") or []
    title = text.find(MONTHLY_TITLE)
    expect(title >= 0, f"缺整行 `{MONTHLY_TITLE}`")
    if not rows:
        kind = ((payload.get("instrument") or {}).get("instrument_type") or "").lower()
        reason = MONTHLY_EMPTY.get(kind, MONTHLY_EMPTY_STOCK)
        expect(text.find(reason, title) >= 0, f"monthly_revenues 空，缺 `{reason}`")
        expect(
            text.find_where(
                lambda line: re.match(r"^\d{4} 年 \d{1,2} 月\t", line) is not None,
                title,
            )
            < 0,
            "monthly_revenues 空卻有月份列",
        )
        return f"monthly_revenues 空，顯示 `{reason}`"
    latest = max(row["data_as_of"] or row["revenue_month"] for row in rows)
    badge = f"資料 {slash(latest)}"
    expect(text.find(badge, title) >= 0, f"`{MONTHLY_TITLE}` 之後缺 `{badge}`")
    found = []
    for row in rows:
        prefix = monthly_row_prefix(row) + "\t"
        at = text.find_where(lambda line, p=prefix: line.startswith(p), title)
        expect(at >= 0, f"缺 `{prefix.strip()}` 開頭的列")
        found.append(at)
    expect(found == sorted(found), f"列的順序不是 API 的順序：{found}")
    expect(
        text.find_where(lambda line: line.startswith("來源："), title) >= 0,
        f"`{MONTHLY_TITLE}` 表格下缺 `來源：` 行",
    )
    return f"{len(rows)} 個月與 API 相同（第一列 `{monthly_row_prefix(rows[0])}`）；{badge}"


# ---- actions ----

# The page is 我的追蹤 at /watch since #493; the old /actions redirects there (A18).
ACTIONS = Shot("actions", "/watch")
# The old URL with a query and a plan anchor; both must survive the redirect (#493 review).
LEGACY_QUERY, LEGACY_ANCHOR = "from=legacy", "plan-0"
ACTIONS_LEGACY = Shot(
    "actions-legacy", f"/actions?{LEGACY_QUERY}#{LEGACY_ANCHOR}", (1280,)
)
WATCH_TITLE, WATCH_EYEBROW = (
    "我的追蹤",
    "追蹤與提醒",
)  # ActionsPage in frontend/src/App.tsx


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


# Each tier section opens with `第 N 級`, its label and `顯示 k／N 檔` (UI_COPY_SPEC §5, #278).
TIER_HEAD = re.compile(r"^第 ([0-5]) 級$")
# A table row of the action list ends with its 資料日 cell and the link cell; a
# tier 3 row's link says 價位見策略總表 → (UI_COPY_SPEC §6, #277-B).
NEAR_ROW_LINK = "價位見策略總表 →"
ACTION_ROW = re.compile(r"\t([0-9]{4}/[0-9]{2}/[0-9]{2})\t(?:價位見)?策略總表 →$")
ACTIONS_EMPTY = "目前沒有符合篩選的標的。"


def tier_block(text: Text, tier: dict) -> tuple[int, int]:
    """(label line, end) of a tier section; (-1, -1) when the page has none."""

    for i, line in enumerate(text.lines[:-1]):
        if line == f"第 {tier['tier']} 級" and text.lines[i + 1] == tier["label"]:
            end = text.find_where(lambda line: bool(TIER_HEAD.match(line)), i + 1)
            return i + 1, end if end > 0 else len(text.lines)
    return -1, -1


def listed_tiers(payload: dict) -> list[dict]:
    return [
        tier
        for tier in (payload.get("summary") or {}).get("tiers") or []
        if tier.get("shown")
    ]


# A tier with rows but none on the first page loads its first rows on its own
# (ACTION_TIER_PREVIEW in frontend/src/actions/actionTiers.ts, UI_COPY_SPEC §5).
ACTION_TIER_PREVIEW = 5
MAX_ACTION_PAGE = 100  # backend/app/api.py MAX_PAGE_SIZE


def loaded_actions(run: Run) -> list[dict]:
    """The rows the actions page shows on load, in page order of their tiers."""

    payload = actions_payload(run)
    items = list(payload.get("items") or [])
    for tier in listed_tiers(payload):
        if not any(item.get("tier") == tier["tier"] for item in items):
            preview = run.get(
                f"actions?tier={tier['tier']}&limit={ACTION_TIER_PREVIEW}",
                f"actions-tier{tier['tier']}.json",
            )
            items += preview.get("items") or []
    return items


def instrument_key(item: dict) -> tuple:
    instrument = item.get("instrument") or {}
    return (instrument.get("exchange"), instrument.get("symbol"))


@check("actions", "A3")
def a3(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    items = loaded_actions(run)
    tiers = listed_tiers(payload)
    if not tiers:
        expect(text.has(ACTIONS_EMPTY), f"summary 沒有列出的級別，缺 `{ACTIONS_EMPTY}`")
        return f"沒有列出的級別，顯示 `{ACTIONS_EMPTY}`"
    shown = []
    for tier in tiers:
        start, end = tier_block(text, tier)
        expect(start >= 0, f"缺 `第 {tier['tier']} 級`／`{tier['label']}` 區塊")
        k = sum(item.get("tier") == tier["tier"] for item in items)
        line = f"顯示 {k:,}／{tier['shown']:,} 檔"
        expect(
            text.after(start) == line,
            f"`{tier['label']}` 下一行是 {text.after(start)!r}，預期 `{line}`（{text.at(start)}）",
        )
        rest = tier["shown"] - k
        if rest > 0:
            more = f"顯示更多（還有 {rest:,} 檔）"
            expect(more in text.lines[start:end], f"`{tier['label']}` 缺 `{more}`")
        shown.append(f"{tier['label']} `{line}`")
    hidden = [
        tier["label"]
        for tier in (payload.get("summary") or {}).get("tiers") or []
        if not tier.get("shown") and tier_block(text, tier)[0] >= 0
    ]
    expect(not hidden, f"shown 為 0 的級別仍有區塊：{'、'.join(hidden)}")
    return "；".join(shown)


@check("actions", "A4")
def a4(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    dates = [m.group(1) for line in text.lines if (m := ACTION_ROW.search(line))]
    k = len(dates)
    items = loaded_actions(run)
    # #251: zero rows against a non-empty API is a page that lost its rows, not a pass.
    expect(k > 0 or not items, f"actions.json items {len(items)}，頁面沒有任何行動列")
    expect(
        k == len(items),
        f"以 `策略總表 →` 結尾的列 {k}，actions.json 與各級首批 items {len(items)}",
    )
    as_of = ((payload.get("meta") or {}).get("data_as_of") or "")[:10]
    expect(bool(as_of), "actions.json 沒有 meta.data_as_of")
    late = sorted({day for day in dates if day > slash(as_of)})
    expect(not late, f"列的資料日 {late} 晚於 data_as_of {slash(as_of)}")
    latest = run.facts()["market_latest_trading_date"]
    expect(
        as_of == latest,
        f"data_as_of {as_of} ≠ facts market_latest_trading_date {latest}",
    )
    return f"{k} 列各有資料日 ≤ {slash(as_of)}；data_as_of = facts"


@check("actions", "A5")
def a5(run: Run) -> str:
    text = run.text(ACTIONS)
    hits = [
        text.at(i)
        for i, line in enumerate(text.lines)
        if "AI 推論" in line or "（推論）" in line
    ]
    expect(not hits, f"出現 LLM 推論標記：{'、'.join(hits)}")
    # #251: a check for what must be absent proves nothing on a page without rows.
    k = text.count(lambda line: bool(ACTION_ROW.search(line)))
    if k == 0:
        raise Undetermined("頁面沒有行動列，沒有可查的內容")
    return f"{k} 列，沒有 `AI 推論` 與 `（推論）`"


def action_detail(run: Run) -> tuple[Stock, dict, Text]:
    stock = run.stock()
    payload = run.get(f"actions/{stock.exchange}/{stock.symbol}", "action-detail.json")
    return stock, payload, run.text(action_detail_shot(stock))


@check("actions", "A6")
def a6(run: Run) -> str:
    stock, payload, text = action_detail(run)
    # The shot clicks nothing: 研究動作 shows only on the research tab, so it proves
    # /actions/E/S landed on /stocks/E/S?tab=research (#278).
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


def tier_of(payload: dict, number: int) -> dict:
    tiers = (payload.get("summary") or {}).get("tiers") or []
    return next((tier for tier in tiers if tier.get("tier") == number), {})


@check("actions", "A8")
def a8(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    listed = candidates(run)
    tier = tier_of(payload, 1)
    expect(bool(tier), "actions.json summary.tiers 沒有第 1 級")
    rows = [item for item in loaded_actions(run) if item.get("tier") == 1]
    start, end = tier_block(text, tier)
    ranks = [
        int(match.group(1))
        for line in text.lines[max(start, 0) : end if start >= 0 else 0]
        if (match := RANK_ROW.match(line))
    ]
    loaded = [(item.get("candidate") or {}).get("rank") for item in rows]
    expect(
        ranks == loaded, f"今日候選區的 `#n` 列 {ranks}，actions.json 第 1 級 {loaded}"
    )
    as_of = ((payload.get("meta") or {}).get("data_as_of") or "")[:10]
    # A held candidate is listed in tier 0 (持倉風險), not in 今日候選.
    held = {
        instrument_key(item)
        for item in run.get(
            f"actions?tier=0&limit={MAX_ACTION_PAGE}", "actions-holdings.json"
        ).get("items")
        or []
    }
    want = [
        item["rank"]
        for item in listed.get("items") or []
        if instrument_key(item) not in held
    ]
    if listed.get("trading_date") != as_of:
        # Candidates of another day are not today's tier 1.
        expect(
            not ranks,
            f"candidates.json 是 {listed.get('trading_date')}，資料日 {as_of} 卻有今日候選列",
        )
        return f"candidates.json {listed.get('trading_date')} ≠ 資料日 {as_of}，沒有今日候選列"
    if tier.get("shown") == len(rows):
        count = (listed.get("candidate_count") or 0) - (
            len(listed.get("items") or []) - len(want)
        )
        expect(
            ranks == want and len(ranks) == count,
            f"今日候選區 {ranks}，預期 candidates.json 去掉持倉後的 {want}"
            f"（candidate_count {listed.get('candidate_count')}，持倉中的候選 "
            f"{len(listed.get('items') or []) - len(want)} 檔）",
        )
        return f"今日候選 {len(ranks)} 列 = candidates.json 去掉持倉，依名次 {ranks}"
    # Holdings took the first page: the loaded rows are the top of the list.
    expect(
        ranks == want[: len(ranks)],
        f"今日候選區 {ranks} 不是 candidates.json {want} 的前段",
    )
    return f"今日候選已載入 {len(ranks)}／{tier.get('shown')} 列，依名次 = candidates.json 前段"


# An action row's market line: `上市 · ETF` and the next cells (UI_COPY_SPEC §5).
ETF_ROW = re.compile(r"^(上市|上櫃|市場待核實) · ETF(\t|$)")


@check("actions", "A9")
def a9(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    summary = payload.get("summary") or {}
    etfs = [
        item
        for item in loaded_actions(run)
        if (item.get("instrument") or {}).get("instrument_type") == "etf"
    ]
    # Holdings and the watchlist are listed in every view.
    listed = [
        (item.get("instrument") or {}).get("symbol")
        for item in etfs
        if item.get("tier") != 0 and not item.get("watchlisted")
    ]
    expect(not listed, f"預設清單列出 ETF：{'、'.join(map(str, listed))}")
    expect(
        (summary.get("view"), summary.get("include_etf")) == ("focus", False),
        f"actions.json 不是預設篩選：view {summary.get('view')}、include_etf {summary.get('include_etf')}",
    )
    rows = text.count(lambda line: bool(ETF_ROW.match(line)))
    expect(
        rows == len(etfs),
        f"頁面 `· ETF` 列 {rows}，actions.json 的持倉／自選 ETF {len(etfs)}",
    )
    hidden = (summary.get("hidden") or {}).get("etf")
    return f"預設清單沒有 ETF（持倉／自選 ETF {len(etfs)} 列）；隱藏 ETF {hidden} 檔"


def hidden_line(summary: dict) -> str | None:
    """The hidden-rows line of UI_COPY_SPEC §5 for the default filter."""

    hidden = summary.get("hidden") or {}
    parts = [
        f"{label} {hidden.get(key) or 0:,} 檔"
        for label, key in (
            ("ETF", "etf"),
            ("其他觀察", "observation"),
            ("資料不足", "data_insufficient"),
        )
        if hidden.get(key)
    ]
    if not parts:
        return None
    return f"預設隱藏：{'、'.join(parts)}；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。"


@check("actions", "A10")
def a10(run: Run) -> str:
    payload, text = actions_payload(run), run.text(ACTIONS)
    summary = payload.get("summary") or {}
    expect(
        isinstance(summary.get("hidden"), dict),
        "actions.json 沒有 summary.hidden（頁首隱藏數的來源）",
    )
    line = hidden_line(summary)
    if line is None:
        found = text.find_where(lambda value: value.startswith("預設隱藏："))
        expect(
            found < 0,
            f"summary.hidden 都是 0，頁面仍有 `預設隱藏：`（{text.at(found)}）",
        )
        return "summary.hidden 都是 0，沒有隱藏句"
    expect(text.has(line), f"缺整行 `{line}`")
    return f"`{line}`"


# ---- tier 3 接近成立 (#277-B) ----

# A near card's numbers that are not prices: ratios (「1.20 倍」「0.60～1.20 倍」)
# and percents (the price gap, the day's change).
NOT_PRICE = re.compile(r"[0-9][0-9.,]*(?:～[0-9][0-9.,]*)? 倍|[+-]?[0-9][0-9.,]*%")
PRICE_NUMBER = re.compile(r"(?<![0-9.,])[0-9][0-9,]*\.[0-9]{2}(?![0-9])")
NEAR_LINE = re.compile(r"(?:^|\t)差：")


def near_rows(run: Run) -> tuple[list[list[str]], list[dict]]:
    """The tier 3 block's table rows (their lines) and the loaded tier 3 items."""

    payload, text = actions_payload(run), run.text(ACTIONS)
    tier = tier_of(payload, 3)
    expect(bool(tier), "actions.json summary.tiers 沒有第 3 級")
    items = [item for item in loaded_actions(run) if item.get("tier") == 3]
    if not tier.get("shown"):
        # A check of what near cards show proves nothing without one (#251).
        raise Undetermined("第 3 級（接近成立）沒有標的，沒有可查的接近卡")
    start, end = tier_block(text, tier)
    expect(start >= 0, f"缺 `第 3 級`／`{tier.get('label')}` 區塊")
    rows, current = [], []
    for line in text.lines[start + 2 : end]:
        current.append(line)
        if ACTION_ROW.search(line):
            rows.append(current)
            current = []
    return rows, items


@check("actions", "A11")
def a11(run: Run) -> str:
    rows, items = near_rows(run)
    expect(
        len(rows) == len(items),
        f"接近成立區 {len(rows)} 列，actions.json 第 3 級 {len(items)} 列",
    )
    links = [row[-1] for row in rows if not row[-1].endswith(NEAR_ROW_LINK)]
    expect(not links, f"接近成立列的連結不是 `{NEAR_ROW_LINK}`：{'；'.join(links)}")
    flat = [
        (item.get("instrument") or {}).get("symbol")
        for item in items
        if not (item.get("nearness") or {}).get("near")
    ]
    expect(not flat, f"第 3 級的列沒有 nearness.near：{'、'.join(map(str, flat))}")
    return f"接近成立 {len(rows)} 列 = actions.json 第 3 級，連結 `{NEAR_ROW_LINK}`"


@check("actions", "A12", after=("A11",))
def a12(run: Run) -> str:
    rows, _items = near_rows(run)
    bare = [row[0] for row in rows if not any(NEAR_LINE.search(line) for line in row)]
    expect(not bare, f"接近成立列沒有 `差：` 行：{'；'.join(bare)}")
    lines = sum(len(NEAR_LINE.findall(line)) for row in rows for line in row)
    return f"{len(rows)} 列各有 `差：`，共 {lines} 行"


@check("actions", "A13", after=("A11",))
def a13(run: Run) -> str:
    rows, items = near_rows(run)
    # The row's own close is the only price a near row shows (DESIGN_SYSTEM §7).
    closes = {
        f"{item['current_price']:,.2f}"
        for item in items
        if isinstance(item.get("current_price"), (int, float))
    }
    found = []
    for row in rows:
        for line in row:
            for number in PRICE_NUMBER.findall(NOT_PRICE.sub("", line)):
                if number not in closes:
                    found.append(f"{number}（{line}）")
    expect(not found, f"接近成立列有收盤以外的價格：{'；'.join(found)}")
    return f"{len(rows)} 列除了最近收盤沒有價格（收盤 {'、'.join(sorted(closes))}）"


# User tracking plans (#253): copy of frontend/src/tracking/tracking.ts.
TRACKING_TITLE, HISTORY_TITLE = "追蹤計畫", "追蹤回看"
EMPTY_OPEN_PLANS = "尚未建立追蹤計畫。可從今日候選或個股研究條件加入。"
EMPTY_CLOSED_PLANS = "尚無已結束的計畫。"
TRACKING_NOTE_START = "計畫價位來自建立當日的研究條件"
CONFLICT_NOTE = "行情有更正，狀態待核對"
HISTORY_SUMMARY = "版本、來源與逐日明細"
PLAN_STATUS_LABELS = {
    "pending": "待觸發",
    "triggered": "已觸發",
    "target_hit": "達標",
    "invalidated": "失效",
    "incomparable": "無法比較",
    "expired": "到期",
    "closed": "期滿結算",
    "not_entered": "未進場",
    "cancelled": "已取消",
}
SESSION_STATUS_LABELS = {
    "not_triggered": "未觸發",
    "active": "已模擬成交",
    "target_1_hit": "達標",
    "invalidated": "失效",
    "ambiguous": "順序不明",
    "suspended": "停牌",
    "not_entered": "未進場",
}
PLAN_DATE_LINE = re.compile(r"^計畫資料日 (\S+) · 建立 (\S+)$")
BADGE_DATE_LINE = re.compile(r"^資料 [0-9]{4}/[0-9]{2}/[0-9]{2}$")
HISTORY_ROW = re.compile(r"^([0-9]{4}/[0-9]{2}/[0-9]{2})\t第 ([0-9]+) 日\t([^\t]+)")


def plans(run: Run) -> tuple[list[dict], list[dict]]:
    """The first page of open and of ended plans, as the actions page reads them."""

    opened = run.get("tracking?status=open&page=1&page_size=20", "tracking-open.json")
    closed = run.get(
        "tracking?status=closed&page=1&page_size=20", "tracking-closed.json"
    )
    return opened.get("items") or [], closed.get("items") or []


def signed_return(value: float) -> str:
    """``formatSignedReturn``: 0.0123 -> ``+1.23%``, no negative zero."""

    percent = f"{value * 100:.2f}"
    return (
        ("+" if value > 0 else "") + ("0.00" if percent == "-0.00" else percent) + "%"
    )


def plan_cards(text: Text) -> list[int]:
    """The `計畫資料日` line of every plan card, in page order."""

    return [i for i, line in enumerate(text.lines) if PLAN_DATE_LINE.match(line)]


def card_body(text: Text, card: int) -> list[str]:
    """A card's lines after its `計畫資料日` line, up to its details summary."""

    end = text.find(HISTORY_SUMMARY, card)
    return text.lines[card + 1 : end if end >= 0 else len(text.lines)]


@check("actions", "A14")
def a14(run: Run) -> str:
    text, (opened, closed) = run.text(ACTIONS), plans(run)
    for line in (TRACKING_TITLE, HISTORY_TITLE):
        expect(text.has(line), f"缺整行 `{line}`")
    facts = run.facts()
    for items, fact, empty in (
        (opened, "tracking_plans_open", EMPTY_OPEN_PLANS),
        (closed, "tracking_plans_closed", EMPTY_CLOSED_PLANS),
    ):
        if not items:
            # #251: an empty section passes only when the DB has no such plan either.
            expect(
                not facts.get(fact),
                f"API 沒有計畫，但 DB {fact} 有 {facts.get(fact)} 筆",
            )
            expect(text.has(empty), f"API 沒有計畫，缺 `{empty}`")
    items, cards = opened + closed, plan_cards(text)
    expect(
        len(cards) == len(items),
        f"`計畫資料日` {len(cards)} 行，進行中 {len(opened)}＋已結束 {len(closed)} 筆",
    )
    problems = []
    for item, card in zip(items, cards):
        got = PLAN_DATE_LINE.match(text.lines[card]).groups()
        want = (
            slash(item.get("plan_date") or ""),
            slash(taipei_day(item.get("created_at")) or "待核實"),
        )
        if got != want:
            problems.append(
                f"計畫 {item.get('id')} 為 {got}，預期 {want}（{text.at(card)}）"
            )
    expect(not problems, "；".join(problems))
    return f"進行中 {len(opened)}＋已結束 {len(closed)} 張卡，計畫資料日與建立日 = API"


@check("actions", "A15", after=("A14",))
def a15(run: Run) -> str:
    text, (opened, closed) = run.text(ACTIONS), plans(run)
    items, cards = opened + closed, plan_cards(text)
    expect(
        len(cards) == len(items), f"`計畫資料日` {len(cards)} 行，計畫 {len(items)} 筆"
    )
    problems = []
    for item, card in zip(items, cards):
        name = f"計畫 {item.get('id')}"
        badge = next(
            (i for i in range(card - 1, 0, -1) if BADGE_DATE_LINE.match(text.lines[i])),
            -1,
        )
        status = text.lines[badge - 1] if badge > 0 else None
        want = PLAN_STATUS_LABELS.get(item.get("status"), "狀態待核實")
        if status != want:
            problems.append(
                f"{name} 狀態標籤 {status!r}，預期 `{want}`（{text.at(card)}）"
            )
        conflict = CONFLICT_NOTE in text.lines[badge + 1 : card]
        if conflict != (item.get("data_quality") == "transition_conflict"):
            problems.append(
                f"{name} data_quality {item.get('data_quality')}，`{CONFLICT_NOTE}` {'有' if conflict else '沒有'}"
            )
        body = card_body(text, card)
        results = [line for line in body if line.startswith("模擬報酬")]
        if item.get("open"):
            if results:
                problems.append(f"{name} 進行中卻有 {results}")
        elif (
            item.get("result_comparable") is True
            and item.get("result_return") is not None
        ):
            line = f"模擬報酬 {signed_return(item['result_return'])}"
            if line not in body:
                problems.append(f"{name} 缺整行 `{line}`，實際 {results}")
        elif not any(line.startswith("模擬報酬：無法比較") for line in results):
            problems.append(
                f"{name} 已結束不可比較，缺 `模擬報酬：無法比較`，實際 {results}"
            )
    rate = [
        text.at(i)
        for i, line in enumerate(text.lines)
        if "勝率" in line and not line.startswith(TRACKING_NOTE_START)
    ]
    if rate:
        problems.append(f"出現 `勝率`：{'、'.join(rate)}")
    expect(not problems, "；".join(problems))
    return (
        f"{len(opened) + len(closed)} 張卡的狀態、更正標示與模擬報酬 = API；沒有 `勝率`"
    )


@check("actions", "A16")
def a16(run: Run) -> str:
    text = run.text(ACTIONS)
    heads = {
        line: text.find(line) for line in ("我的庫存", TRACKING_TITLE, HISTORY_TITLE)
    }
    missing = [line for line, i in heads.items() if i < 0]
    expect(not missing, f"缺整行 {missing}")
    stock, plan, history = heads.values()
    expect(
        stock < plan < history,
        f"行序 我的庫存 {stock}、追蹤計畫 {plan}、追蹤回看 {history}",
    )
    # The action list starts at its first tier heading (A3) and sits between the plans in
    # progress and the ended ones (#637); without a tier heading there is no list to place.
    first_action = text.find_where(lambda line: re.fullmatch(r"第 \d 級", line))
    end = first_action if first_action >= 0 else history
    expect(
        plan < end <= history,
        f"行動列表（{text.at(first_action)}）不在 `追蹤計畫` 與 `追蹤回看` 之間",
    )
    problems = [
        f"`記錄來源` 在庫存區外（{text.at(i)}）"
        for i, line in enumerate(text.lines)
        if line.startswith("記錄來源 ") and not stock < i < plan
    ] + [
        f"`{line[:4]}` 在追蹤區外（{text.at(i)}）"
        for i, line in enumerate(text.lines)
        if line.startswith(("模擬成交", "模擬出場", "模擬報酬"))
        and not (plan < i < end or i > history)
    ]
    expect(not problems, "；".join(problems))
    return "我的庫存 < 追蹤計畫 < 行動列表 < 追蹤回看；庫存與模擬的行各在自己的區塊"


@check("actions", "A17", after=("A14",))
def a17(run: Run) -> str:
    text, (opened, closed) = run.text(ACTIONS), plans(run)
    items, cards = opened + closed, plan_cards(text)
    expect(
        len(cards) == len(items), f"`計畫資料日` {len(cards)} 行，計畫 {len(items)} 筆"
    )
    rows_of: list[list[tuple[str, str, str]]] = []
    for n, card in enumerate(cards):
        end = cards[n + 1] if n + 1 < len(cards) else len(text.lines)
        rows_of.append(
            [
                m.groups()
                for line in text.lines[card:end]
                if (m := HISTORY_ROW.match(line))
            ]
        )
    problems = [
        f"計畫 {item.get('id')} 明細 {len(rows)} 列，sessions_observed {item.get('sessions_observed')}"
        for item, rows in zip(items, rows_of)
        if len(rows) != item.get("sessions_observed")
    ]
    expect(not problems, "；".join(problems))
    total = sum(len(rows) for rows in rows_of)
    if not closed:
        return f"{total} 列明細 = 各卡 sessions_observed；沒有已結束的計畫，不取 tracking-plan.json"
    plan_id = closed[0].get("id")
    detail = run.get(f"tracking/plans/{plan_id}", "tracking-plan.json")
    sessions = detail.get("sessions") or []
    want = [
        (
            slash(session["session_date"]),
            str(session["session_no"]),
            SESSION_STATUS_LABELS.get(session["status"], "狀態待核實"),
        )
        for session in sessions
    ]
    got = rows_of[len(opened)]
    expect(got == want, f"計畫 {plan_id} 明細 {got}，預期 {want}")
    last = (detail.get("plan") or {}).get("last_session_date")
    expect(
        not sessions or sessions[-1]["session_date"] == last,
        f"最後一列 {sessions[-1]['session_date'] if sessions else None}，last_session_date {last}",
    )
    return f"{total} 列明細 = 各卡 sessions_observed；計畫 {plan_id} 的 {len(want)} 列 = tracking-plan.json"


def watch_title(text: Text) -> int:
    """The page title line: 我的追蹤 right after its eyebrow (the navbar also has a 我的追蹤 link)."""

    i = text.find(WATCH_EYEBROW)
    return i + 1 if i >= 0 and text.after(i) == WATCH_TITLE else -1


@check("actions", "A18")
def a18(run: Run) -> str:
    """#493: /watch is 我的追蹤, and the old /actions redirects there with its query and anchor.

    The page text alone cannot tell a redirect from /actions rendering the page in place, so
    the URL the browser ended on (screenshot.cjs `finalUrl`) must be /watch.
    """

    pages = (("`/watch`", run.text(ACTIONS)), ("`/actions`", run.text(ACTIONS_LEGACY)))
    for where, text in pages:
        expect(not text.has("找不到此頁。"), f"{where} 是找不到此頁")
        i = watch_title(text)
        expect(i >= 0, f"{where} 缺 `{WATCH_EYEBROW}` 之後整行 `{WATCH_TITLE}`")
    final = (run.shoot(ACTIONS_LEGACY).get(1280) or {}).get("finalUrl")
    expect(bool(final), f"`{ACTIONS_LEGACY.path}` 的截圖結果沒有 finalUrl")
    landed = urllib.parse.urlsplit(final)
    want = f"/watch?{LEGACY_QUERY}#{LEGACY_ANCHOR}"
    got = (
        landed.path
        + (f"?{landed.query}" if landed.query else "")
        + (f"#{landed.fragment}" if landed.fragment else "")
    )
    expect(got == want, f"`{ACTIONS_LEGACY.path}` 落在 `{got}`，預期 `{want}`")
    return f"`/watch` 是 `{WATCH_TITLE}`；`{ACTIONS_LEGACY.path}` 轉到 `{got}`"


# ---- manual checks: samples picked by fixed rules, judged by an agent ----
#
# Each features check labeled 人工 has a sampler here (registry_problems enforces
# it), so the sample is fixed by code before anyone looks at the pages (#251).

Sampler = Callable[[Run], dict]
MANUAL: dict[str, dict[str, Sampler]] = {page: {} for page in PAGES}
NEWS_SAMPLE = 5
NEWS_PAGES = 5  # pages of 100 news searched for D
CANDIDATE_SAMPLE = 3


def manual(page: str, *codes: str):
    def register(fn: Sampler) -> Sampler:
        for code in codes:
            MANUAL[page][code] = fn
        return fn

    return register


def taipei_day(value: Any) -> str | None:
    """The Taipei date of an API instant; one without a zone is UTC (features/news.md 陷阱)."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TAIPEI).date().isoformat()


@manual("news", "N7", "N8")
def news_sample(run: Run) -> dict:
    d = run.D()
    picked, cursor = [], ""
    # Newest first: page back until D's news are passed (a run days after D starts later).
    for page in range(1, NEWS_PAGES + 1):
        path = "news?category=domestic&limit=100" + (
            f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""
        )
        listed = run.get(path, f"news-domestic-100-{page}.json")
        rows = listed.get("items") or []
        picked += [
            item
            for item in rows
            if usable_ai(item.get("ai")) and taipei_day(item.get("published_at")) == d
        ]
        meta = listed.get("meta") or {}
        older = any((taipei_day(item.get("published_at")) or d) < d for item in rows)
        if len(picked) >= NEWS_SAMPLE or older or not meta.get("has_more"):
            break
        cursor = meta.get("next_cursor") or ""
    picked = picked[:NEWS_SAMPLE]
    items = []
    for item in picked:
        detail = run.get(f"news/{item['id']}", f"news-{item['id']}.json")
        items.append(
            {
                key: detail.get(key)
                for key in (
                    "id",
                    "title",
                    "source",
                    "published_at",
                    "summary",
                    "description",
                    "instruments",
                    "themes",
                    "ai",
                )
            }
        )
    return {
        "rule": f"/news?category=domestic&limit=100（依 next_cursor 往後最多 {NEWS_PAGES} 頁）中台北發布日 = D（{d}）且有 AI 判讀的前 {NEWS_SAMPLE} 則，API 順序",
        "items": items,
    }


@manual("today", "T10")
def candidate_sample(run: Run) -> dict:
    payload = candidates(run)
    return {
        "rule": f"candidates.json 依名次前 {CANDIDATE_SAMPLE} 檔",
        "trading_date": payload.get("trading_date"),
        "items": [
            {
                key: item.get(key)
                for key in ("rank", "instrument", "strategy", "levels", "llm_note")
            }
            for item in (payload.get("items") or [])[:CANDIDATE_SAMPLE]
        ],
    }


def write_samples(run: Run, pages: list[str]) -> list[tuple[str, str, str]]:
    """(page, code, note) per manual check; the samples go to <out>/manual/<code>.json."""

    folder = run.out / "manual"
    folder.mkdir(parents=True, exist_ok=True)
    rows, taken = [], {}
    for page in pages:
        for code, sampler in MANUAL[page].items():
            if sampler not in taken:
                try:
                    taken[sampler] = sampler(run)
                except CheckError as error:
                    taken[sampler] = {"error": str(error), "items": []}
            sample = taken[sampler]
            (folder / f"{code}.json").write_text(
                json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            count = len(sample["items"])
            note = sample.get("error") or (
                f"{count} 筆，`manual/{code}.json`" if count else "樣本 0 筆：無法判定"
            )
            rows.append((page, code, note))
    return rows


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
        except CheckError as error:
            problems.append(str(error))
            continue
        got = fixture.actual_for(payload, json_path, want)
        if got != want:
            problems.append(f"/api/{path} {json_path}：預期 {want!r}，實際 {got!r}")
    expect(not problems, "；".join(problems))
    return f"{len(fixture.EXPECTED[page])} 項 = fixture_data.EXPECTED"


# ---- driver ----


def run_order(page: str) -> list[str]:
    """The page's codes with its owners and ``after`` targets first, so their results exist when used."""

    codes = list(CHECKS[page])
    first = {code for owner_page, code in OWNERS.values() if owner_page == page}
    first |= {up for (p, _), ups in AFTER.items() if p == page for up in ups}
    return sorted(codes, key=lambda code: (code not in first, codes.index(code)))


def judge(run: Run, page: str, code: str, stock: Stock | None, label: str) -> Result:
    """Run one check; a failure after an upstream that did not pass is 無法判定（上游 X）."""

    fn, upstream, environment = CHECKS[page][code], None, False
    try:
        if stock is None and code in NEEDS_STOCK:
            run.stock()  # raises why no E/S was picked
        detail = fn(run, stock) if page == "stocks" else fn(run)
        state = PASS
    except Fail as error:
        detail, state = str(error), FAIL
    except Undetermined as error:
        detail, state = str(error), UNDETERMINED
        upstream = getattr(error, "upstream", None)
        environment = isinstance(error, Environment)
    subject = stock.label if stock else ""
    for up in AFTER.get((page, code), ()) if state == FAIL else ():
        owner = run.done.get((page, up, subject)) or run.done.get((page, up, ""))
        if owner is not None and owner.state != PASS:
            upstream = owner.upstream or up
            detail, state = str(Upstream(upstream, detail)), UNDETERMINED
            break
    known, issue = KNOWN_FAILURES.get((page, code)), None
    if known and known.expired(run.now):
        if state == FAIL:
            detail += f"（已知失敗 {known.issue} 已於 {known.expires} 到期）"
        else:
            detail += f"；KNOWN_FAILURES 的 {page} {code} 已到期，移除"
        known = None
    if known and state == FAIL and known.match in detail:
        issue = known.issue
    elif known and state == PASS:
        issue = known.issue
        detail += f"；修好了就從 KNOWN_FAILURES 移除 {page} {code}"
    elif known and state == FAIL:
        detail += f"（不是已知失敗 {known.issue}：訊息沒有 `{known.match}`）"
    result = Result(page, code, state, detail, label, issue, upstream, environment)
    run.done[(page, code, subject)] = result
    return result


def run_page(run: Run, page: str, stocks: list[Stock]) -> list[Result]:
    results = []
    for code in run_order(page):
        subjects: list[Stock | None] = [None]
        if page == "stocks":
            subjects = (list(stocks) if code in PER_STOCK else list(stocks[:1])) or [
                None
            ]
        for stock in subjects:
            label = (
                stock.label if stock and code in PER_STOCK and len(stocks) > 1 else ""
            )
            results.append(judge(run, page, code, stock, label))
    order = list(CHECKS[page])
    return sorted(results, key=lambda r: order.index(r.code))


def stocks_for(run: Run, fixture) -> list[Stock]:
    try:
        stocks = [run.stock()]
    except CheckError:
        return []  # judge reports why on every stocks check that needs E/S
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
    run.retake(list(shots.values()))


def default_jobs(jobs: int | None, fixture: bool) -> int:
    """``--jobs`` as given, else FIXTURE_JOBS on the fixture database and REAL_JOBS on real data (#609)."""

    return jobs or (FIXTURE_JOBS if fixture else REAL_JOBS)


def blocking(results: list[Result], fixture: bool) -> list[Result]:
    """The results that fail the run; on the fixture database every value exists, so 無法判定 too."""

    return [r for r in results if r.failed or (fixture and r.undetermined)]


def verdict(rows: list[Result]) -> str:
    """A page: 失敗 when a check failed, else 無法判定 when one was, else 通過."""

    if any(r.failed for r in rows):
        return FAIL
    if any(r.undetermined for r in rows):
        return UNDETERMINED
    return "失敗（已知）" if any(r.known for r in rows) else PASS


ENV_URL_ROWS = 20


def environment_markdown(env: dict) -> list[str]:
    """The summary's environment section (#609); nothing when the API never answered 5xx."""

    if not env or not env.get("hits"):
        return []
    rechecked = env["rechecked"]
    ok = [path for path, status in rechecked.items() if status == 200]
    recovered = env["recovered"]
    lines = [
        f"### 環境：API 5xx／逾時 {env['hits']} 次"
        f"（截圖 {env['screenshot_hits']}、API 呼叫 {env['api_hits']}；截圖並行 {env['jobs']}）",
        "",
        f"- 重截 {len(env['retaken'])} 張（串列、各一次），恢復 {len(recovered)} 張"
        + (f"：{'、'.join(recovered)}" if recovered else ""),
        f"- 重截後仍 5xx 的 URL {len(rechecked)} 個：直接 GET 回 200 的 {len(ok)} 個"
        f"（記無法判定（環境）），仍非 200 的 {len(rechecked) - len(ok)} 個（照舊判失敗）",
        "- 無法判定（環境）的檢查："
        + ("、".join(f"`{check}`" for check in env["checks"]) or "無"),
        *(
            f"- 重截後恢復的 `{name}` 第一次截圖另有：{'；'.join(problems)}"
            for name, problems in env.get("replaced_problems", {}).items()
        ),
        "",
        "| URL | 狀態 | 次數 |",
        "| --- | --- | --- |",
    ]
    for row in env["urls"][:ENV_URL_ROWS]:
        status = row["status"] or "逾時／連線失敗"
        path = row["path"].replace("|", "%7C")
        lines.append(f"| `/api/{path}` | {status} | {row['count']} |")
    if len(env["urls"]) > ENV_URL_ROWS:
        lines.append(f"| 另 {len(env['urls']) - ENV_URL_ROWS} 個 | | |")
    return lines + [""]


def summary_markdown(
    results: list[Result],
    pages: list[str],
    head: str,
    evidence: bool = True,
    samples: list[tuple[str, str, str]] = (),
    environment: dict | None = None,
) -> str:
    """Per page tables; without ``evidence`` only each check's result (no page text)."""

    lines = [head, "", *environment_markdown(environment or {})]
    names = {
        "today": "今日名單 `/`",
        "news": "新聞 `/news`",
        "themes": "族群 `/themes`",
        "stocks": "個股 `/stocks`",
        "actions": "我的追蹤 `/watch`",
    }
    if samples:
        lines += [
            "### 人工檢查樣本（依 features 規則抽樣，判讀見 SKILL 真資料模式第 3 步）",
            "",
            "| 檢查 | 樣本 |",
            "| --- | --- |",
        ]
        lines += [f"| {code} | {note.replace('|', '/')} |" for _, code, note in samples]
        lines.append("")
    for page in pages:
        rows = [r for r in results if r.page == page]
        lines += [f"### {names[page]}：{verdict(rows)}", ""]
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
    parser.add_argument(
        "--jobs",
        type=int,
        help=f"screenshots taken at once; default {FIXTURE_JOBS} with --fixture, else {REAL_JOBS}",
    )
    parser.add_argument(
        "--g7",
        action="store_true",
        help="refuse unless HEAD is the committed tip of G7_REF (G7 evidence)",
    )
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
    problems = g7_problems() if args.g7 else []
    if problems:
        print("--g7：" + "；".join(problems), file=sys.stderr)
        return 2

    started = time.monotonic()
    run = Run(args.api, args.web, args.db, args.out, args.browser)
    run.env_checks = not args.fixture
    fixture = fixture_module() if args.fixture else None
    stocks = stocks_for(run, fixture)
    jobs = default_jobs(args.jobs, args.fixture)
    prefetch(run, pages, stocks, jobs)
    print(f"screenshots: {time.monotonic() - started:.1f} s", file=sys.stderr)
    results: list[Result] = []
    for page in pages:
        page_started = time.monotonic()
        if fixture is not None:
            try:
                detail, state = expected_check(run, fixture, page), PASS
            except Fail as error:
                detail, state = str(error), FAIL
            results.append(Result(page, "API", state, detail))
        results += run_page(run, page, stocks)
        for r in (r for r in results if r.page == page):
            print(
                f"{page} {r.label} {r.status} {r.detail}"
                + (f"（已知：{r.known}）" if r.known else "")
            )
        print(f"{page}: {time.monotonic() - page_started:.1f} s", file=sys.stderr)
    samples = write_samples(run, pages)

    failed = blocking(results, fixture is not None)
    undetermined = sum(r.undetermined for r in results)
    picked = f"{stocks[0].label}，{run.picked}" if stocks else run.picked or "未選"
    head = (
        f"## verify 檢查結果（{run.now:%Y-%m-%d %H:%M} 台北）\n\n"
        f"- 程式：{program()}\n"
        f"- API `{args.api}`、前端 `{args.web}`、DB `{args.db.name}`"
        f"{'（假資料庫）' if fixture else ''}\n"
        f"- 個股 E／S：{picked}\n"
        f"- 截圖並行 {jobs}{'' if args.jobs else '（預設）'}\n"
        f"- {len(results)} 項：通過 {sum(r.state == PASS and not r.known for r in results)}、"
        f"失敗 {sum(r.failed for r in results)}、無法判定 {undetermined}、"
        f"已知失敗 {sum(r.state == FAIL and bool(r.known) for r in results)}；"
        f"耗時 {time.monotonic() - started:.0f} 秒"
    )
    env = run.environment(jobs, results)
    (args.out / "environment.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "summary.md").write_text(
        summary_markdown(results, pages, head, samples=samples, environment=env),
        encoding="utf-8",
    )
    (args.out / "status.md").write_text(
        summary_markdown(
            results, pages, head, evidence=False, samples=samples, environment=env
        ),
        encoding="utf-8",
    )
    (args.out / "results.json").write_text(
        json.dumps(
            [
                {
                    "page": r.page,
                    "code": r.code,
                    "subject": r.subject,
                    "state": r.state,
                    "status": r.status,
                    "failed": r.failed,
                    "detail": r.detail,
                    "known": r.known,
                    "upstream": r.upstream,
                    "environment": r.environment,
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
        + (": " + ", ".join(f"{r.page} {r.label}" for r in failed) if failed else "")
        + f", {undetermined} undetermined"
        + (
            f", {env['hits']} API 5xx/timeouts (environment.json)"
            if env["hits"]
            else ""
        ),
    )
    return 1 if failed else 0


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=check
    )


def dirty_files() -> list[str]:
    return [line[3:] for line in git("status", "--porcelain").stdout.splitlines()]


def program() -> str:
    """The branch and commit that ran, and the uncommitted files if any."""

    try:
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        head = git("rev-parse", "--short", "HEAD").stdout.strip()
        dirty = dirty_files()
    except (OSError, subprocess.CalledProcessError):
        return "未知（git 不可用）"
    state = f"未 commit：{'、'.join(dirty)}" if dirty else "工作樹乾淨"
    return f"`{branch}` @ `{head}`（{state}）"


def g7_problems() -> list[str]:
    """Why this checkout cannot give G7 evidence: it must be the committed program the
    schedule runs, the tip of the release branch (#251, #288)."""

    try:
        dirty = dirty_files()
        head = git("rev-parse", "HEAD").stdout.strip()
        release = git("rev-parse", "--verify", "--quiet", G7_REF, check=False)
    except (OSError, subprocess.CalledProcessError) as error:
        return [f"git 不可用：{error}"]
    problems = []
    if dirty:
        problems.append(f"工作樹有未 commit 的檔：{'、'.join(dirty)}")
    tip = release.stdout.strip()
    if head != tip:
        problems.append(
            f"HEAD {head[:7]} 不是 {G7_REF}（{tip[:7] or '不存在'}）："
            f"先 git fetch origin {G7_REF.removeprefix('origin/')}，從它建 worktree"
        )
    return problems


if __name__ == "__main__":
    sys.exit(main())
