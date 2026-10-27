"""Research backtest on a copy of stock.db: canonical strategies and ablations (#318).

Runs ``worker.pipeline.backtest(registry=...)`` once over ``--start``..``--end``
on the database given by ``--db`` (a ``tools/ops/copy_db.py`` copy or another
isolated database; the backtest writes signals, settlements and a
``run_type=backtest`` run).  The registry is the canonical strategies (unless
``--no-canonical``) followed by the ablations ``--ablate`` names
(``app.strategies.ablation``); every strategy shares one replay, so the inputs
of each instrument and session are built once.

Refuses before importing the app when ``--db`` is the production database
(inside ``stock-lab-data`` or ``STOCK_DATA_DIR``), when Taipei time is between
18:30 and 21:30 (the daily job), or when free physical memory is under
``--min-free-gb``.  Prints one JSON object: the run, the registry, elapsed
seconds of the migration check and the replay, peak working set, and per
strategy the signal, conditional and settlement counts.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))  # no daylight saving time
DAILY_WINDOW = ((18, 30), (21, 30))
PRODUCTION_DIR_NAME = "stock-lab-data"


class Refused(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backtest_research.py", description=__doc__)
    parser.add_argument("--db", required=True, help="isolated copy of stock.db")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--ablate",
        nargs="*",
        default=[],
        metavar="STRATEGY:CONDITION",
        help="ablations to add, e.g. breakout_v1:group; 'all' for every one",
    )
    parser.add_argument(
        "--no-canonical",
        action="store_true",
        help="evaluate only the ablations, not breakout_v1/pullback_v1",
    )
    parser.add_argument("--min-free-gb", type=float, default=10.0)
    parser.add_argument("--force", action="store_true", help="rerun a finished run")
    return parser


def production_problem(db: Path, environ: dict[str, str]) -> str | None:
    resolved = db.resolve()
    if PRODUCTION_DIR_NAME in (part.lower() for part in resolved.parts):
        return f"{db} is inside {PRODUCTION_DIR_NAME}"
    data_dir = environ.get("STOCK_DATA_DIR")
    if data_dir:
        root = Path(data_dir).resolve()
        if resolved == root or root in resolved.parents:
            return f"{db} is inside STOCK_DATA_DIR ({root})"
    return None


def daily_window_problem(now: datetime) -> str | None:
    local = now.astimezone(TAIPEI)
    (start_h, start_m), (end_h, end_m) = DAILY_WINDOW
    minutes = local.hour * 60 + local.minute
    if start_h * 60 + start_m <= minutes < end_h * 60 + end_m:
        return f"Taipei time {local:%H:%M} is inside 18:30-21:30 (daily job)"
    return None


def free_memory_gb() -> float | None:
    if sys.platform == "win32":

        class Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPhys / 2**30
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
    except (ValueError, OSError, AttributeError):
        return None


def peak_memory_gb() -> float | None:
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32")
        # Without these the 64-bit pseudo handle is truncated and the call fails.
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None
        return counters.PeakWorkingSetSize / 2**30
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # KiB on Linux


def ablation_items(names: list[str]) -> list[tuple[str, str]]:
    from app.strategies.ablation import ABLATIONS, all_ablations

    if names == ["all"]:
        return all_ablations()
    items = []
    for name in names:
        key, _, condition = name.partition(":")
        if condition not in ABLATIONS.get(key, {}):
            raise Refused(f"unknown ablation {name!r}")
        items.append((key, condition))
    return items


def counts(run_id: int) -> dict[str, dict[str, int]]:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Signal, SignalSettlement, StrategyVersion

    prefix = f"backtest-{run_id}-%"
    with SessionLocal() as db:
        rows = db.execute(
            select(StrategyVersion.name, Signal.status, func.count(Signal.id))
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(Signal.signal_key.like(prefix))
            .group_by(StrategyVersion.name, Signal.status)
        ).all()
        settled = db.execute(
            select(StrategyVersion.name, func.count(SignalSettlement.id))
            .join(Signal, Signal.id == SignalSettlement.signal_id)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(Signal.signal_key.like(prefix))
            .group_by(StrategyVersion.name)
        ).all()
    result: dict[str, dict[str, int]] = {}
    for name, status, count in rows:
        item = result.setdefault(name, {"signals": 0, "settlements": 0})
        item["signals"] += count
        item[status] = count
    for name, count in settled:
        result.setdefault(name, {"signals": 0, "settlements": 0})["settlements"] = count
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = [
        production_problem(db, dict(os.environ)),
        daily_window_problem(datetime.now(timezone.utc)),
        None if db.is_file() else f"{db} does not exist",
    ]
    free = free_memory_gb()
    if free is None or free < args.min_free_gb:
        problems.append(f"free memory {free} GB is under {args.min_free_gb} GB")
    problems = [problem for problem in problems if problem]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2

    os.environ["STOCK_DB_PATH"] = str(db.resolve())
    os.environ["STOCK_DATA_DIR"] = str(db.resolve().parent)
    os.environ["STOCK_RAW_DIR"] = str(db.resolve().parent / "raw")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.db import init_db
    from app.strategies.ablation import research_registry
    from worker import pipeline

    try:
        items = ablation_items(args.ablate)
        registry = research_registry(items, canonical=not args.no_canonical)
    except (Refused, ValueError) as exc:
        print(json.dumps({"refused": [str(exc)]}, ensure_ascii=False))
        return 2
    started = time.perf_counter()
    init_db()
    migrated = time.perf_counter()
    result = pipeline.backtest(
        args.start, args.end, force=args.force, registry=registry
    )
    finished = time.perf_counter()
    peak = peak_memory_gb()
    run = result["run"]
    print(
        json.dumps(
            {
                "db": str(db.resolve()),
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "registry": list(registry),
                "run_id": run["id"],
                "status": run["status"],
                "request_key": run["request_key"],
                "score_sessions": (run.get("metadata") or {}).get(
                    "score_session_count"
                ),
                "idempotent_reuse": bool(result.get("idempotent_reuse")),
                "error": result.get("error"),
                "init_db_seconds": round(migrated - started, 1),
                "backtest_seconds": round(finished - migrated, 1),
                "peak_working_set_gb": None if peak is None else round(peak, 2),
                "free_memory_gb_at_start": round(free, 2),
                "strategies": counts(run["id"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if run["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
