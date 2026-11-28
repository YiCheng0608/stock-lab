"""Which instruments are foreign issuers (第一上市（櫃）公司), from stored data (#1101).

Their Q2 report is due two months after the half year, not 45 days
(公開發行公司財務報告及營運情形公告申報特殊適用範圍辦法 第3條第3款, from the
2021 fiscal year), so the quarterly backfill needs to know them.  Official
markers come first, all attached to the instrument id so a rename (``F-`` →
``-KY``) does not matter:

- ``t21sc03_foreign_page``: a ``monthly_revenues`` row from the MOPS 營業收入
  統計表 foreign-company page (``mops_t21sc03``, ``data_json.page = 1``);
- ``t05st10_foreign_exempt``: the single-company revenue page answered
  「外國發行人免申報本項資訊」 (``revenue company-classify``／``company-backfill``
  runs, delisted companies the ``_1`` page no longer lists);
- ``t05st10_functional_currency``: a single-company revenue row read from the
  dual-currency (新台幣／功能性貨幣) layout only foreign issuers have.

An instrument with none of them is a foreign issuer when its name, NFKC
without spaces, ends with ``-KY`` or ``-KY創`` or starts with ``F-``
(``name_suffix``, #1101 決定 7213332342): only delisted companies the
monthly sources never answered are left to it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionRun, Instrument, MonthlyRevenue

# The monthly modules' names, repeated: they import quarterly_fundamentals,
# which imports this module (a test keeps them equal).
PAGE_SOURCE = "mops_t21sc03"  # monthly_revenue.SOURCE
COMPANY_SOURCE = "mops_t05st10"  # monthly_revenue_company.SOURCE_COMPANY
COMPANY_RUN_TYPES = ("revenue_company_classify", "revenue_company_backfill")
FOREIGN_EXEMPT = "foreign_exempt"  # monthly_revenue_company.FOREIGN_EXEMPT
FOREIGN_PAGE = 1
FUNCTIONAL_CURRENCY_KEY = "功能性貨幣"
BASIS_PAGE = "t21sc03_foreign_page"
BASIS_EXEMPT = "t05st10_foreign_exempt"
BASIS_CURRENCY = "t05st10_functional_currency"
BASIS_NAME = "name_suffix"
OFFICIAL_BASES = (BASIS_PAGE, BASIS_EXEMPT, BASIS_CURRENCY)
NAME_PATTERN = re.compile(r"(^F-)|(-KY創?$)")


def name_marks_foreign(name: str | None) -> bool:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))
    return NAME_PATTERN.search(text) is not None


def _exempt_keys(metadata: Any) -> set[tuple[str, str]]:
    """``(exchange, symbol)`` of the manifest items that were 免申報 pages."""

    manifest = metadata.get("manifest") if isinstance(metadata, dict) else None
    found: set[tuple[str, str]] = set()
    for key, item in (manifest or {}).items():
        if not isinstance(item, dict):
            continue
        if FOREIGN_EXEMPT not in (item.get("class"), item.get("write")):
            continue
        parts = str(key).split(":")
        if len(parts) >= 2:
            found.add((parts[0], parts[1]))
    return found


def foreign_issuers(db: Session) -> dict[int, str]:
    """Instrument id → how it is known to be a foreign issuer (first basis found)."""

    found: dict[int, str] = {}
    for (instrument_id,) in db.execute(
        select(MonthlyRevenue.instrument_id)
        .where(
            MonthlyRevenue.source == PAGE_SOURCE,
            MonthlyRevenue.data_json["page"].as_integer() == FOREIGN_PAGE,
        )
        .distinct()
    ):
        found.setdefault(instrument_id, BASIS_PAGE)
    exempt: set[tuple[str, str]] = set()
    for metadata in db.scalars(
        select(IngestionRun.metadata_json).where(
            IngestionRun.run_type.in_(COMPANY_RUN_TYPES)
        )
    ):
        exempt |= _exempt_keys(metadata)
    instruments = list(db.scalars(select(Instrument)))
    for item in instruments:
        if (item.exchange, item.symbol) in exempt:
            found.setdefault(item.id, BASIS_EXEMPT)
    for instrument_id, details in db.execute(
        select(MonthlyRevenue.instrument_id, MonthlyRevenue.data_json).where(
            MonthlyRevenue.source == COMPANY_SOURCE
        )
    ):
        if isinstance(details, dict) and FUNCTIONAL_CURRENCY_KEY in details:
            found.setdefault(instrument_id, BASIS_CURRENCY)
    for item in instruments:
        if item.id not in found and name_marks_foreign(item.name):
            found[item.id] = BASIS_NAME
    return found
