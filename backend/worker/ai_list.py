"""The AI list job: ``python -m worker.cli ai-list`` (Issue #1145, docs/spec/ai_list.md).

Each trading day at 08:21 Taipei, serve runs ``ai-list --trigger scheduler`` at the
same time as ``premarket-ai`` (neither waits for the other): it makes the input
of the day with nothing after 08:15 (``worker.ai_list_input``), calls ``claude
-p`` once with ``ai_list_v1`` (sonnet), checks the answer and adds the day's rows
(``worker.ai_list_reading``).  Only made and stored here; the page and the
message read it from #1144's T2 on.

- **When**: 08:21 to 08:45 for a scheduled run (``in_run_window``);
  outside it ``skipped reason=too_late``.  Serve catches a missed start up inside
  the window (``day_done``).
- **Once a day**: a run that finds the day's ``done`` row makes no call
  (``skipped reason=already_done``); after a ``failed`` or ``rejected`` row it
  reads again and adds the next ``sequence``.  A row is never changed.
- **Limit**: 12 minutes (``TIME_LIMIT_MINUTES``); no call starts with less than
  the CLI's 300 seconds left.  Serve's backstop adds 5 minutes.
- **Skips**: a closed day ``non_trading_day``; maintenance mode ``maintenance``
  (read at the start and again right before writing); less free memory than
  ``--min-free-memory-gb`` ``low_memory``; the lock busy ``already_running``.

The record is the day's log ``<logs>/ai-list-YYYYMMDD.log``: ``===== start``,
``--- `` lines of the input and the reading, one ``--- result status=…`` line and
``===== end exit=N``; kept 90 days.  Exit 0 for done and skipped, 1 for failed
and rejected.  The lock ``<data>/locks/ai_list.lock`` is no other job's.
``--dry-run`` makes the input and calls the CLI as a run would, then prints the
result and writes nothing (no row, no raw, no log); ``--dump DIR`` also writes
the input and the answer there.

Only the standard library at the top: serve imports the log reading here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from . import job, notify

# premarket-ai's clock (--now, else now; another --date at its 08:21) and token
# words: the same 08:21 run.
from .premarket_ai import _clock, _tokens, _utc_naive

LOCK = "ai_list"
LOG_PREFIX = "ai-list"
RUN_TIME = (8, 21)
WINDOW_END = (8, 45)
TIME_LIMIT_MINUTES = 12.0
LOG_RETENTION_DAYS = 90
MIN_FREE_MEMORY_GB = 1.0
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"
DONE_RESULTS = (
    DONE,
    "skipped reason=already_done",
    "skipped reason=non_trading_day",
)
RESULT_LINE = re.compile(r"^--- result status=(\S+)(?: reason=(\S+))?")


def log_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"{LOG_PREFIX}-{day:%Y%m%d}.log"


def day_results(log_dir: Path, day: date) -> list[str]:
    """The day's ``--- result`` lines as ``status`` or ``skipped reason=<reason>``."""

    try:
        text = log_path(log_dir, day).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    results = []
    for line in text.splitlines():
        match = RESULT_LINE.match(line)
        if match:
            status, reason = match.groups()
            results.append(f"{status} reason={reason}" if status == SKIPPED else status)
    return results


def day_done(log_dir: Path, day: date) -> bool:
    return any(result in DONE_RESULTS for result in day_results(log_dir, day))


def in_run_window(moment: datetime) -> bool:
    """Between RUN_TIME and WINDOW_END Taipei: when a scheduled run reads."""

    return RUN_TIME <= (moment.hour, moment.minute) < WINDOW_END


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="組輸入並真的呼叫一次 claude -p、核對，只印出結果，不寫 DB、raw 與日誌",
    )
    parser.add_argument("--dump", help="只給 --dry-run：把輸入與 AI 回應寫進這個目錄")
    parser.add_argument(
        "--date", help="判讀的台北交易日 YYYY-MM-DD（預設 --now 的台北日）"
    )
    parser.add_argument(
        "--now",
        help="時間注入（serve 的 --now）：ISO 8601，沒有時區時為台北時間；預設現在",
    )
    parser.add_argument(
        "--trigger",
        choices=job.TRIGGERS,
        default="manual",
        help=(
            "scheduler 只在台北 08:21～08:45 判讀，其他時刻記 skipped reason=too_late"
            "（預設 manual）"
        ),
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")
    parser.add_argument(
        "--min-free-memory-gb",
        type=float,
        default=MIN_FREE_MEMORY_GB,
        help=f"可用記憶體低於此值就記 skipped reason=low_memory（預設 {MIN_FREE_MEMORY_GB:g}）",
    )
    parser.add_argument(
        "--claude-cli", help="Claude Code CLI，以 STOCK_CLAUDE_CLI 傳給呼叫層"
    )


def argument_problem(args: argparse.Namespace) -> str | None:
    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            return f"--date must be YYYY-MM-DD, got {args.date!r}"
    if args.now:
        try:
            datetime.fromisoformat(args.now)
        except ValueError:
            return f"--now must be an ISO 8601 time, got {args.now!r}"
    if args.dump and not args.dry_run:
        return "--dump applies only with --dry-run"
    if not 0 <= args.min_free_memory_gb <= 1024:
        return "--min-free-memory-gb must be between 0 and 1024"
    return None


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def outcome_line(outcome, snapshot) -> str:
    """``status=… reason=…`` and the reading's numbers, for the log."""

    parts = [f"status={outcome.status}"]
    if outcome.reason:
        parts.append(f"reason={outcome.reason}")
    parts += [
        f"session_date={snapshot.session_date.isoformat()}",
        f"list_date={snapshot.list_date.isoformat()}",
        f"pool_phase={snapshot.pool_phase}",
        f"stocks={len(snapshot.stocks)}",
        f"prompt_version={outcome.prompt_version}",
        f"model={outcome.llm_model or 'none'}",
        f"attempts={len(outcome.attempts)}",
        f"seconds={round(outcome.duration_ms / 1000)}",
        _tokens(outcome.usage),
    ]
    if outcome.output is not None and outcome.status == DONE:
        parts.append(f"stance={outcome.output['market']['stance']}")
        parts.append(f"picks={len(outcome.output['picks'])}")
        parts.append(f"levels_passed={outcome.checks.get('picks_passed', 0)}")
    if outcome.error and outcome.status != DONE:
        parts.append(f"detail={json.dumps(outcome.error[:200], ensure_ascii=False)}")
    return " ".join(parts)


class _Run:
    def __init__(
        self,
        args: argparse.Namespace,
        runner: Callable | None = None,
        out=None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.args = args
        self.moment = _clock(args)
        self.today = date.fromisoformat(args.date) if args.date else self.moment.date()
        self.data_dir = job.resolve_data_dir(None)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        self.runner = runner
        self.out = out or sys.stdout
        self.clock = clock
        self.path = log_path(self.log_dir, self.today)

    def log(self, text: str) -> None:
        if self.args.dry_run:
            print(text, file=self.out)
            return
        with open(self.path, "a", encoding="utf-8", newline="") as log:
            log.write(text + "\n")

    def run(self) -> int:
        if not self.args.dry_run:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        started = datetime.now(job.TAIPEI)
        self.started_at = _utc_naive(started)
        self.deadline = self.clock() + TIME_LIMIT_MINUTES * 60
        lock = job.FileLock(job.lock_path(self.data_dir, LOCK))
        locked = True if self.args.dry_run else lock.acquire()
        try:
            self.log(
                f"===== {started.isoformat()} start job=ai-list"
                f" trigger={self.args.trigger} date={self.today.isoformat()}"
                f" dry_run={self.args.dry_run}"
            )
            try:
                code, result = self._run(locked)
            except Exception as exc:  # logged as the day's failure
                code, result = (
                    1,
                    f"status={FAILED} reason=error:{type(exc).__name__} detail={exc}",
                )
            self.log(f"--- result {result}")
            finished = datetime.now(job.TAIPEI)
            self.log(
                f"===== {finished.isoformat()} end exit={code}"
                f" seconds={round((finished - started).total_seconds())}"
            )
        finally:
            if locked and not self.args.dry_run:
                lock.release()
            if not self.args.dry_run:
                self._remove_old_logs()
        print(
            f"ai-list {result} exit={code} log={self.path}", file=self.out, flush=True
        )
        return code

    def _skip(self) -> tuple[str | None, date | None]:
        with _session() as db:
            if not notify.is_trading_day(db, self.today):
                return f"status={SKIPPED} reason=non_trading_day", None
            if self.args.trigger == "scheduler" and not in_run_window(self.moment):
                return (
                    f"status={SKIPPED} reason=too_late at={self.moment.strftime('%H:%M')}",
                    None,
                )
            return None, notify.previous_session(db, self.today)

    def _run(self, locked: bool) -> tuple[int, str]:
        if not locked:
            return 0, f"status={SKIPPED} reason=already_running"
        if not self.args.dry_run and job.maintenance_state(self.data_dir):
            return 0, f"status={SKIPPED} reason=maintenance"
        free_mb = job.free_memory_mb()
        if free_mb is not None and free_mb < self.args.min_free_memory_gb * 1024:
            return 0, f"status={SKIPPED} reason=low_memory free_mb={free_mb}"
        skip, list_date = self._skip()
        if skip:
            return 0, skip
        if self.args.claude_cli:
            os.environ["STOCK_CLAUDE_CLI"] = self.args.claude_cli
        from app.models import IngestionRun

        from . import ai_list_input, ai_list_reading
        from .news_llm import preflight, run_claude_cli
        from .premarket_reading import Outcome

        with _session() as db:
            stored = ai_list_reading.done_reading(db, self.today)
            if stored is not None:
                return 0, (
                    f"status={SKIPPED} reason=already_done"
                    f" session_date={self.today.isoformat()} reading_id={stored.id}"
                )
            snapshot = ai_list_input.build(
                db, self.today, list_date, _utc_naive(self.moment)
            )
            self._log_input(snapshot)
            command, problem = preflight()
            # No database write until the call is over (as premarket-ai, #1051
            # review 7194545794): the raw files are written as they come, their
            # rows with the reading.
            capture = None if self.args.dry_run else ai_list_reading.AiListCapture()
            db.rollback()
            version = ai_list_reading.PROMPT_VERSION
            if problem:
                outcome = Outcome(
                    role=ai_list_reading.CHAMPION,
                    prompt_version=version,
                    prompt_sha256=ai_list_reading._sha256(
                        ai_list_reading.prompt_text(version)
                    ),
                    status=FAILED,
                    reason=problem.split(":", 1)[0],
                    error=problem,
                    output=None,
                    checks={},
                )
            else:
                outcome = ai_list_reading.read(
                    snapshot,
                    command,
                    self.runner or run_claude_cli,
                    deadline=self.deadline,
                    clock=self.clock,
                    capture=capture,
                )
            line = outcome_line(outcome, snapshot)
            self.log(f"--- {outcome.role} {line}")
            if self.args.dry_run:
                self._log_picks(outcome)
                self._dump(snapshot, outcome)
            else:
                if job.maintenance_state(self.data_dir):
                    db.rollback()
                    return 0, f"status={SKIPPED} reason=maintenance after_calls=yes"
                run = IngestionRun(
                    run_type=ai_list_reading.RUN_TYPE,
                    source="claude_cli",
                    run_date=self.today,
                    status="running",
                    started_at=self.started_at,
                    data_as_of=snapshot.cutoff_at.isoformat(),
                    metadata_json={},
                )
                db.add(run)
                db.flush()
                capture.store_rows(db, run)
                reading = ai_list_reading.store(
                    db,
                    snapshot,
                    outcome,
                    trigger=self.args.trigger,
                    ingestion_run_id=run.id,
                )
                self.log(
                    f"--- stored reading_id={reading.id} sequence={reading.sequence}"
                    f" input_hash={reading.input_hash}"
                )
                self._log_picks(outcome)
                run.status = "success" if outcome.status == DONE else "failed"
                run.records = 1
                run.error = outcome.error if outcome.status != DONE else None
                run.metadata_json = {
                    "reading": {
                        "prompt_version": outcome.prompt_version,
                        "status": outcome.status,
                        "reason": outcome.reason,
                        "attempts": len(outcome.attempts),
                        "duration_ms": outcome.duration_ms,
                        "usage": outcome.usage,
                        "model": outcome.llm_model,
                        "picks_passed": outcome.checks.get("picks_passed"),
                    }
                }
                run.finished_at = _utc_naive(datetime.now(job.TAIPEI))
                db.commit()
        return (0 if outcome.status == DONE else 1), line

    def _log_input(self, snapshot) -> None:
        payload = snapshot.payload
        missing = sum(
            1
            for item in payload["candidates"]
            if (item.get("level_facts") or {}).get("status") == "missing"
        )
        self.log(
            f"--- input session_date={payload['session_date']}"
            f" list_date={payload['list_date']} pool_phase={snapshot.pool_phase}"
            f" stocks={len(payload['candidates'])}"
            f" rule_list={payload['pool']['today_list_count']}"
            f" market_news={len(payload['market_news'])}"
            f" level_facts_missing={missing}"
            f" input_hash={snapshot.hash}"
        )

    def _log_picks(self, outcome) -> None:
        if outcome.status != DONE or outcome.output is None:
            return
        for pick in sorted(outcome.output["picks"], key=lambda item: item["rank"]):
            result = outcome.checks["picks"][pick["symbol"]]
            problems = ",".join(sorted({p["check"] for p in result["problems"]}))
            self.log(
                f"--- pick rank={pick['rank']} symbol={pick['symbol']}"
                f" setup={pick['method']['setup']}"
                f" basis={','.join(pick['method']['basis'])}"
                f" confidence={pick['method']['confidence']}"
                f" levels={result['status']} risk_reward={result['risk_reward']}"
                + (f" problems={problems}" if problems else "")
            )

    def _dump(self, snapshot, outcome) -> None:
        if not self.args.dump:
            return
        folder = Path(self.args.dump)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "input.json").write_text(
            json.dumps(snapshot.payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (folder / f"{outcome.role}-{outcome.prompt_version}.json").write_text(
            json.dumps(
                {
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "error": outcome.error,
                    "llm_model": outcome.llm_model,
                    "attempts": outcome.attempts,
                    "duration_ms": outcome.duration_ms,
                    "usage": outcome.usage,
                    "checks": outcome.checks,
                    "output": outcome.output,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    def _remove_old_logs(self) -> None:
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for path in self.log_dir.glob(f"{LOG_PREFIX}-*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def run(args: argparse.Namespace) -> int:
    """``worker.cli ai-list``."""

    problem = job.platform_problem("worker.ai_list")
    if problem and not args.dry_run:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    return _Run(args).run()
