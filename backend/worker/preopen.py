"""The pre-open check of the today list: ``python -m worker.cli preopen`` (#755).

Each trading day at 08:20 Taipei, serve runs ``preopen --trigger scheduler``. It takes
the list the today page shows, the run ``app.candidate_runs.read_run`` gives for the
session before today (``notify.previous_session``: the weekday before, skipping the days
``trading_calendar_days`` marks closed), and writes ``preopen_news_checks``: per
candidate, the news its daily had not seen, with the AI direction of each as stored then
(``app.preopen_news``, #755 decision 6888598143). No AI is called.

- **When**: 08:20, after the 08:00 news run (2 to 4 minutes, #755 AC-1), away from the
  watchdog's :15, us at 08:30 and notify at 08:45. A scheduled run checks only between
  08:20 and 13:30 Taipei and records ``skipped reason=too_late`` otherwise; serve
  catches a missed day up in that window (``day_done``).
- **The news run**: while ``news.lock`` is held (a late news run), the check waits for
  it, polling with ``job.lock_held`` (it takes the lock for a moment and drops it at
  once: it never works holding it, so the next news run is not kept out), at most 10
  minutes; then it checks anyway and the result says ``news_running``.
- **Once a day**: a scheduled run that finds the list date's rows of the same run
  records ``skipped reason=already_checked``, so the day's result is the first check.
  ``--force`` replaces them, and so does a run that finds the rows of another run of
  the date (the list recomputed); the log keeps the replaced ``checked_at``.
- **Skips**: a weekend or a closed day ``non_trading_day`` (no rows); maintenance mode
  ``maintenance`` (the check writes the database; read at the start and again right
  before writing, as it may start during the wait for news); no list for the date ``no_list``;
  the lock busy ``already_running``.

- **The candidate pool's morning run** (#1020): after a check (not after a skip), the
  same ``checked_at`` adds the stocks named by the news collected after the evening
  pool (``worker.candidate_pool.run_morning_pool``, written once). One
  ``--- candidate_pool phase=morning status=…`` line with its finish time and seconds;
  its outcome never changes the result line or the exit code.

The record is the day's log ``<logs>/preopen-YYYYMMDD.log`` (the Taipei day of the
run): ``===== start``, a line per candidate with news, one ``--- result status=…`` line
and ``===== end exit=N``; kept 90 days. The lock ``<data>/locks/preopen.lock`` is no other
job's. Not through ``worker.job``: it reads the news and writes a few dozen rows.

Only the standard library at the top: serve imports the log reading here.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from . import job, notify

LOCK = "preopen"
NEWS_LOCK = "news"
LOG_PREFIX = "preopen"
RUN_TIME = (8, 20)
CATCH_UP_END = (13, 30)
NEWS_WAIT_SECONDS = 600.0
NEWS_POLL_SECONDS = 10.0
# The wait for the news run and the check itself; serve's backstop adds 5 minutes.
TIME_LIMIT_MINUTES = 15.0
LOG_RETENTION_DAYS = 90
CHECKED = "checked"
FAILED = "failed"
SKIPPED = "skipped"
# The results after which the day needs no run any more (serve's catch-up).
DONE_RESULTS = (
    CHECKED,
    "skipped reason=already_checked",
    "skipped reason=non_trading_day",
    "skipped reason=no_list",
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
    """Between RUN_TIME and CATCH_UP_END Taipei: when a scheduled run checks."""

    return RUN_TIME <= (moment.hour, moment.minute) < CATCH_UP_END


def wait_for_news(
    path: Path,
    wait_seconds: float = NEWS_WAIT_SECONDS,
    poll_seconds: float = NEWS_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bool, float]:
    """Wait while the news job holds PATH, at most WAIT_SECONDS.

    Returns (whether news was still running at the end, seconds waited). It only
    probes the lock (``job.lock_held`` takes it for a moment and drops it).
    """

    started = clock()
    while job.lock_held(path):
        waited = clock() - started
        if waited >= wait_seconds:
            return True, waited
        sleep(min(poll_seconds, wait_seconds - waited))
    return False, clock() - started


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只印出這次會存的結果，不寫 DB、不寫日誌",
    )
    parser.add_argument("--force", action="store_true", help="名單日已有結果時整天覆寫")
    parser.add_argument("--date", help="台北日 YYYY-MM-DD（預設 --now 的台北日）")
    parser.add_argument(
        "--now",
        help="時間注入（serve 的 --now）：ISO 8601，沒有時區時為台北時間；預設現在",
    )
    parser.add_argument(
        "--trigger",
        choices=job.TRIGGERS,
        default="manual",
        help=(
            "scheduler 只在台北 08:20～13:30 檢查，其他時刻記 skipped reason=too_late"
            "（預設 manual）"
        ),
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")


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
    return None


def _clock(args: argparse.Namespace) -> datetime:
    if not getattr(args, "now", None):
        return datetime.now(job.TAIPEI)
    moment = datetime.fromisoformat(args.now)
    return (moment if moment.tzinfo else moment.replace(tzinfo=job.TAIPEI)).astimezone(
        job.TAIPEI
    )


def _today(args: argparse.Namespace) -> date:
    return date.fromisoformat(args.date) if args.date else _clock(args).date()


def _utc_naive(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def _taipei(value: datetime | None) -> str:
    if value is None:
        return "none"
    return value.replace(tzinfo=timezone.utc).astimezone(job.TAIPEI).isoformat()


def _summary_lines(db, rows) -> list[str]:
    from app.models import Instrument

    names = {
        row.id: f"{row.exchange}:{row.symbol}"
        for row in db.query(Instrument).filter(
            Instrument.id.in_([row.instrument_id for row in rows])
        )
    }
    return [
        f"--- candidate rank={row.rank} {names.get(row.instrument_id, row.instrument_id)}"
        f" news={row.news_count} positive={row.positive} negative={row.negative}"
        f" mixed={row.mixed} unknown={row.unknown} unscored={row.unscored}"
        f" ids={','.join(str(entry['news_id']) for entry in row.news_json) or '-'}"
        for row in rows
        if row.news_count
    ]


class _Run:
    def __init__(
        self,
        args: argparse.Namespace,
        wait: Callable[[Path], tuple[bool, float]] | None = None,
        out=None,
    ) -> None:
        self.args = args
        self.today = _today(args)
        self.data_dir = job.resolve_data_dir(None)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        self.wait = wait or wait_for_news
        self.out = out or sys.stdout
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
        lock = job.FileLock(job.lock_path(self.data_dir, LOCK))
        locked = True if self.args.dry_run else lock.acquire()
        try:
            self.log(
                f"===== {started.isoformat()} start job=preopen trigger={self.args.trigger}"
                f" date={self.today.isoformat()} force={self.args.force}"
                f" dry_run={self.args.dry_run}"
            )
            try:
                code, result = self._run(locked)
            except Exception as exc:  # logged as the day's failure
                code, result = (
                    1,
                    (f"status={FAILED} reason=error:{type(exc).__name__} detail={exc}"),
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
            f"preopen {result} exit={code} log={self.path}", file=self.out, flush=True
        )
        return code

    def _decide(self):
        """(skip result or None, list date, run id) from one short read."""

        from app.candidate_runs import read_run
        from app.preopen_news import stored_check

        with _session() as db:
            if not notify.is_trading_day(db, self.today):
                return f"status={SKIPPED} reason=non_trading_day", None, None, None
            if self.args.trigger == "scheduler":
                moment = _clock(self.args)
                if not in_run_window(moment):
                    return (
                        f"status={SKIPPED} reason=too_late"
                        f" at={moment.strftime('%H:%M')}",
                        None,
                        None,
                        None,
                    )
            list_date = notify.previous_session(db, self.today)
            run = read_run(db, list_date)
            if run is None:
                return (
                    f"status={SKIPPED} reason=no_list list_date={list_date.isoformat()}",
                    list_date,
                    None,
                    None,
                )
            stored = stored_check(db, list_date)
            same = bool(stored) and stored[0].candidate_run_id == run.id
            if same and not self.args.force:
                return (
                    f"status={SKIPPED} reason=already_checked"
                    f" list_date={list_date.isoformat()} run_id={run.id}"
                    f" checked_at={_taipei(stored[0].checked_at)}",
                    list_date,
                    run.id,
                    None,
                )
            replaced = stored[0] if stored else None
            previous = (
                f"checked_at={_taipei(replaced.checked_at)} run_id={replaced.candidate_run_id}"
                if replaced
                else None
            )
            return None, list_date, run.id, previous

    def _run(self, locked: bool) -> tuple[int, str]:
        if not locked:
            return 0, f"status={SKIPPED} reason=already_running"
        if not self.args.dry_run and job.maintenance_state(self.data_dir):
            return 0, f"status={SKIPPED} reason=maintenance"
        skip, list_date, run_id, previous = self._decide()
        if skip:
            return 0, skip
        # A dry run only prints: it does not wait for the news run (review 6889365957).
        news_running, waited = (
            (False, 0.0)
            if self.args.dry_run
            else self.wait(job.lock_path(self.data_dir, NEWS_LOCK))
        )
        self.log(
            f"--- news_lock waited={round(waited)}s"
            f" running={'yes' if news_running else 'no'}"
        )
        from app.models import CandidateRun
        from app.preopen_news import check_rows, replace_check

        with _session() as db:
            run = db.get(CandidateRun, run_id)
            checked_at = _utc_naive(_clock(self.args))
            window_start = run.computed_at
            rows = check_rows(db, run, checked_at)
            counts = {
                "candidates": len(rows),
                "with_news": sum(1 for row in rows if row.news_count),
                "news": sum(row.news_count for row in rows),
                "unscored": sum(row.unscored for row in rows),
            }
            lines = _summary_lines(db, rows)
            if previous:
                self.log(f"--- overwrite {previous}")
            for line in lines:
                self.log(line)
            if not self.args.dry_run:
                # Maintenance may have started during the wait for news (a backfill, a
                # deploy): read the marker again right before writing (review 6889365957).
                if job.maintenance_state(self.data_dir):
                    return 0, f"status={SKIPPED} reason=maintenance after_wait=yes"
                replace_check(db, run, rows)
                db.commit()
        self.log(self._candidate_pool(list_date, checked_at))
        result = (
            f"status={CHECKED} list_date={list_date.isoformat()} run_id={run_id}"
            f" window_start={_taipei(window_start)} checked_at={_taipei(checked_at)}"
            + "".join(f" {key}={value}" for key, value in counts.items())
        )
        if news_running:
            result += " news_running=yes"
        return 0, result

    def _candidate_pool(self, list_date: date, checked_at: datetime) -> str:
        """The candidate pool's morning run (#1020) as one log line.

        After the check, so it reads the same news; its outcome never changes
        the check's result or exit code (``run_morning_pool`` never raises).
        """

        from worker.candidate_pool import run_morning_pool

        started = datetime.now(job.TAIPEI)
        try:
            outcome = run_morning_pool(
                list_date, checked_at, dry_run=self.args.dry_run, session=_session
            )
        except Exception as exc:  # noqa: BLE001 - one log line, the check stands
            outcome = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        finished = datetime.now(job.TAIPEI)
        fields = [f"status={outcome.get('status')}"]
        for key in ("reason", "run_id", "records", "union"):
            if outcome.get(key) is not None:
                fields.append(f"{'added' if key == 'records' else key}={outcome[key]}")
        if outcome.get("error"):
            fields.append(f"error={str(outcome['error']).replace(' ', '_')[:200]}")
        fields.append(f"finished_at={finished.isoformat()}")
        fields.append(f"seconds={round((finished - started).total_seconds(), 1)}")
        return "--- candidate_pool phase=morning " + " ".join(fields)

    def _remove_old_logs(self) -> None:
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for path in self.log_dir.glob(f"{LOG_PREFIX}-*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def run(args: argparse.Namespace) -> int:
    """``worker.cli preopen``."""

    problem = job.platform_problem("worker.preopen")
    if problem and not args.dry_run:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    return _Run(args).run()
