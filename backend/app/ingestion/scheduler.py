"""APScheduler entrypoint for daily ingestion retries."""

from __future__ import annotations

import datetime as dt
import logging
import signal
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.ingestion.pipeline import Pipeline, PipelineRunResult, create_production_pipeline

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
Clock = Callable[[], dt.datetime]


class NotifierLike(Protocol):
    def notify(self, subject: str, message: str) -> None:
        """Send one notification."""


class _LoggingNotifier:
    def notify(self, subject: str, message: str) -> None:
        logger.info("[NOTIFICATION] %s: %s", subject, message)


@dataclass(slots=True)
class DailyIngestionState:
    """Successful source state for one Taipei calendar date."""

    date: dt.date
    succeeded_sources: set[str] = field(default_factory=set)
    adjustment_succeeded: bool = False
    all_green: bool = False


class IngestionCoordinator:
    """Retry coordinator shared by APScheduler and unit tests."""

    def __init__(
        self,
        pipeline: Pipeline,
        notifier: NotifierLike | None = None,
        *,
        clock: Clock | None = None,
        cutoff_time: dt.time = dt.time(23, 59),
    ) -> None:
        self._pipeline = pipeline
        self._notifier = notifier or _default_notifier()
        self._clock = clock or taipei_now
        self._cutoff_time = cutoff_time
        self._state: DailyIngestionState | None = None

    @property
    def state(self) -> DailyIngestionState | None:
        return self._state

    def trigger(self) -> PipelineRunResult | None:
        """Run failed-or-not-yet-run sources for the current Taipei day.

        Returns `None` when today's run is already complete or the cutoff has passed.
        """
        now = self._clock().astimezone(TAIPEI)
        state = self._state_for(now.date())
        if state.all_green:
            logger.info("ingestion already complete for %s", state.date.isoformat())
            return None
        if now.timetz().replace(tzinfo=None) > self._cutoff_time:
            logger.info("ingestion cutoff passed for %s", state.date.isoformat())
            return None

        pending = self._pending_sources()
        result = self._pipeline.run(
            date=state.date,
            source_names=None if not state.succeeded_sources else pending,
        )
        self._record_result(state, result)
        self._notify_failures(result)
        return result

    def _state_for(self, today: dt.date) -> DailyIngestionState:
        if self._state is None or self._state.date != today:
            self._state = DailyIngestionState(date=today)
        return self._state

    def _pending_sources(self) -> Iterable[str]:
        names = [name for name, _source in self._pipeline._ordered_sources()]
        succeeded = self._state.succeeded_sources if self._state is not None else set()
        return [name for name in names if name not in succeeded]

    def _record_result(self, state: DailyIngestionState, result: PipelineRunResult) -> None:
        for name, source_result in result.sources.items():
            if source_result.success:
                state.succeeded_sources.add(name)
        if result.adjustment_success:
            state.adjustment_succeeded = True
        all_sources = {name for name, _source in self._pipeline._ordered_sources()}
        if all_sources.issubset(state.succeeded_sources) and state.adjustment_succeeded:
            state.all_green = True

    def _notify_failures(self, result: PipelineRunResult) -> None:
        for name, source_result in result.failed_sources.items():
            self._safe_notify(
                "Ingestion source failed",
                f"{result.date.isoformat()} {name}: {source_result.error or 'unknown error'}",
            )
        if not result.adjustment_success:
            self._safe_notify(
                "Ingestion adjustment failed",
                f"{result.date.isoformat()}: {result.adjustment_error or 'unknown error'}",
            )

    def _safe_notify(self, subject: str, message: str) -> None:
        try:
            self._notifier.notify(subject, message)
        except Exception:  # noqa: BLE001 - notification must not break retries.
            logger.exception("notifier failed")


def taipei_now() -> dt.datetime:
    return dt.datetime.now(TAIPEI)


def _default_notifier() -> NotifierLike:
    try:
        from app.notifications.log_notifier import LogNotifier
    except Exception:  # noqa: BLE001 - keep scheduler import/testable without optional deps.
        return _LoggingNotifier()
    return LogNotifier()


def build_scheduler(
    coordinator: IngestionCoordinator,
    *,
    scheduler_factory: Callable[..., Any] | None = None,
) -> Any:
    """Create an APScheduler BackgroundScheduler with daily and hourly triggers."""
    if scheduler_factory is None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on installed extras.
            raise RuntimeError("APScheduler is required to run app.ingestion.scheduler") from exc

        scheduler_factory = BackgroundScheduler

    scheduler = scheduler_factory(timezone=TAIPEI)
    scheduler.add_job(
        coordinator.trigger,
        "cron",
        hour=18,
        minute=0,
        id="ingestion_daily_start",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        coordinator.trigger,
        "cron",
        hour="19-23",
        minute=0,
        id="ingestion_hourly_retry",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    coordinator = IngestionCoordinator(create_production_pipeline(), _default_notifier())
    scheduler = build_scheduler(coordinator)
    scheduler.start()
    logger.info("ingestion scheduler started; timezone=%s", TAIPEI.key)

    stop = False

    def _request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    try:
        while not stop:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
