"""The pre-market AI reading job: ``python -m worker.cli premarket-ai`` (#1041).

Each trading day at 08:21 Taipei, serve runs ``premarket-ai --trigger scheduler``:
it makes the input snapshot of the day with nothing after 08:15
(``worker.premarket_input``), calls ``claude -p`` once with ``premarket_v1``
(sonnet), checks the answer and adds the day's rows
(``worker.premarket_reading``; docs/spec/premarket_ai.md).

- **When**: 08:21, after the 08:15 TX night run and the 08:20 pre-open check,
  before notify at 08:45. A scheduled run reads only between 08:21 and 08:45
  (``in_run_window``) and records ``skipped reason=too_late`` otherwise: after
  08:45 the message is out and nothing is caught up (#1002 AC-3 C). Serve
  catches a missed start up inside the window (``day_done``).
- **The news run**: not waited for. The snapshot reads only what was collected
  and judged by 08:15, so a news run still going at 08:21 changes nothing in
  it; whether ``news.lock`` was held is logged (``news_running``).
- **Once a day**: a run that finds the day's ``done`` row of a version and role
  makes no call for it (``skipped reason=already_done``); after a ``failed`` or
  ``rejected`` row it reads again and adds the next row. A row is never changed.
  A shadow version (``premarket_reading.SHADOW_PROMPT_VERSION``) reads the
  champion's input of the day: the stored one when the champion was done
  earlier.
- **Limit**: 12 minutes (``TIME_LIMIT_MINUTES``); no call starts with less than
  the CLI's 300-second timeout left, so a retry or a shadow is left out
  rather than run past it. Serve's backstop adds 5 minutes.
- **Skips**: a weekend or a closed day ``non_trading_day``; maintenance mode
  ``maintenance`` (it writes the database; read at the start and again right
  before writing); less free memory than ``--min-free-memory-gb`` ``low_memory``;
  the lock busy ``already_running``.

The record is the day's log ``<logs>/premarket-ai-YYYYMMDD.log`` (the Taipei day of
the run): ``===== start``, ``--- `` lines of the input and each reading, one
``--- result status=…`` line (the champion's) and ``===== end exit=N``; kept 90
days. Exit 0 for done and skipped, 1 for failed and rejected. The lock
``<data>/locks/premarket_ai.lock`` is no other job's. ``--dry-run`` makes the input
and calls the CLI as a run would, then prints the result and writes nothing (no
row, no raw, no log); ``--dump DIR`` also writes the input and the answer there.

Only the standard library at the top: serve imports the log reading here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import job, notify

LOCK = "premarket_ai"
NEWS_LOCK = "news"
LOG_PREFIX = "premarket-ai"
RUN_TIME = (8, 21)
WINDOW_END = (8, 45)
TIME_LIMIT_MINUTES = 12.0
LOG_RETENTION_DAYS = 90
MIN_FREE_MEMORY_GB = 1.0
DONE = "done"
FAILED = "failed"
REJECTED = "rejected"
SKIPPED = "skipped"
# The results after which the day needs no run any more (serve's catch-up).
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
    parser.add_argument(
        "--dump", help="只給 --dry-run：把輸入快照與 AI 回應寫進這個目錄"
    )
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


def _clock(args: argparse.Namespace) -> datetime:
    """The run's Taipei moment: --now, else now; on another --date its 08:21."""

    if getattr(args, "now", None):
        moment = datetime.fromisoformat(args.now)
        moment = (
            moment if moment.tzinfo else moment.replace(tzinfo=job.TAIPEI)
        ).astimezone(job.TAIPEI)
    else:
        moment = datetime.now(job.TAIPEI)
    if args.date and date.fromisoformat(args.date) != moment.date():
        # A past (or later) day read by hand: as at its scheduled time, so that a
        # night collected that morning is in it and nothing later is.
        moment = datetime.combine(
            date.fromisoformat(args.date),
            datetime.min.time().replace(hour=RUN_TIME[0], minute=RUN_TIME[1]),
            tzinfo=job.TAIPEI,
        )
    return moment


def _utc_naive(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def _tokens(usage: dict[str, Any]) -> str:
    return " ".join(
        f"{key}={usage.get(key, 0)}"
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )


def outcome_line(outcome, snapshot) -> str:
    """``status=… reason=…`` and the reading's numbers, for the log."""

    actions: dict[str, int] = {}
    stance = None
    if outcome.output is not None and outcome.status == DONE:
        for item in outcome.output["candidates"]:
            actions[item["action"]] = actions.get(item["action"], 0) + 1
        stance = outcome.output["market"]["stance"]
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
    if stance:
        parts.append(f"stance={stance}")
        parts.append(
            "actions="
            + ",".join(
                f"{key}:{actions.get(key, 0)}" for key in ("keep", "reprice", "defer")
            )
        )
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
                f"===== {started.isoformat()} start job=premarket-ai"
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
            f"premarket-ai {result} exit={code} log={self.path}",
            file=self.out,
            flush=True,
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
        from app.premarket_ai import CHAMPION, done_reading

        from . import premarket_input, premarket_reading
        from .news_llm import preflight, run_claude_cli

        roles = premarket_reading.roles()
        with _session() as db:
            done = {
                (version, role): done_reading(db, self.today, version, role)
                for version, role in roles
            }
            if all(done.values()):
                champion = done[(premarket_reading.PROMPT_VERSION, CHAMPION)]
                return 0, (
                    f"status={SKIPPED} reason=already_done"
                    f" session_date={self.today.isoformat()} reading_id={champion.id}"
                )
            news_running = job.lock_held(job.lock_path(self.data_dir, NEWS_LOCK))
            self.log(f"--- news_lock running={'yes' if news_running else 'no'}")
            fresh = premarket_input.build(
                db, self.today, list_date, _utc_naive(self.moment)
            )
            self._log_input(fresh)
            command, problem = preflight()
            # No database write until the calls are over (review 7194545794, 1 and 2):
            # the raw files are written as they come, their rows with the readings.
            capture = None if self.args.dry_run else premarket_reading.RawCapture()
            # Nothing above wrote: end the read transaction so that no snapshot is
            # held through the calls.
            db.rollback()
            champion_snapshot = None
            outcomes = []
            for version, role in roles:
                stored = done[(version, role)]
                if stored is not None:
                    self.log(
                        f"--- {role} status={SKIPPED} reason=already_done"
                        f" prompt_version={version} reading_id={stored.id}"
                    )
                    if role == CHAMPION:
                        champion_snapshot = premarket_reading.snapshot_of(db, stored)
                        self.log(
                            f"--- stored_input reading_id={stored.id}"
                            f" input_hash={stored.input_hash}"
                        )
                    continue
                snapshot = champion_snapshot or fresh
                if role == CHAMPION:
                    champion_snapshot = snapshot
                if problem:
                    outcome = premarket_reading.Outcome(
                        role=role,
                        prompt_version=version,
                        prompt_sha256=premarket_reading._sha256(
                            premarket_reading.prompt_text(version)
                        ),
                        status=FAILED,
                        reason=problem.split(":", 1)[0],
                        error=problem,
                        output=None,
                        checks={},
                    )
                else:
                    outcome = premarket_reading.read(
                        snapshot,
                        version,
                        role,
                        command,
                        self.runner or run_claude_cli,
                        deadline=self.deadline,
                        clock=self.clock,
                        capture=capture,
                    )
                outcomes.append((outcome, snapshot))
                self.log(f"--- {role} {outcome_line(outcome, snapshot)}")
            if self.args.dry_run:
                self._dump(fresh, outcomes)
            else:
                # Maintenance may have started during the calls: read it again before
                # writing (as preopen does).
                if job.maintenance_state(self.data_dir):
                    # Nothing is written (the raw files stay on disk, without rows).
                    db.rollback()
                    return 0, f"status={SKIPPED} reason=maintenance after_calls=yes"
                run = IngestionRun(
                    run_type=premarket_reading.RUN_TYPE,
                    source="claude_cli",
                    run_date=self.today,
                    status="running",
                    # The job's start, not the write's (review 7195500836, 2): the
                    # row is only added once the calls are over.
                    started_at=self.started_at,
                    data_as_of=fresh.cutoff_at.isoformat(),
                    metadata_json={},
                )
                db.add(run)
                db.flush()
                capture.store_rows(db, run)
                for outcome, snapshot in outcomes:
                    reading = premarket_reading.store(
                        db,
                        snapshot,
                        outcome,
                        trigger=self.args.trigger,
                        ingestion_run_id=run.id,
                    )
                    self.log(
                        f"--- stored role={outcome.role} reading_id={reading.id}"
                        f" sequence={reading.sequence} input_hash={reading.input_hash}"
                    )
                champion_outcome = next(
                    (outcome for outcome, _ in outcomes if outcome.role == CHAMPION),
                    None,
                )
                run.status = (
                    "success"
                    if champion_outcome is None or champion_outcome.status == DONE
                    else "failed"
                )
                run.records = len(outcomes)
                run.error = (
                    champion_outcome.error
                    if champion_outcome is not None and champion_outcome.status != DONE
                    else None
                )
                run.metadata_json = {
                    "readings": [
                        {
                            "role": outcome.role,
                            "prompt_version": outcome.prompt_version,
                            "status": outcome.status,
                            "reason": outcome.reason,
                            "attempts": len(outcome.attempts),
                            "duration_ms": outcome.duration_ms,
                            "usage": outcome.usage,
                            "model": outcome.llm_model,
                        }
                        for outcome, _ in outcomes
                    ]
                }
                run.finished_at = _utc_naive(datetime.now(job.TAIPEI))
                db.commit()
        champion = next(
            ((o, s) for o, s in outcomes if o.role == CHAMPION),
            None,
        )
        if champion is None:
            stored = done[(premarket_reading.PROMPT_VERSION, CHAMPION)]
            return 0, (
                f"status={SKIPPED} reason=already_done"
                f" session_date={self.today.isoformat()} reading_id={stored.id}"
            )
        outcome, snapshot = champion
        line = outcome_line(outcome, snapshot)
        if news_running:
            line += " news_running=yes"
        return (0 if outcome.status == DONE else 1), line

    def _log_input(self, snapshot) -> None:
        payload = snapshot.payload
        night = payload["tx_futures"]["night"]
        us = payload["us_indices"]
        fresh = sum(
            1
            for key, value in us.items()
            if key != "expected_date"
            and value.get("freshness") in ("latest", "us_market_closed")
        )
        stats = payload["overnight_news_stats"]
        self.log(
            f"--- input session_date={payload['session_date']}"
            f" list_date={payload['list_date']} pool_phase={snapshot.pool_phase}"
            f" stocks={len(payload['candidates'])}"
            f" today_list={payload['pool']['today_list_count']}"
            f" market_news={len(payload['market_news'])}"
            f" overnight_news={stats.get('total', 0)}"
            f" ai_done={stats.get('ai_done', 0)}"
            f" us_fresh={fresh}/{len(us) - 1}"
            f" tx_night={'missing' if night.get('status') == 'missing' else night.get('close')}"
            f" taiex={payload['taiex'].get('close', 'missing')}"
            f" input_hash={snapshot.hash}"
        )

    def _dump(self, snapshot, outcomes) -> None:
        if not self.args.dump:
            return
        folder = Path(self.args.dump)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "input.json").write_text(
            json.dumps(snapshot.payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        for outcome, _snapshot in outcomes:
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
    """``worker.cli premarket-ai``."""

    problem = job.platform_problem("worker.premarket_ai")
    if problem and not args.dry_run:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    return _Run(args).run()
