"""Quarterly balance sheet and cash flow items from the MOPS XBRL archives (Issue #1083).

``t163sb04`` has the income statement only.  The quarterly archive that
``worker.quarterly_xbrl`` reads for EPS also holds every company's balance sheet and
cash flow statement; #1078 chose fifteen items (``FIELDS``) and checked them against
the summary pages (#1078 7207007046), and #1135 seventeen more: the current
investments, the interest-bearing debt and the net income (#1135 7234320089, decision
7234355063; Issue #1140).  ``quarterly_statements`` keeps them, research database
only (#1078 decision 7207067861).

Two commands:

- ``fetch_check_pages`` downloads, for each quarter, one market's MOPS balance sheet
  summary ``t163sb05`` (``CHECK_ENDPOINT``) into ``<dir>/t163sb05`` with its own
  manifest; the apply compares the archive with it.  At least
  ``quarterly_xbrl.REQUEST_INTERVAL_SECONDS`` between requests, none in
  ``quarterly_xbrl.QUIET_HOURS``; a page already there and whole is not asked again.
- ``apply_statements`` writes the quarters of the archive directory (the one
  ``fundamentals xbrl-fetch`` fills) into ``quarterly_statements``: one
  ``quarterly_statements_backfill`` run, one commit per quarter.  Before a quarter is
  written it is checked twice: the gross profit, operating income, net income and
  the parent's net income of every company ``t163sb04`` has against that row's
  ``data_json`` (``INCOME_CHECKS``), and the total assets and
  total equity against the quarter's ``t163sb05`` page.  One different company (or
  too many that cannot be compared) stops the command before that quarter.  Who gets
  a row: an instrument with a ``t163sb04`` row of the quarter whose archive EPS is
  the same (so a reused code's old company is never written onto the new one), and
  ``delisted``／``transferred`` instruments by ``quarterly_xbrl``'s window rule.  A
  rerun changes nothing.  Research database only, holding maintenance mode
  (``worker.cli``).

The archive is read with ``quarterly_xbrl``'s guards: members in memory, the limits
of ``ReadBudget``, a DOCTYPE or an entity refused before parsing.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    QuarterlyStatement,
    RawPayload,
)
from worker import quarterly_fundamentals as qf
from worker import sources
from worker import quarterly_xbrl as qx
from worker.foreign_issuers import foreign_issuers
from worker.quarterly_fundamentals import Quarter
from worker.sources import OfficialDataError, parse_number

SOURCE = qx.SOURCE  # mops_tifrs_zip, the one source of the table
MemberError = qx.MemberError
RUN_TYPE = "quarterly_statements_backfill"

# --- the items (#1078 7207007046) ------------------------------------------------------
INSTANT = "instant"  # the quarter-end balance
YEAR_TO_DATE = "ytd"  # 1 January to the quarter's end
# field: (context, element local names in order: 2013–2017 names, then 2018's)
FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "total_assets": (INSTANT, ("Assets",)),
    "total_liabilities": (INSTANT, ("Liabilities",)),
    # An individual report (``ir``／``er``) has no subsidiary: its Equity (FALLBACKS).
    "equity_parent": (INSTANT, ("EquityAttributableToOwnersOfParent",)),
    "equity_total": (INSTANT, ("Equity",)),
    "current_assets": (INSTANT, ("CurrentAssets",)),
    "current_liabilities": (INSTANT, ("CurrentLiabilities",)),
    "cash": (INSTANT, ("CashAndCashEquivalents",)),
    "receivables": (INSTANT, ("AccountsReceivableNet", "AccountsReceivable")),
    "inventories": (INSTANT, ("Inventories",)),
    "share_capital_common": (INSTANT, ("OrdinaryShare", "CommonStock")),
    "share_capital_total": (
        INSTANT,
        ("IssuedCapital", "CapitalStock", "Capital", "ShareCapital"),
    ),
    "cfo_ytd": (YEAR_TO_DATE, ("CashFlowsFromUsedInOperatingActivities",)),
    "capex_ytd": (
        YEAR_TO_DATE,
        (
            "AcquisitionOfPropertyPlantAndEquipment",
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        ),
    ),
    "gross_profit_ytd": (
        YEAR_TO_DATE,
        ("GrossProfitLossFromOperationsNet", "GrossProfit"),
    ),
    "operating_income_ytd": (
        YEAR_TO_DATE,
        ("NetOperatingIncomeLoss", "ProfitLossFromOperatingActivities"),
    ),
    # --- short-term investments, interest-bearing debt and net income (#1140) ---
    # Names and order as #1135 7234320089.  One line a field, no sum: the totals are
    # the research tools'.  Current financial assets, IFRS 9 (2018 on); 2013–2017's
    # FVTPL is spelt ``Fairvalue`` (a securities firm's ``FairValue``).
    "st_inv_fvtpl": (
        INSTANT,
        (
            "CurrentFinancialAssetsAtFairvalueThroughProfitOrLoss",
            "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
        ),
    ),
    "st_inv_fvoci": (
        INSTANT,
        ("CurrentFinancialAssetsAtFairValueThroughOtherComprehensiveIncome",),
    ),
    "st_inv_amortised": (INSTANT, ("CurrentFinancialAssetsAtAmortisedCost",)),
    # IAS 39's four current lines (2013–2017; none from 2019); the second names are a
    # securities firm's, the available-for-sale third one its 2018 name.
    "st_inv_afs": (
        INSTANT,
        (
            "CurrentAvailableForSaleFinancialAssets",
            "AvailableForSaleCurrentFinancialAssets",
            "CurrentFinancialAssetsAvailableforsale",
        ),
    ),
    "st_inv_htm": (
        INSTANT,
        (
            "CurrentHeldToMaturityFinancialAssets",
            "HeldToMaturityCurrentFinancialAssets",
        ),
    ),
    "st_inv_no_active_market": (INSTANT, ("CurrentBondInvestmentWithoutActiveMarket",)),
    "st_inv_at_cost": (INSTANT, ("CurrentFinancialAssetsAtCost",)),
    # A reference line: time deposits over three months before 2018, and restricted
    # deposits and other items that are no investment.
    "other_current_financial_assets": (INSTANT, ("OtherCurrentFinancialAssets",)),
    "short_term_borrowings": (INSTANT, ("ShorttermBorrowings",)),
    "short_term_bills_payable": (
        INSTANT,
        (
            "ShorttermNotesAndBillsPayable",
            "CommercialPaperPayable",
            "CurrentCommercialPapersIssuedAndCurrentPortionOfNoncurrentCommercialPapersIssued",
        ),
    ),
    # Holds the current bonds and borrowings.  A company that leaves it inside
    # 其他流動負債 has none: NULL, never worked out from that total.
    "long_term_current_portion": (INSTANT, ("LongtermLiabilitiesCurrentPortion",)),
    "bonds_payable_noncurrent": (
        INSTANT,
        (
            "BondsPayable",
            "BondsPayableIncludingOverseasBonds",
            "NoncurrentPortionOfNoncurrentBondsIssued",
        ),
    ),
    "long_term_borrowings": (INSTANT, ("LongtermBorrowings",)),
    # IFRS 16's 2019 names first: 2019Q2 has 89 companies filing the old name as 0
    # beside the new one.  2019Q2's 3202 files both non-zero; the first is kept.
    "lease_liabilities_current": (
        INSTANT,
        (
            "CurrentLeaseLiabilities",
            "CurrentFinanceLeaseLiabilities",
            "CurrentLeaseObligationsPayable",
        ),
    ),
    "lease_liabilities_noncurrent": (
        INSTANT,
        (
            "NoncurrentFinanceLeaseLiabilities",
            "NonCurrentLeaseLiabilities",
            "FinanceLeaseLiabilities",
            "NoncurrentLeaseObligationsPayable",
        ),
    ),
    # With non-controlling interests; an individual report's parent line is this one
    # (FALLBACKS).
    "net_income_ytd": (YEAR_TO_DATE, ("ProfitLoss",)),
    "net_income_parent_ytd": (
        YEAR_TO_DATE,
        ("ProfitLossAttributableToOwnersOfParent",),
    ),
}
# Lines a report format does not have (industry codes as quarterly_xbrl.INDUSTRY_FORMATS):
# banks, holdings and insurers do not split current items; no cost of sales.
_UNCLASSIFIED = frozenset({"basi", "fh", "ins"})
# Their investments and debts are the business (deposits, insurance liabilities), with
# no current line: none of #1140's balance sheet items (#1135 decision 7234355063).  A
# securities firm (``bd``) has them; its current FVTPL is its trading stock.
_DEBT_AND_INVESTMENTS = (
    "st_inv_fvtpl",
    "st_inv_fvoci",
    "st_inv_amortised",
    "st_inv_afs",
    "st_inv_htm",
    "st_inv_no_active_market",
    "st_inv_at_cost",
    "other_current_financial_assets",
    "short_term_borrowings",
    "short_term_bills_payable",
    "long_term_current_portion",
    "bonds_payable_noncurrent",
    "long_term_borrowings",
    "lease_liabilities_current",
    "lease_liabilities_noncurrent",
)
NOT_APPLICABLE: dict[str, frozenset[str]] = {
    "current_assets": _UNCLASSIFIED,
    "current_liabilities": _UNCLASSIFIED,
    "receivables": _UNCLASSIFIED,
    "inventories": _UNCLASSIFIED | {"bd"},
    "gross_profit_ytd": _UNCLASSIFIED | {"bd"},
    "operating_income_ytd": frozenset({"basi", "fh"}),
    **{name: _UNCLASSIFIED for name in _DEBT_AND_INVESTMENTS},
}
# Facts of a note taxonomy (a holding's OrdinaryShare is in ``tifrs-notes``) are not read.
NOTES_MARK = "notes"
# An individual report (``ir``／``er``) has no subsidiary, so no line for the parent's
# share: the parent's is the whole (its Equity, its ProfitLoss), read in the same context.
FALLBACKS: dict[str, str] = {
    "equity_parent": "Equity",
    "net_income_parent_ytd": "ProfitLoss",
}
_WANTED = {name for _context, names in FIELDS.values() for name in names} | set(
    FALLBACKS.values()
)
# The (element, context) pairs read: a fact of a wanted element in the other context
# is never a number we use (2013Q1 has a cash policy note tagged as a year-to-date
# CashAndCashEquivalents), so it is skipped, not parsed.
_SLOTS = {(name, context) for context, names in FIELDS.values() for name in names} | {
    (element, FIELDS[name][0]) for name, element in FALLBACKS.items()
}

# --- the checks -------------------------------------------------------------------------
# The fundamental_snapshots rows naming today's company of a code: t163sb04, and the
# daily's OpenAPI snapshot (t187ap14), which writes a quarter first (2026Q2 on).
SNAPSHOT_SOURCE = "mops_fundamental"
IDENTITY_SOURCES = {qx.T163SB04_SOURCE: "t163sb04_eps", SNAPSHOT_SOURCE: "snapshot_eps"}
# Their data_json columns (thousand NTD) the archive's YTD must equal, the first of a
# field's names with a number (each format names a line its own way; #1135
# 7234320089); the snapshot has no gross profit nor net income.
INCOME_CHECKS: dict[str, dict[str, tuple[str, ...]]] = {
    qx.T163SB04_SOURCE: {
        "gross_profit_ytd": ("營業毛利（毛損）淨額",),
        "operating_income_ytd": ("營業利益（損失）",),
        "net_income_ytd": (
            "本期淨利（淨損）",
            "本期稅後淨利（淨損）",
            "繼續營業單位本期純益（純損）",
        ),
        "net_income_parent_ytd": (
            "淨利（淨損）歸屬於母公司業主",
            "淨利（損）歸屬於母公司業主",
        ),
    },
    SNAPSHOT_SOURCE: {"operating_income_ytd": ("營業利益",)},
}
# A page value that is blank (``--``) or a column the page lacks is not compared, but
# t163sb04 prints the parent's net income for every consolidated report: only an
# individual one's is ``--`` (its parent's is ProfitLoss, FALLBACKS; #1135
# 7234320089), so a consolidated report's ``--`` there is a difference.
CONSOLIDATED_PAGE_LINES = frozenset({"net_income_parent_ytd"})
# t163sb05 columns (each format names them differently) the quarter-end must equal.
BALANCE_CHECKS: dict[str, tuple[str, ...]] = {
    "total_assets": ("資產總額", "資產總計", "資產合計"),
    "equity_total": ("權益總額", "權益總計", "權益合計"),
}
# XBRL is in NTD (decimals=-3), the pages in thousands: one thousand of rounding.
CHECK_TOLERANCE = Decimal(1)
CHECK_MISSING_LIMIT = qx.CHECK_MISSING_LIMIT

CHECK_ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb05"
CHECK_DIR = "t163sb05"
CHECK_MANIFEST = "manifest.json"

GROUPS = ("active", "delisted", "transferred", "other")


def check_market(quarter: Quarter) -> str:
    """The one market whose t163sb05 page checks QUARTER: listed and OTC alternate."""

    return "sii" if (quarter.year * 4 + quarter.quarter) % 2 == 0 else "otc"


def check_page_name(quarter: Quarter) -> str:
    return f"{quarter.label}-{check_market(quarter)}.html"


# --- one instance -------------------------------------------------------------------------


def _instants(root: ElementTree.Element, quarter: Quarter) -> set[str]:
    """Ids of the quarter-end instant contexts without dimensions."""

    end = quarter.period_end.isoformat()
    found = set()
    for element in root.iter():
        if qx._local(element.tag) != "context":
            continue
        names = {qx._local(child.tag): child for child in element.iter()}
        if "segment" in names or "scenario" in names:
            continue
        instant = names.get("instant")
        if instant is not None and (instant.text or "").strip() == end:
            found.add(element.get("id") or "")
    return found


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


@dataclass(frozen=True)
class Statement:
    """One member's items in NTD, the element and context each came from, and its EPS."""

    values: dict[str, Decimal | None]
    elements: dict[str, list[str]]
    not_applicable: list[str]
    eps: float | None

    def thousands(self, name: str) -> float | None:
        value = self.values.get(name)
        return None if value is None else float(value / 1000)

    @property
    def empty(self) -> bool:
        return all(value is None for value in self.values.values())


def parse_statement(
    data: bytes, quarter: Quarter, *, industry: str, kind: str
) -> Statement:
    """The ``FIELDS`` of one instance (``.xml`` or inline ``.html``).

    Only contexts without dimensions: the quarter-end instant and the year to date,
    and of each element only the one its field reads.  Facts of one element and
    context must agree, else MemberError.  An item the
    INDUSTRY's format has no line for is None and listed in ``not_applicable``.
    """

    root = qx.parse_instance(data)
    eps, _context = qx.eps_of(root, quarter)
    contexts = {
        **{context: INSTANT for context in _instants(root, quarter)},
        **{context: YEAR_TO_DATE for context in qx._year_to_date(root, quarter)},
    }
    facts: dict[tuple[str, str], dict[Decimal | None, str]] = {}
    for element in root.iter():
        local = qx._local(element.tag)
        if local == "nonFraction":
            name = element.get("name") or ""
            prefix, _, local = name.rpartition(":")
            if local not in _WANTED or NOTES_MARK in prefix:
                continue
            reader = qx._inline_value
        elif local in _WANTED and element.get("contextRef") is not None:
            if NOTES_MARK in _namespace(element.tag):
                continue
            reader = qx._plain_value
        else:
            continue
        context = element.get("contextRef") or ""
        slot = contexts.get(context)
        if slot is None or (local, slot) not in _SLOTS:
            continue
        facts.setdefault((local, slot), {})[reader(element)] = context
    values: dict[str, Decimal | None] = {}
    elements: dict[str, list[str]] = {}
    for (local, slot), found in facts.items():
        known = {value for value in found if value is not None}
        if len(known) > 1:
            raise MemberError(
                f"{local} {slot} facts disagree: {sorted(found.values())}"
            )
    for name, (slot, candidates) in FIELDS.items():
        values[name] = None
        for local in candidates:
            found = facts.get((local, slot), {})
            known = [value for value in found if value is not None]
            if known:
                values[name] = known[0]
                elements[name] = [local, found[known[0]]]
                break
    for name, local in FALLBACKS.items():
        if values[name] is not None or kind == "cr":
            continue
        found = facts.get((local, FIELDS[name][0]), {})
        known = [value for value in found if value is not None]
        if known:
            values[name] = known[0]
            elements[name] = [local, found[known[0]]]
    not_applicable = sorted(
        name for name, industries in NOT_APPLICABLE.items() if industry in industries
    )
    for name in not_applicable:
        values[name] = None
        elements.pop(name, None)
    return Statement(values, elements, not_applicable, eps)


# --- the t163sb05 page --------------------------------------------------------------------


def _amount(text: Any) -> Decimal | None:
    """A page's amount (thousand NTD; ``1,234``, ``-5``); None for a blank or ``--``."""

    number = parse_number(text)
    return None if number is None else Decimal(repr(number))


def parse_check_page(
    html: str, market: str, quarter: Quarter
) -> dict[str, dict[str, Decimal | None]]:
    """Every company's ``BALANCE_CHECKS`` (thousand NTD) on one t163sb05 page."""

    label = f"MOPS t163sb05 {market} {quarter.label}"
    upper = html.upper()
    if any(marker.upper() in upper for marker in qf.BLOCK_MARKERS):
        raise OfficialDataError(f"{label} was refused by the source")
    parser = qf._ReportParser()
    parser.feed(html)
    parser.close()
    title = " ".join(parser.titles)
    reports = [table for table in parser.tables if "hasBorder" in table.css_class]
    if not reports:
        raise OfficialDataError(f"{label} has no report table")
    if qf.MARKET_TITLES[market] not in title:
        raise OfficialDataError(f"{label} answered another market: {title!r}")
    named = [
        n for n, words in qf.QUARTER_TITLES.items() if any(w in title for w in words)
    ]
    if quarter.quarter not in named:
        raise OfficialDataError(f"{label} answered another quarter: {title!r}")
    result: dict[str, dict[str, Decimal | None]] = {}
    for table in reports:
        if not table.rows:
            raise OfficialDataError(f"{label} has an empty table")
        headers = ["".join(cell.split()) for cell in table.rows[0]]
        if headers[:2] != ["公司代號", "公司名稱"]:
            raise OfficialDataError(f"{label} columns changed: {headers[:3]!r}")
        columns: dict[str, int] = {}
        for name, choices in BALANCE_CHECKS.items():
            found = [i for i, header in enumerate(headers) if header in choices]
            if len(found) != 1:
                raise OfficialDataError(f"{label} has no single {name} column")
            columns[name] = found[0]
        for cells in table.rows[1:]:
            if len(cells) != len(headers):
                raise OfficialDataError(f"{label} has a malformed row: {cells[:2]!r}")
            symbol = cells[0].strip()
            if not symbol or symbol in result:
                raise OfficialDataError(
                    f"{label} has a blank or repeated code {symbol!r}"
                )
            result[symbol] = {}
            for name, index in columns.items():
                result[symbol][name] = _amount(cells[index])
    if not result:
        raise OfficialDataError(f"{label} lists no company")
    return result


def read_check_manifest(directory: Path) -> dict[str, Any]:
    path = directory / CHECK_DIR / CHECK_MANIFEST
    if not path.exists():
        return {"quarters": {}}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or not isinstance(stored.get("quarters"), dict):
        raise ValueError(f"{path} is not a manifest")
    return stored


def _write_check_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    path = directory / CHECK_DIR / CHECK_MANIFEST
    temporary = path.with_name(f".{CHECK_MANIFEST}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _whole_page(directory: Path, quarter: Quarter, manifest: dict[str, Any]) -> bool:
    entry = manifest["quarters"].get(quarter.label)
    path = directory / CHECK_DIR / check_page_name(quarter)
    if not entry or not path.exists() or entry.get("file") != path.name:
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == entry.get("sha256")


def post_once(url: str, form: dict[str, str]) -> str:
    """One POST of the page; anything but a 200 is OfficialDataError, never asked again.

    The same rule as ``xbrl-fetch`` (``quarterly_fundamentals.fetch_html`` retries
    transient failures, so its request count is not the requests sent; review of PR
    #1084).  Through ``sources._throttle_official_host`` as every official request.
    """

    sources._throttle_official_host(url)
    try:
        response = httpx.post(
            url, data=form, timeout=60.0, headers={"User-Agent": qx.USER_AGENT}
        )
    except httpx.HTTPError as exc:
        raise OfficialDataError(f"{url}: {exc!r}") from exc
    if response.status_code != 200:
        raise OfficialDataError(f"{url}: HTTP {response.status_code}")
    return response.text


def fetch_check_pages(
    directory: Path,
    start: Quarter,
    end: Quarter,
    *,
    fetcher: Callable[[str, dict[str, str]], str] = post_once,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """One t163sb05 page per quarter into DIRECTORY/t163sb05; never asks for one it has."""

    targets = qx.quarters_between(start, end)
    (directory / CHECK_DIR).mkdir(parents=True, exist_ok=True)
    manifest = read_check_manifest(directory)
    result: dict[str, Any] = {"downloaded": [], "kept": [], "failed": {}, "requests": 0}
    failures_in_a_row = 0
    last_request: float | None = None
    stopped: str | None = None
    for quarter in targets:
        if _whole_page(directory, quarter, manifest):
            result["kept"].append(quarter.label)
            continue
        if last_request is not None:
            wait = qx.REQUEST_INTERVAL_SECONDS - (clock() - last_request)
            if wait > 0:
                sleep(wait)
        moment = now()
        if qx.in_quiet_hours(moment):
            stopped = (
                f"quiet hours at {moment.astimezone(qx.TAIPEI):%H:%M} Taipei before "
                f"{quarter.label}; run the same command again after them"
            )
            break
        market = check_market(quarter)
        form = qf.request_form(market, quarter)
        last_request = clock()
        result["requests"] += 1
        try:
            html = fetcher(CHECK_ENDPOINT, form)
            companies = parse_check_page(html, market, quarter)
        except OfficialDataError as exc:
            result["failed"][quarter.label] = str(exc)
            failures_in_a_row += 1
            if failures_in_a_row >= qx.ABORT_AFTER_FAILURES:
                stopped = (
                    f"{failures_in_a_row} quarters failed in a row at {quarter.label}; "
                    "停下來問"
                )
                break
            continue
        failures_in_a_row = 0
        data = html.encode("utf-8")
        path = directory / CHECK_DIR / check_page_name(quarter)
        path.write_bytes(data)
        manifest["quarters"][quarter.label] = {
            "url": CHECK_ENDPOINT,
            "form": form,
            "market": market,
            "file": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "companies": len(companies),
            "fetched_at": moment.astimezone(timezone.utc).isoformat(),
        }
        _write_check_manifest(directory, manifest)
        result["downloaded"].append(quarter.label)
    if stopped and failures_in_a_row >= qx.ABORT_AFTER_FAILURES:
        status = "failed"
    elif stopped or result["failed"]:
        status = "partial"
    else:
        status = "success"
    return {
        "status": status,
        "start_quarter": targets[0].label,
        "end_quarter": targets[-1].label,
        "stopped": stopped,
        **result,
    }


# --- apply ----------------------------------------------------------------------------------


@dataclass
class QuarterCounts:
    members: int = 0
    companies: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    would_insert: int = 0
    existing: int = 0  # a dry run's rows already there (not compared)
    not_in_db: int = 0
    # An active instrument with neither a t163sb04 nor a snapshot row of the quarter.
    no_identity_row: int = 0
    eps_different: int = 0
    outside_window: int = 0
    excluded: int = 0
    excluded_already_written: int = 0
    unknown_format: int = 0
    unreadable: int = 0
    no_items: int = 0
    income_same: int = 0
    income_different: int = 0
    income_missing: int = 0
    balance_same: int = 0
    balance_different: int = 0
    balance_missing: int = 0
    errors: list[str] = field(default_factory=list)
    examples: list[list[Any]] = field(default_factory=list)
    # The income check by the row compared: {source: {"same": n, "different": n}}
    income_by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    # group: {"rows": n, "rules": {target_rule: n}, "applicable": {field: n},
    # "missing": {field: n}}
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_row(self, group: str, rule: str, statement: Statement) -> None:
        item = self.groups.setdefault(
            group, {"rows": 0, "rules": {}, "applicable": {}, "missing": {}}
        )
        item["rows"] += 1
        item["rules"][rule] = item["rules"].get(rule, 0) + 1
        for name in FIELDS:
            if name in statement.not_applicable:
                continue
            item["applicable"][name] = item["applicable"].get(name, 0) + 1
            if statement.values.get(name) is None:
                item["missing"][name] = item["missing"].get(name, 0) + 1


class MismatchError(qx.ArchiveError):
    """The archive and a summary page differ on a company both have."""

    def __init__(self, quarter: Quarter, counts: QuarterCounts, what: str) -> None:
        super().__init__(
            f"{quarter.label}: archive and {what} differ (income same "
            f"{counts.income_same}, different {counts.income_different}, missing "
            f"{counts.income_missing}, eps different {counts.eps_different}; balance same {counts.balance_same}, different "
            f"{counts.balance_different}, missing {counts.balance_missing}); 停下來問"
        )
        self.counts = counts


def _differs(stored: Decimal | None, read: float | None) -> bool:
    """A page's value against the archive's (thousand NTD); a page blank is not compared."""

    if stored is None:
        return False
    if read is None:
        return True
    return abs(stored - Decimal(str(read))) > CHECK_TOLERANCE


def _page_number(
    details: dict[str, Any] | None, columns: tuple[str, ...]
) -> Decimal | None:
    """The first of COLUMNS the page has a number in (thousand NTD)."""

    for column in columns:
        number = _amount((details or {}).get(column))
        if number is not None:
            return number
    return None


def _income_differs(
    statement: Statement,
    kind: str,
    name: str,
    details: dict[str, Any] | None,
    columns: tuple[str, ...],
) -> bool:
    stored = _page_number(details, columns)
    if (
        stored is None
        and kind == "cr"
        and name in CONSOLIDATED_PAGE_LINES
        and any(column in (details or {}) for column in columns)
    ):
        return True
    return _differs(stored, statement.thousands(name))


def _group(instrument: Instrument) -> str:
    return instrument.status if instrument.status in GROUPS else "other"


def apply_statement_quarter(
    db: Session,
    run: IngestionRun | None,
    quarter: Quarter,
    data: bytes,
    digest: str,
    fetched_at: datetime,
    page: dict[str, dict[str, Decimal | None]],
    *,
    page_label: str = "t163sb05",
    excluded: frozenset[int] = frozenset(),
    foreign: dict[int, str] | None = None,
) -> QuarterCounts:
    """Check one quarter against t163sb04 and t163sb05, then write it (``run`` None: dry run).

    Raises ArchiveError when the archive cannot be trusted and ``MismatchError`` when
    a summary page and the archive differ; nothing of the quarter is written then.
    ``foreign`` (``foreign_issuers``; read here when None) gives foreign issuers
    their own Q2 deadline (#1101), as ``xbrl-apply`` does.
    """

    counts = QuarterCounts()
    if foreign is None:
        foreign = foreign_issuers(db)
    fiscal_period = f"Q{quarter.quarter}"
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise qx.ArchiveError(f"{quarter.label} is not a whole zip: {exc}") from exc
    with archive:
        members = qx.archive_members(archive, quarter)
        counts.members = len(members)
        chosen = qx.best_members(members)
        counts.companies = len(chosen)
        budget = qx.ReadBudget(qx.MAX_TOTAL_BYTES)
        parsed: dict[str, tuple[qx.Member, Statement | None, str]] = {}

        def read(symbol: str) -> tuple[qx.Member, Statement | None, str] | None:
            if symbol in parsed:
                return parsed[symbol]
            member = chosen.get(symbol)
            if member is None:
                return None
            content = budget.read(archive, member)
            try:
                statement = parse_statement(
                    content, quarter, industry=member.industry, kind=member.kind
                )
            except MemberError as exc:
                counts.unreadable += 1
                counts.errors.append(f"{member.name}: {exc}")
                parsed[symbol] = (member, None, "")
                return parsed[symbol]
            parsed[symbol] = (member, statement, hashlib.sha256(content).hexdigest())
            return parsed[symbol]

        # 1. Income statement items against t163sb04 (or the snapshot), on the
        #    instruments they have.
        sb04 = db.execute(
            select(
                Instrument.id,
                Instrument.symbol,
                FundamentalSnapshot.eps,
                FundamentalSnapshot.data_json,
                FundamentalSnapshot.source,
            )
            .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
            .where(
                FundamentalSnapshot.source.in_(IDENTITY_SOURCES),
                FundamentalSnapshot.period_end == quarter.period_end,
                FundamentalSnapshot.fiscal_period == fiscal_period,
            )
        ).all()
        same_eps: dict[int, bool] = {}
        rules: dict[int, str] = {}
        for instrument_id, symbol, stored_eps, details, source in sb04:
            rules[instrument_id] = IDENTITY_SOURCES[source]
            found = read(symbol)
            statement = found[1] if found else None
            kind = found[0].kind if found else ""
            if statement is None or statement.eps is None or stored_eps is None:
                counts.income_missing += 1
                same_eps[instrument_id] = False
                continue
            if statement.eps != stored_eps:
                # Another company under the code: not compared, not written.
                counts.eps_different += 1
                same_eps[instrument_id] = False
                continue
            same_eps[instrument_id] = True
            different = [
                name
                for name, columns in INCOME_CHECKS[source].items()
                # The snapshot prints a 營業利益 for formats without the line.
                if not (source == SNAPSHOT_SOURCE and name in statement.not_applicable)
                and _income_differs(statement, kind, name, details, columns)
            ]
            tally = counts.income_by_source.setdefault(
                source, {"same": 0, "different": 0}
            )
            if different:
                counts.income_different += 1
                tally["different"] += 1
                counts.examples.append([source, symbol, different])
            else:
                counts.income_same += 1
                tally["same"] += 1
        compared = len(sb04)
        if (
            counts.income_different
            or counts.income_same == 0
            or counts.income_missing > compared * CHECK_MISSING_LIMIT
            # Many EPS differences are not reused codes but a source gone wrong.
            or counts.eps_different > compared * CHECK_MISSING_LIMIT
        ):
            raise MismatchError(quarter, counts, "t163sb04／snapshot")

        # 2. Total assets and equity against the quarter's t163sb05 page.
        for symbol, stored in sorted(page.items()):
            found = read(symbol)
            statement = found[1] if found else None
            if statement is None or statement.empty:
                counts.balance_missing += 1
                continue
            different = [
                name
                for name in BALANCE_CHECKS
                if _differs(stored.get(name), statement.thousands(name))
            ]
            if different:
                counts.balance_different += 1
                counts.examples.append([page_label, symbol, different])
            else:
                counts.balance_same += 1
        if (
            counts.balance_different
            or counts.balance_same == 0
            or counts.balance_missing > len(page) * CHECK_MISSING_LIMIT
        ):
            raise MismatchError(quarter, counts, page_label)

        # 3. The rows.
        instruments: dict[str, list[Instrument]] = {}
        for item in db.scalars(
            select(Instrument).where(Instrument.instrument_type.in_(qx.TARGET_TYPES))
        ):
            instruments.setdefault(item.symbol, []).append(item)
        existing = {
            row.instrument_id: row
            for row in db.scalars(
                select(QuarterlyStatement).where(
                    QuarterlyStatement.period_end == quarter.period_end,
                    QuarterlyStatement.fiscal_period == fiscal_period,
                )
            )
        }
        first_seen = qx._taipei_day(fetched_at)
        deadlines: dict[str, tuple[date, str]] = {}
        raw: RawPayload | None = None
        for symbol in sorted(chosen):
            member = chosen[symbol]
            candidates = instruments.get(symbol, [])
            if not candidates:
                counts.not_in_db += 1
                continue
            report_format = qx.report_format_of(member.industry, quarter)
            if report_format is None:
                counts.unknown_format += 1
                continue
            for instrument in sorted(candidates, key=lambda item: item.id):
                if instrument.id in same_eps:
                    if not same_eps[instrument.id]:
                        continue  # counted by the check
                    rule = rules[instrument.id]
                elif instrument.status in qx.TARGET_STATUSES:
                    rule = "bar_window"
                else:
                    counts.no_identity_row += 1
                    continue
                if instrument.id in excluded:
                    counts.excluded += 1
                    if instrument.id in existing:
                        counts.excluded_already_written += 1
                    continue
                if rule == "bar_window" and not qx._bar_within(
                    db, instrument.id, quarter
                ):
                    counts.outside_window += 1
                    continue
                found = read(symbol)
                if found is None or found[1] is None:
                    continue  # unreadable, counted by read
                _member, statement, member_sha = found
                if statement.empty:
                    # No quarter-end context (a non-calendar fiscal year): nothing read.
                    counts.no_items += 1
                    continue
                counts.add_row(_group(instrument), rule, statement)
                row = existing.get(instrument.id)
                if run is None:
                    if row is None:
                        counts.would_insert += 1
                    else:
                        counts.existing += 1
                    continue
                if raw is None:
                    raw = qx._raw_row(db, run, quarter, data, digest, fetched_at)
                foreign_basis = foreign.get(instrument.id)
                key = qf.deadline_key(report_format, quarter, foreign_basis)
                if key not in deadlines:
                    deadlines[key] = qf.roll_to_session(
                        db,
                        qf.nominal_deadline(
                            report_format, quarter, foreign_basis is not None
                        ),
                    )
                deadline, calendar = deadlines[key]
                available, basis = qf.availability(deadline, first_seen)
                details = {
                    "member": member.name,
                    "member_sha256": member_sha,
                    "archive_sha256": digest,
                    "industry_code": member.industry,
                    "report_kind": member.kind,
                    "report_format": report_format,
                    "eps": statement.eps,
                    "target_rule": rule,
                    "elements": statement.elements,
                    "not_applicable": statement.not_applicable,
                    "announcement_basis": basis,
                    "statutory_deadline": deadline.isoformat(),
                    "deadline_calendar": calendar,
                    **qf.deadline_details(quarter, foreign_basis),
                }
                outcome, existing[instrument.id] = _write_row(
                    db, row, instrument, quarter, available, statement, details, raw.id
                )
                setattr(counts, outcome, getattr(counts, outcome) + 1)
    return counts


def _write_row(
    db: Session,
    row: QuarterlyStatement | None,
    instrument: Instrument,
    quarter: Quarter,
    available: date,
    statement: Statement,
    details: dict[str, Any],
    raw_payload_id: int,
) -> tuple[str, QuarterlyStatement]:
    """Insert, update or keep one row: ``inserted``, ``updated`` or ``unchanged``, and it.

    The raw payload id and ``collected_at`` change only with the values, so a rerun
    changes nothing.
    """

    amounts = {name: statement.thousands(name) for name in FIELDS}
    if row is None:
        row = QuarterlyStatement(
            instrument_id=instrument.id,
            period_end=quarter.period_end,
            fiscal_period=f"Q{quarter.quarter}",
            announcement_date=available,
            **amounts,
            source=SOURCE,
            raw_payload_id=raw_payload_id,
            data_as_of=quarter.period_end,
            collected_at=utcnow(),
            data_json=details,
        )
        db.add(row)
        db.flush()
        return "inserted", row
    if (
        row.announcement_date == available
        and all(getattr(row, name) == value for name, value in amounts.items())
        and row.data_json == details
        and row.source == SOURCE
    ):
        return "unchanged", row
    row.announcement_date = available
    for name, value in amounts.items():
        setattr(row, name, value)
    row.source = SOURCE
    row.raw_payload_id = raw_payload_id
    row.data_as_of = quarter.period_end
    row.collected_at = utcnow()
    row.data_json = details
    return "updated", row


def _summary(counts: QuarterCounts) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(counts).items()
        if name not in {"errors", "examples"}
    } | {"errors": counts.errors[:20], "examples": counts.examples[:20]}


def apply_statements(
    db: Session,
    directory: Path,
    start: Quarter,
    end: Quarter,
    *,
    dry_run: bool = False,
    excluded: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Write the quarters of DIRECTORY's archives; stops at the first untrusted quarter."""

    targets = qx.quarters_between(start, end)
    manifest = qx.read_manifest(directory)
    pages = read_check_manifest(directory)
    absent = [
        quarter.label
        for quarter in targets
        if quarter.label not in manifest["quarters"]
        or not (directory / qx.archive_name(quarter)).exists()
    ]
    if absent:
        return {"status": "failed", "error": f"not downloaded: {', '.join(absent)}"}
    no_page = [
        quarter.label
        for quarter in targets
        if quarter.label not in pages["quarters"]
        or not (directory / CHECK_DIR / check_page_name(quarter)).exists()
    ]
    if no_page:
        return {
            "status": "failed",
            "error": f"no t163sb05 page (statements-check-fetch): {', '.join(no_page)}",
        }
    run: IngestionRun | None = None
    if not dry_run:
        now = utcnow()
        run = IngestionRun(
            run_type=RUN_TYPE,
            source="official",
            run_date=qx._taipei_day(now),
            status="running",
            started_at=now,
            data_as_of=targets[-1].period_end.isoformat(),
            metadata_json={
                "start_quarter": targets[0].label,
                "end_quarter": targets[-1].label,
                "directory": str(directory),
                "excluded_instruments": sorted(excluded),
            },
        )
        db.add(run)
        db.commit()
    coverage: dict[str, Any] = {}
    try:
        aborted = _apply_each(
            db, run, directory, targets, manifest, pages, coverage, excluded
        )
    except Exception as exc:
        db.rollback()
        if run is not None:
            run.status = "failed"
            run.error = f"error: {exc!r}"
            run.finished_at = utcnow()
            run.metadata_json = {
                **run.metadata_json,
                "coverage_manifest": dict(coverage),
            }
            flag_modified(run, "metadata_json")
            db.commit()
        raise
    status = "failed" if aborted else "success"
    if run is not None:
        run.status = status
        run.error = aborted
        run.finished_at = utcnow()
        db.commit()
    totals: dict[str, int] = {}
    for item in coverage.values():
        for name, value in item.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[name] = totals.get(name, 0) + value
    changed = totals.get("inserted", 0) + totals.get("updated", 0)
    return {
        "status": status,
        "dry_run": dry_run,
        "run_id": run.id if run is not None else None,
        "start_quarter": targets[0].label,
        "end_quarter": targets[-1].label,
        "aborted": aborted,
        "changed": changed,
        "totals": totals,
        "quarters": coverage,
    }


def _apply_each(
    db: Session,
    run: IngestionRun | None,
    directory: Path,
    targets: list[Quarter],
    manifest: dict[str, Any],
    pages: dict[str, Any],
    coverage: dict[str, Any],
    excluded: frozenset[int],
) -> str | None:
    aborted: str | None = None
    foreign = foreign_issuers(db)
    for quarter in targets:
        entry = manifest["quarters"][quarter.label]
        page_entry = pages["quarters"][quarter.label]
        path = directory / qx.archive_name(quarter)
        page_path = directory / CHECK_DIR / check_page_name(quarter)
        started = time.monotonic()
        try:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry.get("sha256"):
                raise qx.ArchiveError(
                    f"{quarter.label}: {path.name} sha256 {digest} is not the manifest's"
                )
            page_data = page_path.read_bytes()
            page_digest = hashlib.sha256(page_data).hexdigest()
            if page_digest != page_entry.get("sha256"):
                raise qx.ArchiveError(
                    f"{quarter.label}: {page_path.name} is not the t163sb05 manifest's"
                )
            market = check_market(quarter)
            try:
                page = parse_check_page(page_data.decode("utf-8"), market, quarter)
            except OfficialDataError as exc:
                raise qx.ArchiveError(str(exc)) from exc
            counts = apply_statement_quarter(
                db,
                run,
                quarter,
                data,
                digest,
                datetime.fromisoformat(entry["fetched_at"]),
                page,
                page_label=f"t163sb05 {market}",
                excluded=excluded,
                foreign=foreign,
            )
        except MismatchError as exc:
            db.rollback()
            coverage[quarter.label] = {"status": "failed", **_summary(exc.counts)}
            aborted = str(exc)
        except qx.ArchiveError as exc:
            db.rollback()
            coverage[quarter.label] = {"status": "failed", "error": str(exc)}
            aborted = str(exc)
        else:
            coverage[quarter.label] = {
                "status": "success",
                "archive_sha256": digest,
                "check_page": page_path.name,
                "check_page_sha256": page_digest,
                "seconds": round(time.monotonic() - started, 1),
                **_summary(counts),
            }
        if run is not None:
            run.metadata_json = {
                **run.metadata_json,
                "coverage_manifest": dict(coverage),
            }
            flag_modified(run, "metadata_json")
            run.records = sum(
                item.get("inserted", 0) + item.get("updated", 0)
                for item in coverage.values()
            )
            db.commit()
        if aborted:
            break
    return aborted


# --- commands -------------------------------------------------------------------------------


def run_check_fetch(directory: str, start: str, end: str) -> dict[str, Any]:
    try:
        return fetch_check_pages(
            Path(directory), Quarter.parse(start), Quarter.parse(end)
        )
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}


def run_statements_apply(
    directory: str,
    start: str,
    end: str,
    *,
    dry_run: bool = False,
    exclude_file: str | None = None,
) -> dict[str, Any]:
    try:
        targets = (Quarter.parse(start), Quarter.parse(end))
        excluded: frozenset[int] = frozenset()
        if exclude_file:
            loaded = json.loads(Path(exclude_file).read_text(encoding="utf-8"))
            if not isinstance(loaded, list) or not all(
                isinstance(item, int) for item in loaded
            ):
                raise ValueError(f"{exclude_file} is not a list of instrument ids")
            excluded = frozenset(loaded)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        try:
            return apply_statements(
                db, Path(directory), *targets, dry_run=dry_run, excluded=excluded
            )
        except ValueError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc)}
