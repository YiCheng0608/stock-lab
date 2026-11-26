"""The month's review: every monthly entry in one command (#1062, #1004 1／2).

docs/spec/evidence.md 每月檢討: on the first trading day of a month the
coordinator runs this on a copy and gets, for the month before,

- each object's numbers as its own entry writes them: H1 forward
  (``portfolio_research.py --hypothesis H1 --window forward``), every key of
  ``forward_watch.WATCHES`` (read from it, so a row added there runs here),
  the candidates' scorecard, the feature evidence, the candidate pool's
  sources (``candidate_pool_score.py``), the month's wrong pre-market AI
  calls (``premarket_errors.py``, the cases ``prompt_proposal.py`` reads) and
  the pre-market AI scores' monthly report
  (``worker.premarket_score_report.render``, the code of ``worker.cli
  premarket-score-report``, on the copy);
- two lists, 變差 and 變強, by the rules frozen here (``worse``, ``better``)
  before the first real run.  The lists only list: a product or delisting
  decision is the user's, a 變強 feature only a candidate for a next round.

The entries are run as they are, each as its own command in a child process
(``subprocess_runner``), their definitions, versions and ``definitions_sha256``
untouched: an entry's own refusal (a frozen check, the daily window) is that
entry's failure, the others still run, and the command ends non-zero.  Every
entry's raw output goes to ``<out>/<name>/`` as it would alone; the review
writes ``summary.md`` and ``review.json``, the machine-readable half the next
month's ``--previous`` reads.  The whole ``<out>`` goes to pr-assets/699's
``run-<YYYYMMDD>/``, nowhere else (#1062 決定 7200751860).

``--month`` is a cutoff: the copy's last session on or before the month's
last day is every entry's ``--cutoff``／``--end``, so a copy taken on the 2nd
still reports the month.  Read only, and refused as forward_watch is (the
production database, Taipei 21:30～23:30, too little free memory) before any
entry runs.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402
import feature_evidence as fe  # noqa: E402
import forward_watch as fw  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 2
DESIGN = "1062"
# What each VERSION changed in the lists (研究規則第 3 條)
VERSION_NOTES = {
    1: "#1062：前瞻對象、H1、今日名單、特徵與條件",
    2: "#1069：加候選池的 16 個來源（任一期間「輸給基準」進變差、「通過」進變強，"
    "只當紀錄）；新增「候選池的對答案」「早盤 AI 判錯清單」兩段，判錯清單不進清單",
}
# review.json's layout; a --previous of another layout is refused, not read
REVIEW_FORMAT = 1
HERE = Path(__file__).resolve().parent
H1 = "H1"
SCORECARD = "candidate_scorecard"
FEATURES = "feature_evidence"
PREMARKET = "premarket_score_report"
POOL_SCORE = "candidate_pool_score"
ERRORS = "premarket_errors"
LOGS = "logs"
OK, FAILED = "ok", "failed"
TAIEX, POPULATION = pr.TAIEX, pr.POPULATION

# (stdout, stderr) of one entry run as a command: ``runner(tool, argv)``
Runner = Callable[[str, list[str]], tuple[int, str, str]]


def subprocess_runner(tool: str, argv: list[str]) -> tuple[int, str, str]:
    """``python tools/research/<tool>.py <argv>``, the command as run alone."""

    done = subprocess.run(
        [sys.executable, str(HERE / f"{tool}.py"), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done.returncode, done.stdout, done.stderr


# --- the month ---------------------------------------------------------------


def month_problem(month: str) -> str | None:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        return "--month 要是 YYYY-MM"
    return None


def month_bounds(month: str) -> tuple[date, date]:
    year, number = (int(part) for part in month.split("-", 1))
    return date(year, number, 1), date(
        year, number, calendar.monthrange(year, number)[1]
    )


def month_cutoff(db: Path, month: str) -> date | None:
    """The copy's last market session in ``month`` (None: it has none)."""

    first, last = month_bounds(month)
    con = lib.connect_read_only(db)
    try:
        sessions = lib.research_report().market_sessions(con, first, last)
    finally:
        con.close()
    return sessions[-1] if sessions else None


# --- the entries --------------------------------------------------------------


def steps(db: Path, out: Path, cutoff: date, min_free_gb: float) -> list[dict]:
    """Every entry in the order run: H1, the ``WATCHES`` keys, the scorecard,
    the feature evidence, the pool's sources, the AI's misses, then the
    pre-market report (no tool: in process).  ``tables`` is the file an entry
    that succeeded has written (``tables.json`` unless said)."""

    end = cutoff.isoformat()
    month = end[:7]
    memory = ["--min-free-gb", f"{min_free_gb:g}"]
    listed = [
        {
            "name": H1,
            "tool": "portfolio_research",
            "argv": ["--db", str(db), "--hypothesis", H1, "--window", pr.FORWARD]
            + ["--out", str(out / H1), "--cutoff", end, *memory],
        }
    ]
    for key in fw.WATCHES:
        listed.append(
            {
                "name": key,
                "tool": "forward_watch",
                "argv": ["--db", str(db), "--watch", key, "--out", str(out / key)]
                + ["--cutoff", end, *memory],
            }
        )
    for name in (SCORECARD, FEATURES):
        listed.append(
            {
                "name": name,
                "tool": name,
                "argv": ["--db", str(db), "--out", str(out / name), "--end", end],
            }
        )
    listed.append(
        {
            "name": POOL_SCORE,
            "tool": POOL_SCORE,
            "argv": [
                "--db",
                str(db),
                "--out",
                str(out / POOL_SCORE),
                "--end",
                end,
                *memory,
            ],
        }
    )
    listed.append(
        {
            "name": ERRORS,
            "tool": ERRORS,
            "argv": [
                "--db",
                str(db),
                "--month",
                month,
                "--out",
                str(out / ERRORS),
                *memory,
            ],
            "tables": "cases.json",
        }
    )
    listed.append({"name": PREMARKET, "tool": None, "argv": []})
    return listed


def _reason(code: int, stdout: str, stderr: str) -> str:
    """The entry's own words: its ``refused`` line, else its last error line."""

    for line in reversed(stdout.strip().splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("refused"):
            return "拒絕：" + "；".join(str(item) for item in parsed["refused"])
        if isinstance(parsed, dict) and parsed.get("stopped"):
            return "停下：" + str(parsed["stopped"])
    tail = [line for line in stderr.strip().splitlines() if line.strip()]
    return f"exit {code}" + (f"：{tail[-1].strip()}" if tail else "")


def missing_table(text: str, db: Path | None) -> str | None:
    """A copy of a database the migration has not reached yet, said plainly."""

    missing = re.search(r"no such table: (\w+)", text)
    if not missing:
        return None
    alembic = pr.copy_facts(db)["alembic"] if db is not None else "?"
    return (
        f"副本沒有 `{missing.group(1)}` 表（alembic `{alembic}`）：建它的 migration "
        "還沒部署到正式 DB"
    )


def run_tool_step(
    step: dict, out: Path, runner: Runner, db: Path | None = None
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        code, stdout, stderr = runner(step["tool"], step["argv"])
    except Exception as exc:  # noqa: BLE001 - one entry's crash is its failure only
        code, stdout, stderr = -1, "", f"{type(exc).__name__}: {exc}"
    logs = out / LOGS
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{step['name']}.stdout.txt").write_text(stdout, encoding="utf-8")
    (logs / f"{step['name']}.stderr.txt").write_text(stderr, encoding="utf-8")
    tables = out / step["name"] / step.get("tables", "tables.json")
    status = {
        "tool": step["tool"],
        "command": f"python tools/research/{step['tool']}.py " + " ".join(step["argv"]),
        "returncode": code,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    if code != 0:
        reason = missing_table(stderr, db) or _reason(code, stdout, stderr)
        return {**status, "status": FAILED, "reason": reason}
    if not tables.is_file():
        return {**status, "status": FAILED, "reason": f"exit 0 但沒有 {tables.name}"}
    return {**status, "status": OK}


def premarket_text(db: Path, month: str) -> str:
    """``worker.premarket_score_report.render`` on the copy, read only: the
    code of ``worker.cli premarket-score-report --month``, its Session on the
    copy instead of ``pipeline.SessionLocal`` (the production database)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from worker import premarket_score_report as report

    engine = create_engine("sqlite://", creator=lambda: lib.connect_read_only(db))
    try:
        with Session(engine) as session:
            return report.render(session, month)
    finally:
        engine.dispose()


def run_premarket(
    db: Path, month: str, out: Path, render: Callable[[Path, str], str]
) -> dict[str, Any]:
    started = time.monotonic()
    status: dict[str, Any] = {
        "tool": None,
        "command": f"premarket_score_report.render({month})",
    }
    try:
        text = render(db, month)
    except Exception as exc:  # noqa: BLE001 - its failure is its section's only
        reason = missing_table(str(exc), db) or f"{type(exc).__name__}: {exc}"
        return {
            **status,
            "status": FAILED,
            "reason": reason,
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }
    folder = out / PREMARKET
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.md").write_text(text + "\n", encoding="utf-8")
    return {
        **status,
        "status": OK,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }


# --- what the entries said -------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _excess(part: dict[str, Any]) -> dict[str, Any]:
    return {key: part.get(key) for key in ("days", "mean", "annual", "t")}


def forward_facts(out: Path, status: dict[str, dict]) -> dict[str, dict]:
    """H1 and every ``WATCHES`` key: the verdict and the two excesses."""

    facts: dict[str, dict] = {}
    if status[H1]["status"] == OK:
        t = _read(out / H1 / "tables.json")
        facts[H1] = {
            "code": H1,
            "kind": "H1 前瞻",
            "note": "只當紀錄，不改 H1 成立與否（H1 成立以歷史樣本外的判定為準）",
            "verdict": t["verdict"],
            "days": t["days"],
            "min_days": t["min_days"],
            "excess": {
                TAIEX: _excess(t["excess"]["all"][TAIEX]),
                # the verdict's block: the first min_days sessions forward
                POPULATION: _excess(t["excess"]["judged"][POPULATION]),
            },
        }
    for key in fw.WATCHES:
        if status[key]["status"] != OK:
            continue
        t = _read(out / key / "tables.json")
        facts[key] = {
            "code": fw.display(key),
            "kind": t["kind"],
            "note": t["note"],
            "verdict": t["verdict"],
            "days": t["days"],
            "min_days": t["min_days"],
            "first_signal": t.get("first_signal"),
            "signal_days": t.get("signal_days"),
            "next_deadline": t.get("next_deadline"),
            "excess": {
                TAIEX: _excess(t["excess"][TAIEX]),
                POPULATION: _excess(t["excess"][POPULATION]),
            },
        }
    return facts


def scorecard_facts(out: Path, status: dict[str, dict]) -> dict[str, Any] | None:
    if status[SCORECARD]["status"] != OK:
        return None
    t = _read(out / SCORECARD / "tables.json")
    horizons = {}
    for horizon, tables in t.get("horizons", {}).items():
        part = tables["all"]
        daily = part.get("daily_excess") or {"days": 0, "mean": None, "t": None}
        horizons[horizon] = {
            "candidates": part["candidates"],
            "comparable": part["comparable"],
            "pending": part["pending"],
            "days": daily["days"],
            "mean": daily["mean"],
            "t": daily["t"],
            "verdict": scorecard_verdict(daily),
        }
    return {
        "range": t["range"],
        "candidates": t["candidates"],
        "last_session": t.get("last_session"),
        "horizons": horizons,
    }


def feature_facts(out: Path, status: dict[str, dict]) -> dict[str, Any] | None:
    if status[FEATURES]["status"] != OK:
        return None
    t = _read(out / FEATURES / "tables.json")
    verdicts: dict[str, dict[str, dict[str, str]]] = {"features": {}, "conditions": {}}
    for horizon, tables in t["horizons"].items():
        for kind in verdicts:
            for key, part in tables[kind].items():
                verdicts[kind].setdefault(key, {})[horizon] = part["verdict"]
    return {"version": t["version"], "range": t["range"], "verdicts": verdicts}


def pool_facts(out: Path, status: dict[str, dict]) -> dict[str, Any] | None:
    """The pool's 16 sources: each horizon's days, excess, t and verdict."""

    if status[POOL_SCORE]["status"] != OK:
        return None
    t = _read(out / POOL_SCORE / "tables.json")
    sources: dict[str, dict[str, dict]] = {}
    for horizon, part in t["horizons"].items():
        for source in t["sources"]:
            group = part["groups"][f"source:{source}"]
            sources.setdefault(source, {})[horizon] = {
                "days": group["days"],
                "mean": group["mean"],
                "t": group["t"],
                "verdict": group["verdict"],
                "liquid_mean": group["liquid_reference"]["mean"],
            }
    return {
        "version": t["version"],
        "range": t["range"],
        "pool_days": t["pool_days"],
        "comparisons": t["comparisons"],
        "min_days": t["min_days"],
        "ai_check": {h: part["ai_check"] for h, part in t["horizons"].items()},
        "sources": sources,
    }


def error_facts(out: Path, status: dict[str, dict]) -> dict[str, Any] | None:
    if status[ERRORS]["status"] != OK:
        return None
    t = _read(out / ERRORS / "cases.json")
    return {
        "version": t["version"],
        "prompt_version": t["prompt_version"],
        "days": t["days"],
        "found": t["found"],
        "cases": len(t["cases"]),
        "proposal_gate": t["proposal_gate"],
    }


# --- the lists (docs/spec/evidence.md 每月檢討) -----------------------------------
#
# Frozen before the first real run (#1062 AC-1); a change is a new VERSION.

LOSING = "輸給基準"
PASSING = "通過"
# feature_evidence.judge's verdicts from the best down; cannot_tell has no rank
RANKS = {"evidence": 3, "weak": 2, "not_selected": 1, "reversed": 0}
UNRANKED = "cannot_tell"
BETTER_FLOOR = RANKS["weak"]  # a 變強 feature is at least 方向一致但不顯著 now
SCORECARD_MIN_DAYS = 60
SCORECARD_NOTE = "今日名單是產品：統籌在 #1 提案檢討（不是下架提案）"
POOL_NOTE = (
    "候選池只決定 AI 看哪些股票：統籌在 #1 提案調整來源或上限；改 `PoolConfig` "
    "預設值要留 `決定：`"
)


def pool_items(review: dict[str, Any], verdict: str) -> list[dict]:
    """The pool sources judged ``verdict`` on a horizon (#1069 Q5), or its
    failure: in both lists, as a failed forward object is."""

    if "pool" not in review:
        return []  # a review of the first version's shape
    pool = review["pool"]
    if pool is None:
        return [
            _item("failed", POOL_SCORE, f"{POOL_SCORE} 失敗，未判", "看該段的失敗原因")
        ]
    items = []
    for source, by in pool["sources"].items():
        for horizon, part in _by_horizon_parts(by):
            if part["verdict"] != verdict:
                continue
            items.append(
                _item(
                    "pool",
                    f"pool:{source}:T+{horizon}",
                    f"候選池來源 `{source}` T+{horizon} 判「{verdict}」：每日超額日均 "
                    f"{lib.pct(part['mean'], 3)}，t {lib.num(part['t'], 2)}，"
                    f"{part['days']} 日（比較 {pool['comparisons']} 組）",
                    POOL_NOTE if verdict == LOSING else "只當紀錄；" + POOL_NOTE,
                )
            )
    return items


def _by_horizon_parts(by: dict[str, dict]) -> list[tuple[str, dict]]:
    return sorted(by.items(), key=lambda pair: int(pair[0]))


def scorecard_verdict(daily: dict[str, Any]) -> str:
    """``forward_judge`` on the scorecard's daily excess of all candidates."""

    if daily.get("mean") is None:
        return "樣本不足"
    return pr.forward_judge(
        {"days": daily["days"], "mean": daily["mean"], "t": daily["t"]},
        SCORECARD_MIN_DAYS,
    )


def feature_tokens(value: Any) -> set[str]:
    """The ``FEATURES`` keys named in a definition (whole words of its repr)."""

    text = repr(value)
    return {key for key, *_ in fe.FEATURES if re.search(rf"\b{re.escape(key)}\b", text)}


def product_features() -> dict[str, list[str]]:
    """Feature key → the 已進產品 ``WATCHES`` keys whose definition names it."""

    used: dict[str, list[str]] = {}
    for key, entry in fw.WATCHES.items():
        if entry["kind"] != fw.PRODUCT:
            continue
        for feature in sorted(feature_tokens(fw.definition(key))):
            used.setdefault(feature, []).append(key)
    return used


def product_unmatched() -> dict[str, list[str]]:
    """The 已進產品 ``WATCHES`` keys' sort and filter keys that are no
    ``FEATURES`` key (X4's ``eps_yield_raw``): nothing to compare, said so."""

    names = {key for key, *_ in fe.FEATURES}
    out: dict[str, list[str]] = {}
    for key, entry in fw.WATCHES.items():
        if entry["kind"] != fw.PRODUCT:
            continue
        spec = fw.definition(key)
        keys = [*spec.get("keys", ()), *(part[0] for part in spec.get("filters", ()))]
        missing = sorted({name for name in keys if name not in names})
        if missing:
            out[key] = missing
    return out


def registered_features(
    ledger: Path = HERE / "explore_ledger.json",
) -> dict[str, list[str]]:
    """Feature key → the registered hypotheses whose definition names it: every
    ledger row's tool's ``HYPOTHESES[代號]``, H1 and the ``WATCHES`` objects."""

    definitions: dict[str, Any] = {}
    for row in _read(ledger)["entries"]:
        tool = row.get("tool", "explore_research")
        label = f"{tool}:{row['hypothesis']}"
        if label in definitions:
            continue
        hypotheses = getattr(lib._load(tool), "HYPOTHESES", {})
        definitions[label] = hypotheses.get(row["hypothesis"])
    for name, spec in pr.HYPOTHESES.items():
        definitions[f"portfolio_research:{name}"] = spec
    for key in fw.WATCHES:
        definitions[f"forward_watch:{key}"] = fw.definition(key)
    used: dict[str, list[str]] = {}
    for label, spec in definitions.items():
        for feature in feature_tokens(spec):
            used.setdefault(feature, []).append(label)
    return {key: sorted(labels) for key, labels in used.items()}


def _item(kind: str, name: str, text: str, action: str, **extra: Any) -> dict:
    return {"kind": kind, "name": name, "text": text, "action": action, **extra}


def _comparison(
    current: dict[str, Any] | None, previous: dict[str, Any] | None
) -> str | None:
    """Why the features cannot be compared with last month, or None."""

    if current is None:
        return "本月 feature_evidence 失敗，未判"
    if previous is None:
        return "沒有上個月可比（沒有 --previous），不列"
    before = previous.get("features")
    if before is None:
        return "上個月 feature_evidence 失敗，不比"
    if before["version"] != current["version"]:
        return f"判定規則改版（第 {before['version']} 版→第 {current['version']} 版），不比"
    return None


def _by_horizon(by: dict[str, str]) -> list[tuple[str, str]]:
    """(horizon, verdict) by the horizon's number: T+5 before T+20."""

    return sorted(by.items(), key=lambda pair: int(pair[0]))


def _changes(
    current: dict[str, Any], previous: dict[str, Any], kind: str, keys: list[str]
) -> list[tuple[str, str, str, str]]:
    """(key, horizon, last month's, this month's) for ranked verdicts that moved."""

    moved = []
    before = previous["features"]["verdicts"].get(kind, {})
    for key in keys:
        for horizon, now in _by_horizon(current["verdicts"][kind].get(key, {})):
            then = before.get(key, {}).get(horizon)
            if then is None or then == now or UNRANKED in (then, now):
                continue
            moved.append((key, horizon, then, now))
    return moved


NOT_LAST_MONTH = "上個月沒有，不比"


def _missing(
    current: dict[str, Any], previous: dict[str, Any], kind: str, keys: list[str]
) -> list[tuple[str, str]]:
    """(key, horizon) this month has and last month had not (a key or a
    horizon added without a new feature_evidence.VERSION): said, not compared."""

    before = previous["features"]["verdicts"].get(kind, {})
    return [
        (key, horizon)
        for key in keys
        for horizon, _now in _by_horizon(current["verdicts"][kind].get(key, {}))
        if before.get(key, {}).get(horizon) is None
    ]


def _missing_items(
    current: dict[str, Any], previous: dict[str, Any], kind: str, keys: list[str]
) -> list[dict]:
    return [
        _item(
            "note", f"{key}:T+{horizon}", f"`{key}` T+{horizon}：{NOT_LAST_MONTH}", "—"
        )
        for key, horizon in _missing(current, previous, kind, keys)
    ]


def feature_changes(
    current: dict[str, Any] | None, previous: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Every verdict that differs from last month's, 無法判定 included (Q1:
    those are listed here only, neither up nor down)."""

    if _comparison(current, previous):
        return []
    rows = []
    before = previous["features"]["verdicts"]
    for kind in ("conditions", "features"):
        for key, by in current["verdicts"][kind].items():
            for horizon, now in _by_horizon(by):
                then = before.get(kind, {}).get(key, {}).get(horizon)
                if then is None:
                    direction = NOT_LAST_MONTH
                elif then == now:
                    continue
                elif UNRANKED in (then, now):
                    direction = "不排序"
                else:
                    direction = "升級" if RANKS[now] > RANKS[then] else "降級"
                rows.append(
                    {
                        "kind": kind,
                        "key": key,
                        "horizon": horizon,
                        "from": then,
                        "to": now,
                        "direction": direction,
                    }
                )
    return rows


USED_NOTE = (
    "「用過」從登記的定義自動查：`explore_ledger.json` 每一筆的工具的 "
    "`HYPOTHESES[代號]`、`portfolio_research.HYPOTHESES` 與 `forward_watch.WATCHES` "
    "的定義裡出現特徵鍵（整字）就算；只用中文標籤描述、沒寫鍵名的假設比對不到，"
    "可能被誤列成沒用過，統籌看清單時刪掉"
)


def _verdict(code: str) -> str:
    return fe.VERDICTS[code]


def _forward_text(fact: dict[str, Any], verdict: str) -> str:
    """The verdict's numbers on one window: H1's verdict reads its first
    ``min_days`` sessions (``excess.judged``), so its days are those."""

    e = fact["excess"][POPULATION]
    days = f"{e['days']} 日"
    if e["days"] != fact["days"]:
        days = f"判定窗口 {e['days']} 日（至今 {fact['days']} 日）"
    return (
        f"{fact['code']}（{fact['kind']}）判「{verdict}」：對母體超額日均 "
        f"{lib.pct(e['mean'], 3)}，t {lib.num(e['t'], 2)}，{days}"
    )


def _failed_items(review: dict[str, Any]) -> list[dict]:
    """H1 or a forward object that failed: in both lists, so a 「（沒有）」
    never stands for an entry that did not run."""

    return [
        _item("failed", name, f"{name} 失敗，未判", "看該段的失敗原因")
        for name in review["failed"]
        if name in fw.WATCHES or name == H1
    ]


def worse(review: dict[str, Any], previous: dict[str, Any] | None) -> list[dict]:
    """變差: a forward object or H1 judged 輸給基準, the scorecard's list judged
    輸給基準, a live condition's or a product strategy's feature downgraded."""

    items = []
    for name, fact in review["forward"].items():
        if fact["verdict"] == LOSING:
            items.append(
                _item(
                    "forward",
                    name,
                    _forward_text(fact, LOSING),
                    fact["note"],
                )
            )
    items += _failed_items(review)
    items += pool_items(review, LOSING)
    card = review["scorecard"]
    if card is None:
        items.append(
            _item("failed", SCORECARD, f"{SCORECARD} 失敗，未判", "看該段的失敗原因")
        )
    else:
        for horizon, part in card["horizons"].items():
            if part["verdict"] == LOSING:
                items.append(
                    _item(
                        "scorecard",
                        f"{SCORECARD}:T+{horizon}",
                        f"今日名單 T+{horizon} 判「輸給基準」：每日超額日均 "
                        f"{lib.pct(part['mean'], 3)}，t {lib.num(part['t'], 2)}，"
                        f"{part['days']} 日",
                        SCORECARD_NOTE,
                    )
                )
    current = review["features"]
    why = _comparison(current, previous)
    if why:
        items.append(_item("note", FEATURES, f"特徵與條件降級：{why}", "—"))
        return items
    products = product_features()
    for kind, keys, label in (
        ("conditions", [key for key, *_ in fe.CONDITIONS], "現行規則的條件"),
        ("features", sorted(products), "已進產品策略用到的特徵"),
    ):
        for key, horizon, then, now in _changes(current, previous, kind, keys):
            if RANKS[now] >= RANKS[then]:
                continue
            whose = f"（{'、'.join(products[key])}）" if kind == "features" else ""
            items.append(
                _item(
                    kind[:-1],
                    f"{key}:T+{horizon}",
                    f"{label} `{key}`{whose} T+{horizon}：{_verdict(then)} → {_verdict(now)}",
                    "列出；採不採用由使用者決定（研究規則第 2 條）",
                )
            )
        items += _missing_items(current, previous, kind, keys)
    return items


def better(
    review: dict[str, Any],
    previous: dict[str, Any] | None,
    used: dict[str, list[str]],
) -> list[dict]:
    """變強: a forward object or H1 judged 通過 (a record only), and a feature
    upgraded to at least 方向一致但不顯著 that no registered hypothesis used."""

    items = []
    for name, fact in review["forward"].items():
        if fact["verdict"] == PASSING:
            items.append(
                _item(
                    "forward",
                    name,
                    _forward_text(fact, PASSING),
                    "只當紀錄；" + fact["note"],
                )
            )
    items += _failed_items(review)
    items += pool_items(review, PASSING)
    current = review["features"]
    why = _comparison(current, previous)
    if why:
        items.append(_item("note", FEATURES, f"特徵升級：{why}", "—"))
        return items
    keys = [key for key, *_ in fe.FEATURES]
    for key, horizon, then, now in _changes(current, previous, "features", keys):
        if RANKS[now] <= RANKS[then] or RANKS[now] < BETTER_FLOOR:
            continue
        if key in used:
            continue
        items.append(
            _item(
                "feature",
                f"{key}:T+{horizon}",
                f"特徵 `{key}` T+{horizon}：{_verdict(then)} → {_verdict(now)}，"
                "已登記的假設沒用過",
                "下一輪研究的候選，照探索、驗證兩段做；不直接進策略",
            )
        )
    items += _missing_items(current, previous, "features", keys)
    return items


# --- the report -------------------------------------------------------------------


def _list_lines(title: str, items: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        return lines + ["（沒有）", ""]
    lines += ["| 項目 | 內容 | 動作 |", "| --- | --- | --- |"]
    for item in items:
        lines.append(f"| `{item['name']}` | {item['text']} | {item['action']} |")
    return lines + [""]


def _head(path: Path, count: int) -> list[str]:
    """The first ``count`` bullet lines of an entry's summary.md."""

    lines = path.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.startswith("- ")][:count]


def _failed_lines(status: dict[str, Any]) -> list[str]:
    return [f"- **失敗**：{status['reason']}", f"- 命令：`{status['command']}`", ""]


def markdown(review: dict[str, Any], out: Path) -> str:
    status = review["steps"]
    failed = review["failed"]
    lines = [
        f"# 每月檢討 {review['month']}（monthly_review 第 {review['version']} 版，"
        f"#{review['design']}）",
        "",
        f"- cutoff：{review['cutoff']}（副本裡 {review['month']} 的最後一個交易日"
        + ("" if review["month_complete"] else "；**月份還沒結束**")
        + "）",
        f"- 副本：最新交易日 {review['copy']['latest']}，alembic "
        f"`{review['copy']['alembic']}`，檔案時間 {review['copy']['mtime']}",
        "- 上個月："
        + (
            f"{review['previous']['month']}（`{review['previous']['dir']}`）"
            if review["previous"]
            else "沒有（沒有 `--previous`）"
        ),
        f"- 子入口：{len(status)} 個，成功 {len(status) - len(failed)}、失敗 {len(failed)}"
        + (f"（{'、'.join(failed)}）" if failed else ""),
        f"- 耗時 {review['elapsed_seconds']:.0f} 秒，峰值記憶體 "
        f"{lib.num(review['peak_memory_gb'], 2)} GB",
        f"- 重現：`{review['command']}`",
        f"- 第 {review['version']} 版改了什麼：{VERSION_NOTES[review['version']]}",
        "",
    ]
    lines += _list_lines("變差", review["lists"]["worse"])
    unmatched = product_unmatched()
    if unmatched:
        lines[-1:] = [
            "",
            "- 已進產品策略用到、不在 `feature_evidence.FEATURES` 的鍵（沒得比）："
            + "；".join(
                f"{key} " + "、".join(f"`{name}`" for name in names)
                for key, names in unmatched.items()
            ),
            "",
        ]
    lines += _list_lines("變強", review["lists"]["better"])
    lines[-1:] = ["", f"- {USED_NOTE}", ""]
    lines += [f"## {H1}", ""]
    if status[H1]["status"] == OK:
        fact = review["forward"][H1]
        e = fact["excess"][TAIEX]
        lines += [
            f"- 對加權指數超額（只列出，至今全部）：日均 {lib.pct(e['mean'], 3)}，t "
            f"{lib.num(e['t'], 2)}，{e['days']} 日",
            *[line for line in _head(out / H1 / "summary.md", 1)],
            f"- 原始輸出：`{H1}/`（整個 `--out` 推 `pr-assets/699` 的 `run-<YYYYMMDD>/`）",
            "",
        ]
    else:
        lines += _failed_lines(status[H1])
    for key in fw.WATCHES:
        lines += [f"## {key}", ""]
        if status[key]["status"] != OK:
            lines += _failed_lines(status[key])
            continue
        fact = review["forward"][key]
        summary = out / key / "summary.md"
        title = summary.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
        lines += [
            f"- {title}",
            *_head(summary, 3),
            f"- 第一個有名單的訊號日：{fact['first_signal'] or '沒有名單'}",
            f"- 原始輸出：`{key}/`（`pr-assets/699` 的 `run-<YYYYMMDD>/{key}/`）",
            "",
        ]
    lines += ["## 候選成績單", ""]
    card = review["scorecard"]
    if card is None:
        lines += _failed_lines(status[SCORECARD])
    else:
        lines += [
            f"- 候選：{card['range'][0]}～{card['range'][1]}，{card['candidates']} 檔次；"
            f"判定：全部候選的每日超額，`forward_judge`，滿 {SCORECARD_MIN_DAYS} 日才判",
            "",
            "| 期間 | 候選 | 未到期 | 可比較 | 日數 | 每日超額日均 | t | 判定 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for horizon, part in card["horizons"].items():
            lines.append(
                f"| T+{horizon} | {part['candidates']} | {part['pending']} "
                f"| {part['comparable']} | {part['days']} | {lib.pct(part['mean'], 3)} "
                f"| {lib.num(part['t'], 2)} | {part['verdict']} |"
            )
        lines += ["", f"- 原始輸出：`{SCORECARD}/`", ""]
    lines += ["## 特徵證據", ""]
    current = review["features"]
    if current is None:
        lines += _failed_lines(status[FEATURES])
    else:
        lines += [
            f"- feature_evidence 第 {current['version']} 版，{current['range'][0]}"
            f"～{current['range'][1]}",
            "",
            "| 類 | 鍵 | T+5 | T+20 |",
            "| --- | --- | --- | --- |",
        ]
        for kind, label in (("conditions", "條件"), ("features", "特徵")):
            for key, by in current["verdicts"][kind].items():
                cells = [_verdict(by[h]) if h in by else "—" for h in ("5", "20")]
                lines.append(f"| {label} | `{key}` | {' | '.join(cells)} |")
        lines += ["", "### 判定有變（和上個月比）", ""]
        why = review["feature_comparison"]
        if why:
            lines.append(why)
        elif not review["feature_changes"]:
            lines.append("（沒有）")
        else:
            lines += [
                "| 類 | 鍵 | 期間 | 上個月 | 本月 | 升降 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for row in review["feature_changes"]:
                label = "條件" if row["kind"] == "conditions" else "特徵"
                lines.append(
                    f"| {label} | `{row['key']}` | T+{row['horizon']} "
                    f"| {_verdict(row['from']) if row['from'] else '—'} "
                    f"| {_verdict(row['to'])} "
                    f"| {row['direction']} |"
                )
        lines += ["", f"- 原始輸出：`{FEATURES}/`", ""]
    lines += ["## 候選池的對答案", ""]
    pool = review.get("pool")
    if pool is None:
        lines += _failed_lines(status[POOL_SCORE])
    elif not pool["range"]:
        lines += [
            "- 副本沒有 candidate_pool_v1 的池",
            "",
            f"- 原始輸出：`{POOL_SCORE}/`",
            "",
        ]
    else:
        lines += [
            f"- 池的交易日 T：{pool['range'][0]}～{pool['range'][1]}，{pool['pool_days']} 天；"
            f"每日超額對母體（同 `premarket_score_v1`），滿 {pool['min_days']} 日才判；"
            f"比較 {pool['comparisons']} 組，其中大約 1 組會純屬偶然達標",
            "- AI 組對 `overall` 的 `ai_version.excess`："
            + "；".join(
                f"T+{h} 比對 {c['compared']} 天、不同 {len(c['differ'])} 天"
                for h, c in sorted(pool["ai_check"].items(), key=lambda p: int(p[0]))
            ),
            "",
            "| 來源 | T+5 日數 | T+5 日均 | T+5 判定 | T+20 日數 | T+20 日均 | T+20 判定 |",
            "| --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
        for source, by in pool["sources"].items():
            cells = []
            for horizon in ("5", "20"):
                part = by.get(horizon)
                cells += (
                    [str(part["days"]), lib.pct(part["mean"], 3), part["verdict"]]
                    if part
                    else ["—", "—", "—"]
                )
            lines.append(f"| `{source}` | " + " | ".join(cells) + " |")
        lines += [
            "",
            f"- 另列的組（全池、層級、來源數、被上限擋掉、AI 判 keep／reprice）與對流動母體的"
            f"參考值在 `{POOL_SCORE}/summary.md`",
            "",
        ]
    lines += ["## 早盤 AI 判錯清單", ""]
    errors = review.get("errors")
    if errors is None:
        lines += _failed_lines(status[ERRORS])
    else:
        found, gate = errors["found"], errors["proposal_gate"]
        lines += [
            f"- champion `{errors['prompt_version']}`；本月判錯 {found['errors']} 筆、"
            f"判對 {found['controls']} 筆，收進 `cases.json` {errors['cases']} 筆"
            f"（不能比 {found['incomparable']}、尚未對答案 {found['pending']}）",
            f"- 提案：**{gate['text']}**（{gate['why']}）",
            "- 不進清單：換版照 premarket_ai 自己的兩個條件；提案命令 `prompt_proposal.py` "
            "另跑（每月流程）",
            f"- 原始輸出：`{ERRORS}/cases.json`、`{ERRORS}/cases.md`",
            "",
        ]
    lines += ["## 早盤 AI 判讀月報", ""]
    if status[PREMARKET]["status"] != OK:
        lines += _failed_lines(status[PREMARKET])
    else:
        text = (out / PREMARKET / "report.md").read_text(encoding="utf-8")
        lines += [
            ("#" + line) if line.startswith("#") else line
            for line in text.rstrip("\n").splitlines()
        ]
        lines += ["", f"- 原始輸出：`{PREMARKET}/report.md`", ""]
    return "\n".join(lines) + "\n"


# --- the run ---------------------------------------------------------------------


def _peak_gb() -> float | None:
    """The largest resident set of this process and of its children (the
    entries); this process's alone where ``resource`` is missing (Windows)."""

    own = lib._load("backtest_research").peak_memory_gb()
    try:
        import resource
    except ImportError:
        return own
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # ru_maxrss is KiB on Linux, bytes on macOS
    children_gb = children / (1024**3 if sys.platform == "darwin" else 1024**2)
    return max(own or 0.0, children_gb)


def read_previous(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = folder / "review.json"
    if not path.is_file():
        return None, f"--previous {folder} 沒有 review.json"
    try:
        previous = _read(path)
    except ValueError as exc:
        return None, f"{path} 讀不了：{exc}"
    if previous.get("format") != REVIEW_FORMAT:
        return None, (
            f"{path} 的格式版本是 {previous.get('format')}，本入口讀 {REVIEW_FORMAT}"
        )
    return previous, None


def run_review(
    db: Path,
    month: str,
    out: Path,
    cutoff: date,
    previous: dict[str, Any] | None = None,
    previous_dir: Path | None = None,
    min_free_gb: float = 2.0,
    command: str = "",
    runner: Runner = subprocess_runner,
    premarket: Callable[[Path, str], str] = premarket_text,
) -> dict[str, Any]:
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    status: dict[str, dict] = {}
    for step in steps(db, out, cutoff, min_free_gb):
        if step["tool"] is None:
            status[step["name"]] = run_premarket(db, month, out, premarket)
        else:
            status[step["name"]] = run_tool_step(step, out, runner, db)
    _first, last_day = month_bounds(month)
    copy = pr.copy_facts(db)
    review: dict[str, Any] = {
        "format": REVIEW_FORMAT,
        "version": VERSION,
        "design": DESIGN,
        "month": month,
        "cutoff": cutoff.isoformat(),
        "month_complete": bool(copy["latest"])
        and copy["latest"] >= last_day.isoformat(),
        "copy": copy,
        "previous": (
            {"month": previous["month"], "dir": str(previous_dir)} if previous else None
        ),
        "command": command,
        "tool_commit": er.tool_commit(),
        "steps": status,
        "failed": [name for name, part in status.items() if part["status"] != OK],
        "forward": forward_facts(out, status),
        "scorecard": scorecard_facts(out, status),
        "features": feature_facts(out, status),
        "pool": pool_facts(out, status),
        "errors": error_facts(out, status),
    }
    review["feature_comparison"] = _comparison(review["features"], previous)
    review["feature_changes"] = feature_changes(review["features"], previous)
    review["lists"] = {
        "worse": worse(review, previous),
        "better": better(review, previous, registered_features()),
    }
    review["elapsed_seconds"] = time.monotonic() - started
    review["peak_memory_gb"] = _peak_gb()
    (out / "review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(markdown(review, out), encoding="utf-8")
    return review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monthly_review.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--previous", default=None, help="last month's --out (its review.json)"
    )
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def refusals(db: Path, month: str, min_free_gb: float) -> list[str]:
    problems = lib._load("exit_research").refusals(db, min_free_gb)
    if problems:
        return problems
    if month_cutoff(db, month) is None:
        return [f"副本在 {month} 沒有交易日"]
    return []


def main(
    argv: list[str] | None = None,
    runner: Runner = subprocess_runner,
    premarket: Callable[[Path, str], str] = premarket_text,
) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    problem = month_problem(args.month)
    if problem:
        parser.error(problem)
    db = Path(args.db)
    problems = refusals(db, args.month, args.min_free_gb)
    previous = None
    if args.previous and not problems:
        previous, problem = read_previous(Path(args.previous))
        if problem:
            problems.append(problem)
        elif previous["month"] >= args.month:
            problems.append(
                f"--previous 的月份 {previous['month']} 不在 {args.month} 之前"
            )
    out = Path(args.out)
    if not problems and out.exists() and any(out.iterdir()):
        # a failed entry would leave last time's files there, pushed with the rest
        problems.append(f"--out {out} 不是空的：每次用新的空目錄")
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    cutoff = month_cutoff(db, args.month)
    review = run_review(
        db,
        args.month,
        Path(args.out),
        cutoff,
        previous=previous,
        previous_dir=Path(args.previous) if args.previous else None,
        min_free_gb=args.min_free_gb,
        command="python tools/research/monthly_review.py " + " ".join(argv),
        runner=runner,
        premarket=premarket,
    )
    print(
        json.dumps(
            {
                "out": str(Path(args.out).resolve()),
                "failed": review["failed"],
                "worse": len(review["lists"]["worse"]),
                "better": len(review["lists"]["better"]),
                "elapsed_seconds": round(review["elapsed_seconds"], 1),
            },
            ensure_ascii=False,
        )
    )
    return 1 if review["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
