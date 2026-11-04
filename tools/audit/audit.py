"""Gate-closing deep audit of a stock.db copy: recompute the whole history (Issue #391).

Run at every gate's close on a read-only copy of the production database
(``tools/ops/copy_db.py``); post ``summary.md`` on the gate's Issue.  The
audit only reads: the database through ``mode=ro`` + ``query_only``, the raw
captures it cites with ``open(path, "rb")``.  Nothing is repaired.

Refuses (exit 2, before anything is read) when ``--db`` is the production
database (inside ``stock-lab-data`` or ``STOCK_DATA_DIR``, or the same file as
its ``stock.db``, a hard link included) or ``--out`` is inside that directory
(the path as written or with links resolved), when Taipei time is between 21:30 and
23:30 (the daily job and its 23:00 retry, #466), or when free physical memory is under
``--min-free-gb``; the rules are ``tools/research/backtest_research.py``'s.  A
run that reaches 21:30 stops before the next item, marks the rest
undetermined and exits 3 (rerun after 23:30, ``--only`` the items left).

Items (docs/WORKFLOW.md 任務流程第 6 步 lists how they are read):
bars_integrity, bars_coverage, bars_raw_values, bars_raw_missing (A4),
bars_raw_missing_inactive, chips_raw_institutional (A3), chips_raw_margin,
actions_fields (A1), actions_missing (A2), provenance, indicators,
chips_ratios, candidates, groups.  Each is 通過／失敗／無法判定: failed when
anything disagrees, undetermined when something could not be compared (a raw
file that cannot be read, a population that cannot be rebuilt) or nothing
was compared.

Writes ``<out>/summary.md`` and ``<out>/findings.json``; exit 0 when nothing
failed, 1 when an item failed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from audit_checks import (  # noqa: E402
    Context,
    actions_fields,
    actions_missing,
    bars_coverage,
    bars_integrity,
    bars_raw,
    chips_raw,
    derived_checks,
    provenance,
)
from audit_lib import FAIL, PASS, RESULT_LABELS, UNKNOWN, Check, RawFiles, connect  # noqa: E402
from backtest_research import (  # noqa: E402
    PRODUCTION_DIR_NAME,
    TAIPEI,
    daily_window_problem,
    free_memory_gb,
    peak_memory_gb,
    production_problem,
)

# (key or keys, function); the derived items share one pass over the instruments.
STEPS = (
    (("bars_integrity",), bars_integrity),
    (("bars_coverage",), bars_coverage),
    (("bars_raw_values", "bars_raw_missing", "bars_raw_missing_inactive"), bars_raw),
    (("chips_raw_institutional", "chips_raw_margin"), chips_raw),
    (("actions_fields",), actions_fields),
    (("actions_missing",), actions_missing),
    (("provenance",), provenance),
    (("indicators", "chips_ratios", "candidates", "groups"), derived_checks),
)
KEYS = [key for keys, _ in STEPS for key in keys]
TITLES = {
    "bars_integrity": "日行情合理性",
    "bars_coverage": "日行情完整性（列數與交易所日期）",
    "bars_raw_values": "raw 對照：日線值",
    "bars_raw_missing": "raw 有行情、active 標的沒有日線",
    "bars_raw_missing_inactive": "raw 有行情、非 active 標的沒有日線",
    "chips_raw_institutional": "raw 對照：三大法人（當日最晚 capture）",
    "chips_raw_margin": "raw 對照：融資餘額與增減",
    "actions_fields": "除權息欄位對官方價格與配股數",
    "actions_missing": "raw 有除權息事件、corporate_actions 沒有",
    "provenance": "來源與日期欄位",
    "indicators": "技術指標全標的全歷史重算",
    "chips_ratios": "訊號的法人 5 日比率與融資 5 日變動比",
    "candidates": "候選分數重算",
    "groups": "族群分數重算",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", required=True, help="read-only copy of stock.db (tools/ops/copy_db.py)"
    )
    parser.add_argument(
        "--out", required=True, help="directory for summary.md and findings.json"
    )
    parser.add_argument(
        "--raw-dir",
        help="raw copy where an old Windows payload_path is looked for when it does not exist",
    )
    parser.add_argument("--only", help="comma-separated items to run (default: all)")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="indicators and signal ratios on the fixed instrument sample only",
    )
    parser.add_argument("--min-free-gb", type=float, default=5.0)
    return parser


def out_problem(out: Path, environ: dict[str, str]) -> str | None:
    """``--out`` must not be in the production data directory (#418 review).

    Both the path as written and the path with links resolved are compared,
    as ``coordinator_lib.sh`` ``guard_dir`` does: a junction or symlink into
    ``stock-lab-data`` or ``STOCK_DATA_DIR`` is refused as well.
    """

    roots = []
    if environ.get("STOCK_DATA_DIR"):
        data_dir = Path(environ["STOCK_DATA_DIR"])
        roots = [data_dir.absolute(), data_dir.resolve()]
    for candidate in (out.absolute(), out.resolve()):
        if PRODUCTION_DIR_NAME in (part.lower() for part in candidate.parts):
            return f"--out {out} is inside {PRODUCTION_DIR_NAME}"
        for root in roots:
            if candidate == root or root in candidate.parents:
                return f"--out {out} is inside STOCK_DATA_DIR ({root})"
    return None


def refusals(
    db: Path,
    environ: dict[str, str],
    now: datetime,
    free: float | None,
    min_free: float,
    out: Path | None = None,
) -> list[str]:
    problems = [
        production_problem(db, environ),
        None if out is None else out_problem(out, environ),
        daily_window_problem(now),
        None if db.is_file() else f"{db} does not exist",
    ]
    if free is None or free < min_free:
        problems.append(f"free memory {free} GB is under {min_free} GB")
    return [problem for problem in problems if problem]


def _git_head() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            or None
        )
    except (OSError, subprocess.SubprocessError):
        return None


def run(
    db: Path,
    raw_dir: Path | None,
    only: list[str],
    quick: bool,
    clock=lambda: datetime.now(timezone.utc),
) -> tuple[list[Check], dict]:
    con = connect(db)
    ctx = Context(con, RawFiles(raw_dir), quick=quick)
    ctx.load()
    facts = {
        "db": str(db.resolve()),
        "alembic": (
            con.execute("select version_num from alembic_version").fetchone() or [None]
        )[0],
        "first_day": ctx.first_day,
        "last_day": ctx.last_day,
        "raw_dir": None if raw_dir is None else str(raw_dir),
        "quick": quick,
    }

    def stop() -> str | None:
        reason = daily_window_problem(clock())
        return None if reason is None else f"未執行：{reason}"

    checks: list[Check] = []
    for keys, function in STEPS:
        wanted = [key for key in keys if key in only]
        if not wanted:
            continue
        reason = stop()
        if reason:
            checks += [Check(key, TITLES[key], skipped=reason) for key in wanted]
            continue
        started = time.perf_counter()
        result = function(ctx, stop) if function is derived_checks else function(ctx)
        produced = result if isinstance(result, list) else [result]
        elapsed = time.perf_counter() - started
        for check in produced:
            check.seconds = elapsed / len(produced)
            if check.key in only:
                checks.append(check)
    facts["raw_files_read"] = ctx.raw.read
    facts["raw_files_unreadable"] = ctx.raw.unreadable
    con.close()
    return checks, facts


def _cell(value) -> str:
    return str(value).replace("|", "／").replace("\n", " ")


def summary_markdown(checks: list[Check], facts: dict) -> str:
    counts = {
        state: sum(check.result == state for check in checks)
        for state in (PASS, FAIL, UNKNOWN)
    }
    lines = [
        "# DB 深度審查 summary",
        "",
        f"- DB：`{facts['db']}`（Alembic `{facts['alembic']}`，日線 {facts['first_day']}～{facts['last_day']}）",
        f"- raw：{'`' + facts['raw_dir'] + '`' if facts.get('raw_dir') else '依 `payload_path`'}；讀取 {facts.get('raw_files_read')} 份、讀不到 {facts.get('raw_files_unreadable')} 份",
        f"- 執行：{facts.get('started')}～{facts.get('finished')}（台北），{facts.get('seconds')} 秒，記憶體峰值 {facts.get('peak_working_set_gb')} GB，工具 `{facts.get('git_head')}`{'，--quick' if facts.get('quick') else ''}",
        f"- 結果：通過 {counts[PASS]}、失敗 {counts[FAIL]}、無法判定 {counts[UNKNOWN]}",
        "",
        "| 項目 | 對應 | 結果 | 比對 | 不一致 | 無法判定 | 範圍 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            f"| `{check.key}` {check.title} | {check.issues or '—'} | **{RESULT_LABELS[check.result]}** | {check.compared} | "
            f"{sum(check.failures.values())} | {sum(check.unknown.values())} | {_cell(check.skipped or check.scope)} |"
        )
    for check in checks:
        if check.result == PASS and not check.notes:
            continue
        lines += [
            "",
            f"## `{check.key}` {check.title}：{RESULT_LABELS[check.result]}",
            "",
        ]
        if check.skipped:
            lines.append(f"- {check.skipped}")
        for note in check.notes:
            lines.append(f"- {note}")
        for category, n in sorted(check.failures.items()):
            lines.append(f"- 失敗 `{category}`：{n}")
            for example in check.examples.get(category, []):
                lines.append(
                    f"  - `{_cell(json.dumps(example, ensure_ascii=False, default=str))}`"
                )
        for reason, n in sorted(check.unknown.items()):
            lines.append(f"- 無法判定 `{reason}`：{n}")
            for example in check.unknown_examples.get(reason, [])[:5]:
                lines.append(
                    f"  - `{_cell(json.dumps(example, ensure_ascii=False, default=str))}`"
                )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    db = Path(args.db)
    only = (
        KEYS
        if not args.only
        else [key.strip() for key in args.only.split(",") if key.strip()]
    )
    unknown = [key for key in only if key not in KEYS]
    free = free_memory_gb()
    problems = refusals(
        db,
        dict(os.environ),
        datetime.now(timezone.utc),
        free,
        args.min_free_gb,
        Path(args.out),
    )
    if unknown:
        problems.append(f"unknown items {unknown}; choose from {KEYS}")
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    started = time.perf_counter()
    started_at = datetime.now(TAIPEI)
    checks, facts = run(
        db, Path(args.raw_dir) if args.raw_dir else None, only, args.quick
    )
    peak = peak_memory_gb()
    facts.update(
        started=f"{started_at:%Y-%m-%d %H:%M}",
        finished=f"{datetime.now(TAIPEI):%Y-%m-%d %H:%M}",
        seconds=round(time.perf_counter() - started, 1),
        peak_working_set_gb=None if peak is None else round(peak, 2),
        free_memory_gb_at_start=round(free, 2),
        git_head=_git_head(),
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text(
        summary_markdown(checks, facts), encoding="utf-8", newline="\n"
    )
    (out / "findings.json").write_text(
        json.dumps(
            {"facts": facts, "checks": [check.as_json() for check in checks]},
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                **{c.key: c.result for c in checks},
                "seconds": facts["seconds"],
                "peak_working_set_gb": facts["peak_working_set_gb"],
            },
            ensure_ascii=False,
        )
    )
    if any(check.skipped for check in checks):
        return 3
    return 1 if any(check.result == FAIL for check in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
