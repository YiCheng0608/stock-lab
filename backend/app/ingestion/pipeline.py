"""Daily ingestion pipeline orchestration.

This module coordinates registered adapters without owning database schema details. The
default repository is in-memory so the pipeline can be exercised without a DB; production
code can inject a repository/sink with the same small method surface.
"""

from __future__ import annotations

import datetime as dt
import os
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.adapters.base import DataSource, NormalizedRow
from app.adapters import registry
from app.pricing.adjustment import fill_adjusted_prices

logger = logging.getLogger(__name__)

Clock = Callable[[], dt.datetime | dt.date]
SourceFactory = Callable[[], DataSource]

SECURITY_SOURCE_HINTS = ("corporate", "security", "securities", "mops")
DEPENDENT_SOURCE_HINTS = ("daily_price", "daily", "chips", "broker_branch", "broker")


class IngestionRepository(Protocol):
    """Storage boundary used by the pipeline.

    Implementations may persist to SQLAlchemy or keep rows in memory. The pipeline only
    depends on upsert-like operations and complete-history reads for price adjustment.
    """

    def write_rows(self, source_name: str, rows: Sequence[NormalizedRow]) -> None:
        """Persist normalized rows for one source."""

    def list_price_series(self) -> Mapping[Any, Sequence[Mapping[str, Any]]]:
        """Return complete historical raw daily price series grouped by security key."""

    def list_corporate_actions(self, security_key: Any) -> Sequence[Mapping[str, Any]]:
        """Return all corporate actions for one security key."""

    def replace_adjusted_prices(
        self,
        security_key: Any,
        adjusted_rows: Sequence[Mapping[str, Any] | Any],
    ) -> None:
        """Rewrite complete historical adjusted price columns for one security."""


@dataclass(slots=True)
class SourceRunResult:
    """Outcome for a single adapter source."""

    name: str
    success: bool
    fetched: bool
    row_count: int = 0
    error: str | None = None


@dataclass(slots=True)
class PipelineRunResult:
    """Outcome for one pipeline run."""

    date: dt.date
    sources: dict[str, SourceRunResult]
    adjustment_success: bool
    adjustment_error: str | None = None
    adjusted_security_count: int = 0

    @property
    def success(self) -> bool:
        return all(result.success for result in self.sources.values()) and self.adjustment_success

    @property
    def failed_sources(self) -> dict[str, SourceRunResult]:
        return {name: result for name, result in self.sources.items() if not result.success}


@dataclass
class InMemoryIngestionRepository:
    """Small repository useful for local runs and unit tests.

    It keeps normalized rows grouped by logical table/source and rewrites adjusted price
    rows by full security history, matching the production pipeline contract.
    """

    rows_by_source: dict[str, list[NormalizedRow]] = field(default_factory=lambda: defaultdict(list))
    adjusted_by_security: dict[Any, list[Any]] = field(default_factory=dict)

    def write_rows(self, source_name: str, rows: Sequence[NormalizedRow]) -> None:
        self.rows_by_source[source_name].extend(dict(row) for row in rows)

    def list_price_series(self) -> Mapping[Any, Sequence[Mapping[str, Any]]]:
        grouped: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
        for source_name, rows in self.rows_by_source.items():
            if "daily_price" not in source_name and not any(_is_daily_price_row(row) for row in rows):
                continue
            for row in rows:
                if _is_daily_price_row(row):
                    grouped[_security_key(row)].append(row)
        for rows in grouped.values():
            rows.sort(key=lambda row: row["date"])
        return grouped

    def list_corporate_actions(self, security_key: Any) -> Sequence[Mapping[str, Any]]:
        actions: list[Mapping[str, Any]] = []
        for rows in self.rows_by_source.values():
            for row in rows:
                if _security_key(row) == security_key and "ex_rights_date" in row:
                    actions.append(row)
        return sorted(actions, key=lambda row: row["ex_rights_date"])

    def replace_adjusted_prices(
        self,
        security_key: Any,
        adjusted_rows: Sequence[Mapping[str, Any] | Any],
    ) -> None:
        self.adjusted_by_security[security_key] = list(adjusted_rows)
        adjusted_by_date = {_read_attr(row, "date"): row for row in adjusted_rows}
        for rows in self.rows_by_source.values():
            for row in rows:
                if _security_key(row) != security_key:
                    continue
                adjusted = adjusted_by_date.get(row.get("date"))
                if adjusted is None:
                    continue
                row["open_adj"] = _read_attr(adjusted, "open_adj")
                row["high_adj"] = _read_attr(adjusted, "high_adj")
                row["low_adj"] = _read_attr(adjusted, "low_adj")
                row["close_adj"] = _read_attr(adjusted, "close_adj")


class SQLAlchemyIngestionRepository:
    """SQLAlchemy-backed repository used by the production scheduler.

    The class keeps SQLAlchemy imports inside methods so unit tests can import this module
    without installing the full runtime. Pass any SQLAlchemy `sessionmaker`-like callable.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    def write_rows(self, source_name: str, rows: Sequence[NormalizedRow]) -> None:
        ordered_rows = sorted(rows, key=_row_write_order)
        with self._session_factory() as session:
            with session.begin():
                for row in ordered_rows:
                    kind = _row_kind(source_name, row)
                    if kind == "security":
                        self._upsert_security(session, row)
                    elif kind == "daily_price":
                        self._upsert_daily_price(session, row)
                    elif kind == "chip":
                        self._upsert_chip(session, row)
                    elif kind == "broker_branch":
                        self._upsert_broker_branch(session, row)
                    elif kind == "corporate_action":
                        self._upsert_corporate_action(session, row)
                    else:
                        raise ValueError(f"unsupported ingestion row from {source_name}: {row!r}")

    def list_price_series(self) -> Mapping[Any, Sequence[Mapping[str, Any]]]:
        from sqlalchemy import select
        from app.models import DailyPrice

        grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        with self._session_factory() as session:
            rows = session.scalars(
                select(DailyPrice).order_by(DailyPrice.security_id, DailyPrice.date)
            ).all()
            for price in rows:
                grouped[price.security_id].append(
                    {
                        "date": price.date,
                        "open_raw": price.open_raw,
                        "high_raw": price.high_raw,
                        "low_raw": price.low_raw,
                        "close_raw": price.close_raw,
                    }
                )
        return grouped

    def list_corporate_actions(self, security_key: Any) -> Sequence[Mapping[str, Any]]:
        from sqlalchemy import select
        from app.models import CorporateAction

        security_id = int(security_key)
        with self._session_factory() as session:
            rows = session.scalars(
                select(CorporateAction)
                .where(CorporateAction.security_id == security_id)
                .order_by(CorporateAction.ex_rights_date)
            ).all()
            return [
                {
                    "ex_rights_date": row.ex_rights_date,
                    "cash_dividend_per_share": row.cash_dividend_per_share,
                    "stock_dividend_per_share": row.stock_dividend_per_share,
                }
                for row in rows
            ]

    def replace_adjusted_prices(
        self,
        security_key: Any,
        adjusted_rows: Sequence[Mapping[str, Any] | Any],
    ) -> None:
        from sqlalchemy import select
        from app.models import DailyPrice

        security_id = int(security_key)
        adjusted_by_date = {_read_attr(row, "date"): row for row in adjusted_rows}
        with self._session_factory() as session:
            with session.begin():
                prices = session.scalars(
                    select(DailyPrice)
                    .where(DailyPrice.security_id == security_id)
                    .order_by(DailyPrice.date)
                ).all()
                for price in prices:
                    adjusted = adjusted_by_date.get(price.date)
                    if adjusted is None:
                        continue
                    price.open_adj = _read_attr(adjusted, "open_adj")
                    price.high_adj = _read_attr(adjusted, "high_adj")
                    price.low_adj = _read_attr(adjusted, "low_adj")
                    price.close_adj = _read_attr(adjusted, "close_adj")

    def _upsert_security(self, session: Any, row: Mapping[str, Any]) -> Any:
        from sqlalchemy import select
        from app.models import Security, SecurityMarket

        symbol = _required(row, "symbol")
        security = session.scalar(select(Security).where(Security.symbol == symbol))
        values = {
            "symbol": symbol,
            "name": _required(row, "name"),
            "market": SecurityMarket(_required(row, "market")),
            "outstanding_shares": row.get("outstanding_shares"),
            "is_active": bool(row.get("is_active", True)),
        }
        if security is None:
            security = Security(**values)
            session.add(security)
            session.flush()
            return security
        for key, value in values.items():
            setattr(security, key, value)
        return security

    def _upsert_daily_price(self, session: Any, row: Mapping[str, Any]) -> None:
        from sqlalchemy import select
        from app.models import DailyPrice

        security = self._existing_security(session, row)
        price = session.scalar(
            select(DailyPrice).where(
                DailyPrice.security_id == security.id,
                DailyPrice.date == _required(row, "date"),
            )
        )
        values = {
            "security_id": security.id,
            "date": _required(row, "date"),
            "open_raw": _required(row, "open_raw"),
            "high_raw": _required(row, "high_raw"),
            "low_raw": _required(row, "low_raw"),
            "close_raw": _required(row, "close_raw"),
            "volume": _required(row, "volume"),
        }
        _upsert_model(session, price, DailyPrice, values)

    def _upsert_chip(self, session: Any, row: Mapping[str, Any]) -> None:
        from sqlalchemy import select
        from app.models import Chip

        security = self._existing_security(session, row)
        chip = session.scalar(
            select(Chip).where(
                Chip.security_id == security.id,
                Chip.date == _required(row, "date"),
            )
        )
        values = {
            "security_id": security.id,
            "date": _required(row, "date"),
            "foreign_net": row.get("foreign_net"),
            "investment_trust_net": row.get("investment_trust_net"),
            "dealer_net": row.get("dealer_net"),
            "margin_balance": row.get("margin_balance"),
            "short_balance": row.get("short_balance"),
            "securities_lending_balance": row.get("securities_lending_balance"),
        }
        _upsert_model(session, chip, Chip, values)

    def _upsert_broker_branch(self, session: Any, row: Mapping[str, Any]) -> None:
        from sqlalchemy import select
        from app.models import BrokerBranchTrade

        security = self._existing_security(session, row)
        trade = session.scalar(
            select(BrokerBranchTrade).where(
                BrokerBranchTrade.security_id == security.id,
                BrokerBranchTrade.broker_branch_code == _required(row, "broker_branch_code"),
                BrokerBranchTrade.date == _required(row, "date"),
            )
        )
        values = {
            "security_id": security.id,
            "date": _required(row, "date"),
            "broker_branch_code": _required(row, "broker_branch_code"),
            "broker_branch_name": row.get("broker_branch_name"),
            "buy_volume": _required(row, "buy_volume"),
            "sell_volume": _required(row, "sell_volume"),
        }
        _upsert_model(session, trade, BrokerBranchTrade, values)

    def _upsert_corporate_action(self, session: Any, row: Mapping[str, Any]) -> None:
        from sqlalchemy import select
        from app.models import CorporateAction

        security = self._existing_security(session, row)
        action = session.scalar(
            select(CorporateAction).where(
                CorporateAction.security_id == security.id,
                CorporateAction.ex_rights_date == _required(row, "ex_rights_date"),
            )
        )
        values = {
            "security_id": security.id,
            "ex_rights_date": _required(row, "ex_rights_date"),
            "cash_dividend_per_share": row.get("cash_dividend_per_share"),
            "stock_dividend_per_share": row.get("stock_dividend_per_share"),
            "capital_change_shares": row.get("capital_change_shares"),
            "capital_after_shares": row.get("capital_after_shares"),
        }
        _upsert_model(session, action, CorporateAction, values)

    def _existing_security(self, session: Any, row: Mapping[str, Any]) -> Any:
        from sqlalchemy import select
        from app.models import Security

        security = session.scalar(select(Security).where(Security.symbol == _required(row, "symbol")))
        if security is None:
            raise ValueError(
                f"security must exist before writing dependent row: "
                f"{row.get('market')}:{row.get('symbol')}"
            )
        return security


class Pipeline:
    """Fetch, parse, persist, and recalculate adjusted prices for one trading date."""

    def __init__(
        self,
        *,
        repository: IngestionRepository | None = None,
        sink: Callable[[str, Sequence[NormalizedRow]], None] | None = None,
        sources: Mapping[str, DataSource | type[DataSource] | SourceFactory] | None = None,
        discover: Callable[[], Mapping[str, type[DataSource]]] = registry.discover,
        clock: Clock | None = None,
        target_provider: Callable[[str, DataSource, dt.date], Any] | None = None,
        adjustment_writer: (
            Callable[[Any, Sequence[Mapping[str, Any] | Any], IngestionRepository], None] | None
        ) = None,
    ) -> None:
        self.repository = repository or InMemoryIngestionRepository()
        self._sink = sink
        self._provided_sources = sources
        self._discover = discover
        self._clock = clock or _taipei_now
        self._target_provider = target_provider or default_target_provider
        self._adjustment_writer = adjustment_writer

    def run(
        self,
        *,
        date: dt.date | None = None,
        source_names: Iterable[str] | None = None,
    ) -> PipelineRunResult:
        run_date = date or _as_date(self._clock())
        source_entries = self._ordered_sources()
        if source_names is not None:
            wanted = set(source_names)
            source_entries = [(name, source) for name, source in source_entries if name in wanted]

        results: dict[str, SourceRunResult] = {}
        for source_name, source_candidate in source_entries:
            result = self._run_source(source_name, source_candidate, run_date)
            results[source_name] = result

        adjustment_success = True
        adjustment_error: str | None = None
        adjusted_security_count = 0
        if all(result.success for result in results.values()):
            try:
                adjusted_security_count = self.recalculate_adjusted_prices()
            except Exception as exc:  # noqa: BLE001 - report per pipeline contract.
                adjustment_success = False
                adjustment_error = f"{type(exc).__name__}: {exc}"
                logger.exception("adjusted price recalculation failed")

        return PipelineRunResult(
            date=run_date,
            sources=results,
            adjustment_success=adjustment_success,
            adjustment_error=adjustment_error,
            adjusted_security_count=adjusted_security_count,
        )

    def recalculate_adjusted_prices(self) -> int:
        """Rewrite adjusted prices for every complete historical daily price series."""
        count = 0
        for security_key, price_rows in self.repository.list_price_series().items():
            prices = list(price_rows)
            if not prices:
                continue
            actions = list(self.repository.list_corporate_actions(security_key))
            adjusted = fill_adjusted_prices(prices, actions)
            if self._adjustment_writer is not None:
                self._adjustment_writer(security_key, adjusted, self.repository)
            else:
                self.repository.replace_adjusted_prices(security_key, adjusted)
            count += 1
        return count

    def _run_source(
        self,
        source_name: str,
        source_candidate: DataSource | type[DataSource] | SourceFactory,
        date: dt.date,
    ) -> SourceRunResult:
        try:
            source = _materialize_source(source_candidate)
            target = self._target_provider(source_name, source, date)
            rows = self._fetch_parse_rows(source, target, date)
            self._write_rows(source_name, rows)
            return SourceRunResult(
                name=source_name,
                success=True,
                fetched=True,
                row_count=len(rows),
            )
        except Exception as exc:  # noqa: BLE001 - failure is per-source state.
            logger.exception("ingestion source failed: %s", source_name)
            return SourceRunResult(
                name=source_name,
                success=False,
                fetched=True,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _write_rows(self, source_name: str, rows: Sequence[NormalizedRow]) -> None:
        if self._sink is not None:
            self._sink(source_name, rows)
        self.repository.write_rows(source_name, rows)

    def _fetch_parse_rows(self, source: DataSource, target: Any, date: dt.date) -> list[NormalizedRow]:
        if _is_target_iterable(target):
            targets = list(target)
            if not targets:
                return []
            rows: list[NormalizedRow] = []
            if hasattr(source, "fetch_many"):
                for raw in source.fetch_many(targets, date):  # type: ignore[attr-defined]
                    rows.extend(source.parse(raw))
                return rows
            for item in targets:
                rows.extend(source.parse(source.fetch(item, date)))
            return rows

        return list(source.parse(source.fetch(target, date)))

    def _ordered_sources(self) -> list[tuple[str, DataSource | type[DataSource] | SourceFactory]]:
        if self._provided_sources is None:
            discovered: Mapping[str, DataSource | type[DataSource] | SourceFactory] = self._discover()
        else:
            discovered = self._provided_sources
        return sorted(discovered.items(), key=lambda item: _source_order_key(item[0]))


def default_target_provider(source_name: str, source: DataSource, date: dt.date) -> Any:
    """Provide minimal adapter targets while keeping true fetch logic in sources."""
    if "corporate" in source_name or "mops" in source_name:
        return None
    if "broker_branch" in source_name or "broker" in source_name:
        return _broker_branch_targets(source_name, source, date)
    return None


def create_sqlalchemy_repository(*, database_url: str | None = None) -> SQLAlchemyIngestionRepository:
    """Build the production SQLAlchemy repository from an explicit or configured URL."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = database_url or _configured_database_url()
    engine = create_engine(url, future=True)
    return SQLAlchemyIngestionRepository(sessionmaker(bind=engine, future=True, expire_on_commit=False))


def create_production_pipeline(*, database_url: str | None = None) -> Pipeline:
    """Production pipeline: registered adapters plus persistent SQLAlchemy repository."""
    return Pipeline(repository=create_sqlalchemy_repository(database_url=database_url))


def _source_order_key(name: str) -> tuple[int, str]:
    normalized = name.lower()
    if any(hint in normalized for hint in SECURITY_SOURCE_HINTS):
        return (0, name)
    if any(hint in normalized for hint in DEPENDENT_SOURCE_HINTS):
        return (1, name)
    return (2, name)


def _materialize_source(candidate: DataSource | type[DataSource] | SourceFactory) -> DataSource:
    if isinstance(candidate, DataSource):
        return candidate
    if inspect.isclass(candidate):
        return candidate()
    source = candidate()
    if not isinstance(source, DataSource):
        raise TypeError(f"source factory returned non-DataSource: {source!r}")
    return source


def _broker_branch_targets(source_name: str, source: DataSource, date: dt.date) -> list[Any]:
    resolver = getattr(source, "resolve_universe", None)
    if resolver is None:
        raise ValueError(f"{source_name} requires target_provider or resolve_universe()")

    targets: list[Any] = []
    for market in ("listed", "otc"):
        market_targets = list(resolver(date, market))
        targets.extend(market_targets)
    if not targets:
        raise ValueError(f"{source_name} resolved no broker branch targets for {date.isoformat()}")
    return targets


def _configured_database_url() -> str:
    try:
        from app.config import get_settings
    except Exception:  # noqa: BLE001 - allow simple env based construction in tests.
        return os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://stocklab:stocklab@localhost:5432/stocklab",
        )
    return get_settings().database_url


def _row_kind(source_name: str, row: Mapping[str, Any]) -> str:
    row_type = row.get("row_type")
    if row_type == "security":
        return "security"
    if row_type == "corporate_action":
        return "corporate_action"
    if "broker_branch_code" in row:
        return "broker_branch"
    if _is_daily_price_row(row):
        return "daily_price"
    if "ex_rights_date" in row:
        return "corporate_action"
    if any(
        field in row
        for field in (
            "foreign_net",
            "investment_trust_net",
            "dealer_net",
            "margin_balance",
            "short_balance",
            "securities_lending_balance",
        )
    ):
        return "chip"
    if "security" in source_name.lower() or "mops" in source_name.lower():
        return "security"
    return "unknown"


def _row_write_order(row: Mapping[str, Any]) -> int:
    if row.get("row_type") == "security":
        return 0
    if "ex_rights_date" in row:
        return 1
    return 2


def _upsert_model(session: Any, instance: Any | None, model: type, values: Mapping[str, Any]) -> Any:
    if instance is None:
        instance = model(**values)
        session.add(instance)
        return instance
    for key, value in values.items():
        setattr(instance, key, value)
    return instance


def _required(row: Mapping[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _is_daily_price_row(row: Mapping[str, Any]) -> bool:
    return all(key in row for key in ("date", "open_raw", "high_raw", "low_raw", "close_raw"))


def _is_target_iterable(target: Any) -> bool:
    if target is None or isinstance(target, (str, bytes, Mapping)):
        return False
    return isinstance(target, Iterable)


def _security_key(row: Mapping[str, Any]) -> Any:
    if "security_id" in row:
        return row["security_id"]
    return (row.get("market"), row.get("symbol"))


def _read_attr(value: Mapping[str, Any] | Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)


def _taipei_now() -> dt.datetime:
    return dt.datetime.now(ZoneInfo("Asia/Taipei"))


def _as_date(value: dt.datetime | dt.date) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    return value
