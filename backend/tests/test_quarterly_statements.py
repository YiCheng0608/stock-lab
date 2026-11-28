"""Quarterly balance sheet and cash flow items from the MOPS XBRL archives (#1083).

The two archive fixtures are the members ``test_quarterly_xbrl`` uses: 3671's
consolidated 2014Q2 instance (``.xml``, the 2013–2017 element names) and 4205's
individual 2024Q3 instance (inline ``.html``, the 2018 names).  The t163sb05 fixture is
the listed 2014Q2 page #1078 fetched (2026-11-27 08:11 Taipei), each table cut to its
header and first two companies, line endings LF and trailing blanks removed.  Other
instances and pages are written here.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    QuarterlyStatement,
    RawPayload,
)
from worker import foreign_issuers as fi
from worker import quarterly_fundamentals as qf
from worker import quarterly_statements as qs
from worker import quarterly_xbrl as qx
from worker import sources
from worker.quarterly_fundamentals import Quarter
from worker.sources import OfficialDataError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
XML_MEMBER = FIXTURES / "mops_tifrs" / "tifrs-fr1-m2-ci-cr-3671-2014Q2.xml"
HTML_MEMBER = FIXTURES / "mops_tifrs" / "tifrs-fr1-m1-ci-ir-4205-2024Q3.html"
PAGE = FIXTURES / "mops_t163sb05" / "t163sb05_sii_103_02.html"
Q = Quarter(2014, 2)
NOW = datetime(2026, 11, 27, 3, 0)  # 11:00 Taipei
FETCHED = "2026-11-16T03:00:00+00:00"

NS = {
    "ifrs": "http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs",
    "ifrs-full": "http://xbrl.ifrs.org/taxonomy/2017-03-09/ifrs-full",
    "tifrs-bsci-ci": "http://www.xbrl.org/tifrs/bsci/ci/2014-03-31",
    "tifrs-SCF": "http://www.xbrl.org/tifrs/scf/2014-03-31",
    "tifrs-notes": "http://www.xbrl.org/tifrs/notes/2014-03-31",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in statement tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    frozen_utcnow.at = NOW
    return frozen_utcnow


# --- instances, archives and pages -----------------------------------------------------


def _context(context_id: str, period: str, dimension: bool = False) -> str:
    segment = (
        '<segment><xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></segment>'
        if dimension
        else ""
    )
    return (
        f'<context id="{context_id}"><entity><identifier scheme="s">1</identifier>'
        f"{segment}</entity><period>{period}</period></context>"
    )


def statement_xml(
    facts: list[tuple[str, str, str]], quarter: Quarter = Q, *, prolog: str = ""
) -> bytes:
    """A small XML instance; FACTS are (prefix:name, context, text).

    Contexts: ``I`` the quarter-end instant, ``Y`` the year to date, ``P`` the year
    before's end, ``ID`` the quarter end with a dimension.
    """

    end = quarter.period_end.isoformat()
    contexts = (
        _context("I", f"<instant>{end}</instant>")
        + _context(
            "Y", f"<startDate>{quarter.year}-01-01</startDate><endDate>{end}</endDate>"
        )
        + _context("P", f"<instant>{quarter.year - 1}-12-31</instant>")
        + _context("ID", f"<instant>{end}</instant>", dimension=True)
    )
    namespaces = "".join(f' xmlns:{prefix}="{uri}"' for prefix, uri in NS.items())
    body = "".join(
        f'<{name} contextRef="{context}" decimals="-3" unitRef="TWD">{text}</{name}>'
        for name, context, text in facts
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{prolog}'
        '<xbrl xmlns="http://www.xbrl.org/2003/instance"'
        f' xmlns:xbrldi="http://xbrl.org/2006/xbrldi"{namespaces}>'
        f"{contexts}{body}</xbrl>"
    ).encode("utf-8")


def statement_inline(facts: list[tuple[str, str, str]], quarter: Quarter = Q) -> bytes:
    """A small inline instance; FACTS are (name, context, attributes and text as ``a|t``)."""

    end = quarter.period_end.isoformat()

    def context(context_id: str, period: str) -> str:
        return (
            f'<xbrli:context id="{context_id}"><xbrli:entity><xbrli:identifier'
            f' scheme="s">1</xbrli:identifier></xbrli:entity><xbrli:period>{period}'
            "</xbrli:period></xbrli:context>"
        )

    contexts = context("I", f"<xbrli:instant>{end}</xbrli:instant>") + context(
        "Y",
        f"<xbrli:startDate>{quarter.year}-01-01</xbrli:startDate>"
        f"<xbrli:endDate>{end}</xbrli:endDate>",
    )
    body = ""
    for name, context_id, spec in facts:
        attributes, text = spec.split("|", 1)
        body += (
            f'<ix:nonFraction name="{name}" contextRef="{context_id}" unitRef="TWD"'
            f' decimals="-3" {attributes}>{text}</ix:nonFraction>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'
        ' xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<body>{contexts}{body}</body></html>"
    ).encode("utf-8")


def company(
    symbol: str,
    *,
    eps: str = "1.00",
    assets: str = "10000000",
    equity: str = "6000000",
    gross: str = "1000000",
    operating: str = "500000",
    industry: str = "ci",
    kind: str = "cr",
    quarter: Quarter = Q,
) -> tuple[str, bytes]:
    """One member with the core items (NTD; the pages are in thousands)."""

    facts = [
        ("ifrs:Assets", "I", assets),
        ("ifrs:Liabilities", "I", str(int(assets) - int(equity))),
        ("ifrs:Equity", "I", equity),
        ("ifrs:EquityAttributableToOwnersOfParent", "I", equity),
        ("ifrs:CurrentAssets", "I", "4000000"),
        ("ifrs:CurrentLiabilities", "I", "2000000"),
        ("ifrs:CashAndCashEquivalents", "I", "1500000"),
        ("tifrs-bsci-ci:OrdinaryShare", "I", "3000000"),
        ("tifrs-bsci-ci:CapitalStock", "I", "3100000"),
        ("ifrs:CashFlowsFromUsedInOperatingActivities", "Y", "800000"),
        ("tifrs-SCF:AcquisitionOfPropertyPlantAndEquipment", "Y", "-200000"),
        ("tifrs-bsci-ci:GrossProfitLossFromOperationsNet", "Y", gross),
        ("tifrs-bsci-ci:NetOperatingIncomeLoss", "Y", operating),
        ("ifrs:BasicEarningsLossPerShare", "Y", eps),
    ]
    name = f"tifrs-fr1-m1-{industry}-{kind}-{symbol}-{quarter.label}.xml"
    return name, statement_xml(facts, quarter)


def archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, data in members.items():
            handle.writestr(name, data)
    return buffer.getvalue()


def page_html(rows: dict[str, tuple[str, str]], quarter: Quarter = Q) -> str:
    """A t163sb05 page of QUARTER's check market; ROWS are (資產總計, 權益總計) in thousands."""

    market = qs.check_market(quarter)
    title = {"sii": "上市", "otc": "上櫃"}[market]
    season = {1: "第一季", 2: "第二季", 3: "第三季", 4: "第四季"}[quarter.quarter]
    cells = "".join(
        f"<tr class='even'><td>{symbol}</td><td>公司{symbol}</td><td>{assets}</td>"
        f"<td>{equity}</td></tr>"
        for symbol, (assets, equity) in rows.items()
    )
    return (
        f"<html><body><h2>{title}公司{season}資料</h2>"
        "<table class='hasBorder'><tr class='tblHead'><th>公司<br>代號</th>"
        "<th>公司名稱</th><th>資產總計</th><th>權益總計</th></tr>"
        f"{cells}</table></body></html>"
    )


def store(
    directory: Path, quarter: Quarter, data: bytes, page: str | None = None
) -> None:
    """The archive and its manifest entry, and the quarter's t163sb05 page."""

    directory.mkdir(parents=True, exist_ok=True)
    (directory / qx.archive_name(quarter)).write_bytes(data)
    manifest = qx.read_manifest(directory)
    manifest["quarters"][quarter.label] = {
        "url": qx.archive_url(quarter),
        "status": 200,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "members": len(zipfile.ZipFile(io.BytesIO(data)).infolist()),
        "fetched_at": FETCHED,
    }
    qx._write_manifest(directory, manifest)
    if page is None:
        return
    (directory / qs.CHECK_DIR).mkdir(exist_ok=True)
    encoded = page.encode("utf-8")
    path = directory / qs.CHECK_DIR / qs.check_page_name(quarter)
    path.write_bytes(encoded)
    pages = qs.read_check_manifest(directory)
    pages["quarters"][quarter.label] = {
        "file": path.name,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "fetched_at": FETCHED,
    }
    qs._write_check_manifest(directory, pages)


# --- parsing ----------------------------------------------------------------------------


def test_the_xml_fixture_reads_the_2013_names_in_thousands():
    data = XML_MEMBER.read_bytes()
    statement = qs.parse_statement(data, Q, industry="ci", kind="cr")
    thousands = {name: statement.thousands(name) for name in qs.FIELDS}
    assert thousands == {
        "total_assets": 23270.0,
        "total_liabilities": 130.0,
        "equity_parent": 23140.0,
        "equity_total": 23140.0,
        "current_assets": 16459.0,
        "current_liabilities": 130.0,
        "cash": 16168.0,
        "receivables": 0.0,
        "inventories": None,  # 3671 has no inventory line
        "share_capital_common": 135000.0,
        "share_capital_total": 135000.0,
        "cfo_ytd": -3364.0,
        "capex_ytd": None,  # nor a purchase of equipment
        "gross_profit_ytd": -1432.0,
        "operating_income_ytd": -10389.0,
    }
    assert statement.elements["equity_parent"] == [
        "EquityAttributableToOwnersOfParent",
        "AsOf20140630",
    ]
    assert statement.elements["gross_profit_ytd"] == [
        "GrossProfitLossFromOperationsNet",
        "From20140101To20140630",
    ]
    assert statement.not_applicable == []
    assert statement.eps == qx.parse_eps(data, Q)[0]


def test_the_inline_fixture_reads_the_2018_names_and_an_individual_equity():
    quarter = Quarter(2024, 3)
    statement = qs.parse_statement(
        HTML_MEMBER.read_bytes(), quarter, industry="ci", kind="ir"
    )
    assert statement.thousands("total_assets") == 2326001.0
    assert statement.thousands("total_liabilities") == 348368.0
    # An individual report has no EquityAttributableToOwnersOfParent: its Equity.
    assert statement.thousands("equity_parent") == 1977633.0
    assert statement.elements["equity_parent"] == ["Equity", "AsOf20240930"]
    assert statement.thousands("equity_total") == 1977633.0
    assert statement.thousands("inventories") == 48538.0
    assert statement.thousands("receivables") == 151635.0
    assert statement.thousands("share_capital_common") == 887720.0
    assert statement.thousands("share_capital_total") == 887720.0
    assert statement.elements["share_capital_total"][0] == "IssuedCapital"
    assert statement.thousands("cfo_ytd") == 245144.0
    # sign="-": an outflow, stored as filed.
    assert statement.thousands("capex_ytd") == -72968.0
    assert statement.thousands("gross_profit_ytd") == 570382.0
    assert statement.elements["gross_profit_ytd"][0] == "GrossProfit"
    assert statement.thousands("operating_income_ytd") == 332931.0
    assert statement.elements["operating_income_ytd"][0] == (
        "ProfitLossFromOperatingActivities"
    )


def test_a_consolidated_report_without_the_parent_line_stays_empty():
    data = statement_xml([("ifrs:Equity", "I", "100000")])
    assert (
        qs.parse_statement(data, Q, industry="ci", kind="cr").values["equity_parent"]
        is None
    )
    for kind in ("ir", "er"):
        statement = qs.parse_statement(data, Q, industry="ci", kind=kind)
        assert statement.thousands("equity_parent") == 100.0


@pytest.mark.parametrize(
    "names",
    [
        (
            "tifrs-bsci-ci:CapitalStock",
            "tifrs-SCF:AcquisitionOfPropertyPlantAndEquipment",
            "tifrs-bsci-ci:GrossProfitLossFromOperationsNet",
            "tifrs-bsci-ci:NetOperatingIncomeLoss",
        ),
        (
            "ifrs-full:IssuedCapital",
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full:GrossProfit",
            "ifrs-full:ProfitLossFromOperatingActivities",
        ),
    ],
    ids=["2013-2017", "2018"],
)
def test_both_sets_of_element_names_are_read(names):
    capital, capex, gross, operating = names
    data = statement_xml(
        [
            (capital, "I", "5000000"),
            (capex, "Y", "-7000"),
            (gross, "Y", "9000"),
            (operating, "Y", "-3000"),
        ]
    )
    statement = qs.parse_statement(data, Q, industry="ci", kind="cr")
    assert statement.thousands("share_capital_total") == 5000.0
    assert statement.thousands("capex_ytd") == -7.0
    assert statement.thousands("gross_profit_ytd") == 9.0
    assert statement.thousands("operating_income_ytd") == -3.0


def test_the_gross_profit_is_the_net_one_not_the_one_before_unrealized():
    data = statement_xml(
        [
            ("tifrs-bsci-ci:GrossProfitLossFromOperations", "Y", "9000"),
            ("tifrs-bsci-ci:GrossProfitLossFromOperationsNet", "Y", "8000"),
        ]
    )
    assert (
        qs.parse_statement(data, Q, industry="ci", kind="cr").thousands(
            "gross_profit_ytd"
        )
        == 8.0
    )


@pytest.mark.parametrize(
    "spec, expected",
    [
        ('format="ixt:numdotdecimal" scale="3"|1,234', 1234.0),
        ('format="ixt:num-dot-decimal" scale="3" sign="-"|72,968', -72968.0),
        ('format="ixt:numdotdecimal" scale="6"|2', 2000.0),
        ('format="ixt:numdotdecimal" scale="0"|1500', 1.5),
        ('format="ixt:fixed-zero" scale="3"|-', 0.0),
        ('format="ixt:zerodash" scale="3"|-', 0.0),
        ('xsi:nil="true"|', None),
    ],
)
def test_inline_scale_sign_format_and_nil(spec, expected):
    data = statement_inline([("ifrs-full:Assets", "I", spec)])
    statement = qs.parse_statement(data, Q, industry="ci", kind="cr")
    assert statement.thousands("total_assets") == expected


def test_an_unknown_inline_format_is_a_member_error():
    data = statement_inline([("ifrs-full:Assets", "I", 'format="ixt:numwordsen"|one')])
    with pytest.raises(qx.MemberError, match="unknown inline XBRL format"):
        qs.parse_statement(data, Q, industry="ci", kind="cr")


def test_only_the_quarter_end_and_year_to_date_contexts_without_dimensions_count():
    data = statement_xml(
        [
            ("ifrs:Assets", "P", "1000"),
            ("ifrs:Assets", "ID", "2000"),
            ("ifrs:CashFlowsFromUsedInOperatingActivities", "I", "3000"),
            ("ifrs:Liabilities", "I", "4000"),
        ]
    )
    statement = qs.parse_statement(data, Q, industry="ci", kind="cr")
    assert statement.values["total_assets"] is None
    assert statement.values["cfo_ytd"] is None
    assert statement.thousands("total_liabilities") == 4.0


def test_a_fact_in_the_context_its_field_does_not_read_is_not_parsed():
    """2013Q1 1213: a cash policy note tagged as a year-to-date CashAndCashEquivalents."""

    note = "1.本集團合併現金流量表中，現金及約當現金包括庫存現金、銀行存款。"
    data = statement_xml(
        [
            ("ifrs:CashAndCashEquivalents", "I", "1500000"),
            ("ifrs:CashAndCashEquivalents", "Y", note),
            ("ifrs:CashFlowsFromUsedInOperatingActivities", "I", note),
            ("ifrs:CashFlowsFromUsedInOperatingActivities", "Y", "800000"),
        ]
    )
    statement = qs.parse_statement(data, Q, industry="ci", kind="cr")
    assert statement.thousands("cash") == 1500.0
    assert statement.thousands("cfo_ytd") == 800.0
    # In the context its field reads, text is still refused.
    bad = statement_xml([("ifrs:CashAndCashEquivalents", "I", note)])
    with pytest.raises(qs.MemberError, match="is not a number"):
        qs.parse_statement(bad, Q, industry="ci", kind="cr")


def test_facts_of_one_element_and_context_must_agree():
    same = statement_xml([("ifrs:Assets", "I", "1000"), ("ifrs:Assets", "I", "1000")])
    assert (
        qs.parse_statement(same, Q, industry="ci", kind="cr").thousands("total_assets")
        == 1.0
    )
    different = statement_xml(
        [("ifrs:Assets", "I", "1000"), ("ifrs:Assets", "I", "2000")]
    )
    with pytest.raises(qx.MemberError, match="Assets instant facts disagree"):
        qs.parse_statement(different, Q, industry="ci", kind="cr")


def test_a_note_taxonomy_fact_is_not_read():
    # A holding's OrdinaryShare is in tifrs-notes; its statement line is CommonStock.
    data = statement_xml(
        [
            ("tifrs-notes:OrdinaryShare", "I", "9000"),
            ("ifrs:CommonStock", "I", "8000"),
        ]
    )
    statement = qs.parse_statement(data, Q, industry="fh", kind="cr")
    assert statement.thousands("share_capital_common") == 8.0
    assert statement.elements["share_capital_common"][0] == "CommonStock"
    inline = statement_inline(
        [("tifrs-notes:OrdinaryShare", "I", 'format="ixt:numdotdecimal" scale="3"|9')]
    )
    assert (
        qs.parse_statement(inline, Q, industry="fh", kind="cr").values[
            "share_capital_common"
        ]
        is None
    )


@pytest.mark.parametrize(
    "industry, not_applicable",
    [
        ("ci", []),
        ("mim", []),
        (
            "basi",
            [
                "current_assets",
                "current_liabilities",
                "gross_profit_ytd",
                "inventories",
                "operating_income_ytd",
                "receivables",
            ],
        ),
        (
            "fh",
            [
                "current_assets",
                "current_liabilities",
                "gross_profit_ytd",
                "inventories",
                "operating_income_ytd",
                "receivables",
            ],
        ),
        (
            "ins",
            [
                "current_assets",
                "current_liabilities",
                "gross_profit_ytd",
                "inventories",
                "receivables",
            ],
        ),
        ("bd", ["gross_profit_ytd", "inventories"]),
    ],
)
def test_a_financial_format_marks_its_missing_lines_not_applicable(
    industry, not_applicable
):
    name, data = company("2801", industry=industry)
    statement = qs.parse_statement(data, Q, industry=industry, kind="cr")
    assert statement.not_applicable == not_applicable
    for item in not_applicable:
        assert statement.values[item] is None and item not in statement.elements
    # The lines every format has are read.
    for item in ("total_assets", "equity_total", "cash", "cfo_ytd", "capex_ytd"):
        assert statement.values[item] is not None


@pytest.mark.parametrize(
    "prolog",
    [
        '<!DOCTYPE xbrl [<!ENTITY e "x">]>',
        '<!DOCTYPE xbrl SYSTEM "http://example.test/x.dtd">',
    ],
)
def test_a_doctype_or_entity_is_refused_before_parsing(prolog):
    data = statement_xml([("ifrs:Assets", "I", "1000")], prolog=prolog)
    with pytest.raises(qx.MemberError, match="DOCTYPE or an entity"):
        qs.parse_statement(data, Q, industry="ci", kind="cr")


def test_a_member_without_the_quarter_contexts_is_empty():
    # A non-calendar fiscal year (2014Q2's 5279) has no context ending at the quarter.
    statement = qs.parse_statement(
        statement_xml([("ifrs:Assets", "P", "1000")]), Q, industry="ci", kind="cr"
    )
    assert statement.empty and statement.eps is None


# --- the t163sb05 page ---------------------------------------------------------------------


def test_the_page_fixture_reads_each_format_s_total_assets_and_equity():
    page = qs.parse_check_page(PAGE.read_text(encoding="utf-8"), "sii", Q)
    assert len(page) == 12
    # As the page prints them (thousand NTD): a bank, a general and an "other" company
    # (#1078's own parse of the whole page, out/sb05.json, has the same).
    assert page["2801"] == {
        "total_assets": Decimal("1757826621"),
        "equity_total": Decimal("113763952"),
    }
    assert page["1101"] == {
        "total_assets": Decimal("280613572"),
        "equity_total": Decimal("147496365"),
    }
    assert page["1409"] == {
        "total_assets": Decimal("129273190"),
        "equity_total": Decimal("34313889"),
    }


@pytest.mark.parametrize(
    "change, message",
    [
        (("上市公司第二季資料", "上櫃公司第二季資料"), "another market"),
        (("上市公司第二季資料", "上市公司第三季資料"), "another quarter"),
        (("<table class='hasBorder'", "<table class='other'"), "no report table"),
        (("資產總額", "資產"), "no single total_assets column"),
    ],
)
def test_a_page_that_cannot_be_trusted_is_refused(change, message):
    html = PAGE.read_text(encoding="utf-8").replace(*change)
    with pytest.raises(OfficialDataError, match=message):
        qs.parse_check_page(html, "sii", Q)


def test_a_block_page_is_refused():
    with pytest.raises(OfficialDataError, match="refused"):
        qs.parse_check_page("<html>查詢過於頻繁</html>", "sii", Q)


def test_the_check_market_alternates():
    markets = [qs.check_market(q) for q in qx.quarters_between(Q, Quarter(2015, 1))]
    assert markets == ["sii", "otc", "sii", "otc"]


# --- fetching the pages ------------------------------------------------------------------


def _clock():
    state = {"now": 0.0, "slept": []}

    def clock():
        return state["now"]

    def sleep(seconds):
        state["slept"].append(seconds)
        state["now"] += seconds

    return state, clock, sleep


def test_fetch_stores_one_page_a_quarter_and_keeps_it_on_a_rerun(tmp_path):
    asked = []

    def fetcher(url, form):
        asked.append((url, form["TYPEK"], form["year"], form["season"]))
        quarter = Quarter(int(form["year"]) + 1911, int(form["season"]))
        return page_html({"1101": ("100", "50")}, quarter)

    state, clock, sleep = _clock()
    noon = lambda: datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)  # noqa: E731
    result = qs.fetch_check_pages(
        tmp_path,
        Q,
        Quarter(2014, 3),
        fetcher=fetcher,
        sleep=sleep,
        clock=clock,
        now=noon,
    )
    assert result["status"] == "success" and result["requests"] == 2
    assert asked == [
        (qs.CHECK_ENDPOINT, "sii", "103", "02"),
        (qs.CHECK_ENDPOINT, "otc", "103", "03"),
    ]
    assert state["slept"] == [qx.REQUEST_INTERVAL_SECONDS]
    entry = qs.read_check_manifest(tmp_path)["quarters"]["2014Q2"]
    assert entry["file"] == "2014Q2-sii.html" and entry["companies"] == 1
    again = qs.fetch_check_pages(
        tmp_path,
        Q,
        Quarter(2014, 3),
        fetcher=fetcher,
        sleep=sleep,
        clock=clock,
        now=noon,
    )
    assert again["kept"] == ["2014Q2", "2014Q3"] and again["requests"] == 0
    assert len(asked) == 2


def test_fetch_sends_nothing_in_quiet_hours(tmp_path):
    def fetcher(url, form):
        raise AssertionError("no request in quiet hours")

    state, clock, sleep = _clock()

    def evening():
        return datetime(2026, 11, 27, 13, 0, tzinfo=timezone.utc)  # 21:00 Taipei

    result = qs.fetch_check_pages(
        tmp_path, Q, Q, fetcher=fetcher, sleep=sleep, clock=clock, now=evening
    )
    assert result["status"] == "partial" and "quiet hours" in result["stopped"]
    assert result["requests"] == 0


def test_fetch_counts_a_bad_page_and_stops_after_three(tmp_path):
    state, clock, sleep = _clock()
    noon = lambda: datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)  # noqa: E731
    result = qs.fetch_check_pages(
        tmp_path,
        Q,
        Quarter(2015, 2),
        fetcher=lambda url, form: "<html>查詢過於頻繁</html>",
        sleep=sleep,
        clock=clock,
        now=noon,
    )
    assert result["status"] == "failed" and result["requests"] == 3
    assert sorted(result["failed"]) == ["2014Q2", "2014Q3", "2014Q4"]
    assert not list((tmp_path / qs.CHECK_DIR).glob("*.html"))


# --- apply --------------------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'statements.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


def add_instrument(db, symbol, *, exchange="TWSE", status="delisted", bars=(10,)):
    """An instrument with bars BARS days after the 2014Q2 quarter end."""

    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status=status,
    )
    db.add(item)
    db.flush()
    for offset in bars:
        db.add(
            MarketBar(
                instrument_id=item.id,
                trading_date=Q.period_end + timedelta(days=offset),
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1000,
            )
        )
    db.flush()
    return item


def add_t163sb04(db, item, eps, gross="1,000", operating="500", quarter=Q):
    db.add(
        FundamentalSnapshot(
            instrument_id=item.id,
            period_end=quarter.period_end,
            fiscal_period=f"Q{quarter.quarter}",
            announcement_date=date(2014, 8, 14),
            eps=eps,
            data_json={
                "report_format": "general",
                "營業毛利（毛損）淨額": gross,
                "營業利益（損失）": operating,
            },
            source=qx.T163SB04_SOURCE,
            data_as_of=quarter.period_end.isoformat(),
        )
    )


def seed(db):
    """Active 2330, delisted 2475 (in the window) and 2499 (not), transferred 1597."""

    survivor = add_instrument(db, "2330", status="active")
    add_t163sb04(db, survivor, 4.0)
    add_instrument(db, "2475")
    add_instrument(db, "2499", bars=(700,))
    twin = add_instrument(db, "1597", status="active")
    add_t163sb04(db, twin, 2.5)
    add_instrument(db, "1597", exchange="TPEx", status="transferred")
    add_instrument(db, "9105", status="active")  # no t163sb04 row: a DR
    db.commit()


SEED_ARCHIVE = dict(
    [
        company("2330", eps="4.00"),
        company("2475", eps="-0.31", assets="5000000", equity="2000000"),
        company("2499", eps="0.10"),
        company("1597", eps="2.50"),
        company("9105", eps="0.20"),
        company("8888"),  # a code the database does not know
    ]
)
SEED_PAGE = page_html({"2330": ("10,000", "6,000"), "1597": ("10000", "6000")})


def apply(factory, directory, start=Q, end=Q, **kwargs):
    with factory() as db:
        return qs.apply_statements(db, directory, start, end, **kwargs)


def written(db):
    query = (
        select(Instrument.exchange, Instrument.symbol, QuarterlyStatement)
        .join(Instrument, Instrument.id == QuarterlyStatement.instrument_id)
        .order_by(Instrument.symbol, Instrument.exchange)
    )
    return {(ex, sym): row for ex, sym, row in db.execute(query).all()}


def test_active_delisted_and_transferred_instruments_get_the_quarter(factory, tmp_path):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    result = apply(factory, tmp_path)
    assert result["status"] == "success", result
    quarter = result["quarters"]["2014Q2"]
    assert quarter["inserted"] == 4
    assert quarter["not_in_db"] == 1
    assert quarter["outside_window"] == 1
    assert quarter["no_identity_row"] == 1
    assert quarter["income_same"] == 2 and quarter["balance_same"] == 2
    assert {group: item["rows"] for group, item in quarter["groups"].items()} == {
        "active": 2,
        "delisted": 1,
        "transferred": 1,
    }
    # The members have no inventory or receivable line: missing, not 0.
    assert quarter["groups"]["active"]["missing"] == {
        "inventories": 2,
        "receivables": 2,
    }
    assert quarter["groups"]["active"]["applicable"]["inventories"] == 2
    assert quarter["groups"]["active"]["rules"] == {"t163sb04_eps": 2}
    assert quarter["groups"]["delisted"]["rules"] == {"bar_window": 1}
    assert quarter["income_by_source"] == {"mops_t163sb04": {"same": 2, "different": 0}}
    with factory() as db:
        rows = written(db)
        assert set(rows) == {
            ("TWSE", "1597"),
            ("TPEx", "1597"),
            ("TWSE", "2330"),
            ("TWSE", "2475"),
        }
        delisted = rows[("TWSE", "2475")]
        assert delisted.total_assets == 5000.0 and delisted.equity_total == 2000.0
        assert delisted.total_liabilities == 3000.0
        assert delisted.capex_ytd == -200.0
        assert delisted.share_capital_common == 3000.0
        assert delisted.share_capital_total == 3100.0
        assert delisted.inventories is None and delisted.receivables is None
        assert delisted.source == "mops_tifrs_zip"
        assert delisted.fiscal_period == "Q2"
        assert delisted.data_as_of == Q.period_end
        # 2014-08-14 is a Thursday; no holiday schedule is loaded.
        assert delisted.announcement_date == date(2014, 8, 14)
        details = delisted.data_json
        assert details["target_rule"] == "bar_window"
        assert details["member"] == "tifrs-fr1-m1-ci-cr-2475-2014Q2.xml"
        assert details["report_kind"] == "cr" and details["report_format"] == "general"
        assert details["elements"]["total_assets"] == ["Assets", "I"]
        assert details["not_applicable"] == []
        assert details["announcement_basis"] == "statutory_deadline"
        assert details["statutory_deadline"] == "2014-08-14"
        assert details["eps"] == -0.31
        assert rows[("TWSE", "2330")].data_json["target_rule"] == "t163sb04_eps"
        assert rows[("TPEx", "1597")].data_json["target_rule"] == "bar_window"
        raw = db.get(RawPayload, delisted.raw_payload_id)
        assert raw.source == qx.RAW_SOURCE and raw.endpoint == qx.archive_url(Q)
        run = db.get(IngestionRun, result["run_id"])
        assert run.run_type == qs.RUN_TYPE and run.status == "success"
        assert run.records == 4
        assert run.metadata_json["coverage_manifest"]["2014Q2"]["check_page"] == (
            "2014Q2-sii.html"
        )


def test_a_rerun_changes_nothing(factory, tmp_path):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    assert apply(factory, tmp_path)["changed"] == 4
    with factory() as db:
        before = {key: row.collected_at for key, row in written(db).items()}
    again = apply(factory, tmp_path)
    assert again["status"] == "success" and again["changed"] == 0
    assert again["quarters"]["2014Q2"]["unchanged"] == 4
    with factory() as db:
        assert {key: row.collected_at for key, row in written(db).items()} == before
        assert db.scalar(select(RawPayload.id).where(RawPayload.id > 1)) is None


def test_a_dry_run_writes_nothing(factory, tmp_path):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    result = apply(factory, tmp_path, dry_run=True)
    assert result["status"] == "success" and result["run_id"] is None
    assert result["quarters"]["2014Q2"]["would_insert"] == 4
    with factory() as db:
        assert written(db) == {}
        assert db.scalar(select(IngestionRun.id)) is None


@pytest.mark.parametrize(
    "gross, operating",
    [("1,001", "500"), ("1,000", "502"), ("1,000", "--"), ("--", "--")],
)
def test_an_income_check_within_rounding_or_blank_passes(
    factory, tmp_path, gross, operating
):
    # One thousand of rounding; a column t163sb04 prints as -- is not compared.
    expected_ok = operating != "502"
    with factory() as db:
        item = add_instrument(db, "2330", status="active")
        add_t163sb04(db, item, 4.0, gross=gross, operating=operating)
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2330", eps="4.00")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert (result["status"] == "success") is expected_ok, result


def _two_quarters(tmp_path, first_page, first_gross="1,000"):
    """2014Q2 and 2014Q3 for 2330; the first quarter's page and t163sb04 as given."""

    later = Quarter(2014, 3)
    store(tmp_path, Q, archive(dict([company("2330", eps="4.00")])), first_page)
    store(
        tmp_path,
        later,
        archive(dict([company("2330", eps="5.00", quarter=later)])),
        page_html({"2330": ("10000", "6000")}, later),
    )
    return later


@pytest.mark.parametrize(
    "what, page, gross",
    [
        ("t163sb04／snapshot", page_html({"2330": ("10000", "6000")}), "1,002"),
        ("t163sb05 sii", page_html({"2330": ("10002", "6000")}), "1,000"),
        ("t163sb05 sii", page_html({"2330": ("10000", "5998")}), "1,000"),
    ],
    ids=["gross profit", "total assets", "equity"],
)
def test_a_different_company_stops_before_the_quarter_is_written(
    factory, tmp_path, what, page, gross
):
    later = _two_quarters(tmp_path, page)
    with factory() as db:
        item = add_instrument(db, "2330", status="active")
        add_t163sb04(db, item, 4.0, gross=gross)
        add_t163sb04(db, item, 5.0, quarter=later)
        db.commit()
    result = apply(factory, tmp_path, Q, later)
    assert result["status"] == "failed"
    assert what in result["aborted"] and "停下來問" in result["aborted"]
    assert set(result["quarters"]) == {"2014Q2"}  # 2014Q3 never ran
    assert result["quarters"]["2014Q2"]["examples"][0][1] == "2330"
    with factory() as db:
        assert written(db) == {}
        run = db.get(IngestionRun, result["run_id"])
        assert run.status == "failed" and "停下來問" in run.error


def test_a_company_the_archive_lacks_on_t163sb04_s_side_is_a_difference(
    factory, tmp_path
):
    # t163sb04 prints a gross profit the archive does not have.
    with factory() as db:
        item = add_instrument(db, "2330", status="active")
        add_t163sb04(db, item, 4.0)
        db.commit()
    member = company("2330", eps="4.00")[0]
    data = statement_xml(
        [
            ("ifrs:Assets", "I", "10000000"),
            ("ifrs:Equity", "I", "6000000"),
            ("ifrs:BasicEarningsLossPerShare", "Y", "4.00"),
        ]
    )
    store(tmp_path, Q, archive({member: data}), page_html({"2330": ("10000", "6000")}))
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert result["quarters"]["2014Q2"]["income_different"] == 1


def add_snapshot(db, item, eps, operating):
    """The daily's OpenAPI snapshot row (2026Q2 on it writes a quarter first)."""

    db.add(
        FundamentalSnapshot(
            instrument_id=item.id,
            period_end=Q.period_end,
            fiscal_period="Q2",
            announcement_date=date(2014, 8, 14),
            eps=eps,
            data_json={"營業利益": operating},
            source=qs.SNAPSHOT_SOURCE,
            data_as_of=Q.period_end.isoformat(),
        )
    )


def test_a_snapshot_row_identifies_the_company_and_checks_operating_income(
    factory, tmp_path
):
    with factory() as db:
        add_snapshot(db, add_instrument(db, "2330", status="active"), 4.0, "500.00")
        # A bank: the snapshot's 營業利益 is not a line of its format, not compared.
        add_snapshot(db, add_instrument(db, "2801", status="active"), 4.0, "999.00")
        sb04 = add_instrument(db, "1101", status="active")
        add_t163sb04(db, sb04, 1.0)
        db.commit()
    members = dict(
        [
            # The archive has a gross profit; the snapshot has nothing to compare.
            company("2330", eps="4.00", gross="7777000"),
            company("2801", eps="4.00", industry="basi"),
            company("1101", eps="1.00"),
        ]
    )
    store(tmp_path, Q, archive(members), page_html({"2330": ("10000", "6000")}))
    result = apply(factory, tmp_path)
    assert result["status"] == "success", result
    quarter = result["quarters"]["2014Q2"]
    assert quarter["income_by_source"] == {
        "mops_fundamental": {"same": 2, "different": 0},
        "mops_t163sb04": {"same": 1, "different": 0},
    }
    assert quarter["groups"]["active"]["rules"] == {
        "snapshot_eps": 2,
        "t163sb04_eps": 1,
    }
    with factory() as db:
        rows = written(db)
        assert rows[("TWSE", "2330")].data_json["target_rule"] == "snapshot_eps"
        assert rows[("TWSE", "2330")].gross_profit_ytd == 7777.0
        assert rows[("TWSE", "2801")].operating_income_ytd is None


def test_a_snapshot_with_another_eps_is_not_written(factory, tmp_path, monkeypatch):
    # One of two is over the 1% stop; a reused code is one among about 2,000.
    monkeypatch.setattr(qs, "CHECK_MISSING_LIMIT", 0.5)
    with factory() as db:
        add_snapshot(db, add_instrument(db, "2330", status="active"), 4.0, "500.00")
        add_snapshot(db, add_instrument(db, "6005", status="active"), 9.9, "500.00")
        db.commit()
    members = dict([company("2330", eps="4.00"), company("6005", eps="1.00")])
    store(tmp_path, Q, archive(members), page_html({"2330": ("10000", "6000")}))
    result = apply(factory, tmp_path)
    assert result["status"] == "success"
    assert result["quarters"]["2014Q2"]["eps_different"] == 1
    with factory() as db:
        assert set(written(db)) == {("TWSE", "2330")}


def test_a_snapshot_with_another_operating_income_stops(factory, tmp_path):
    with factory() as db:
        add_snapshot(db, add_instrument(db, "2330", status="active"), 4.0, "502.00")
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2330", eps="4.00")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "failed" and "停下來問" in result["aborted"]
    assert result["quarters"]["2014Q2"]["income_by_source"] == {
        "mops_fundamental": {"same": 0, "different": 1}
    }
    with factory() as db:
        assert written(db) == {}


def test_an_active_company_with_another_eps_is_not_written(
    factory, tmp_path, monkeypatch
):
    # One of two is over the 1% stop; a reused code is one among about 2,000.
    monkeypatch.setattr(qs, "CHECK_MISSING_LIMIT", 0.5)
    # The code's company in the archive is not the one t163sb04 lists today.
    with factory() as db:
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0)
        other = add_instrument(db, "6005", status="active")
        add_t163sb04(db, other, 9.9)
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2330", eps="4.00"), company("6005", eps="1.00")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "success"
    assert result["quarters"]["2014Q2"]["eps_different"] == 1
    with factory() as db:
        assert set(written(db)) == {("TWSE", "2330")}


def test_too_many_companies_missing_from_a_check_stops(factory, tmp_path):
    with factory() as db:
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0)
        db.commit()
    # The page lists a company the archive does not have: 1 of 2 missing.
    page = page_html({"2330": ("10000", "6000"), "6026": ("1", "1")})
    store(tmp_path, Q, archive(dict([company("2330", eps="4.00")])), page)
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert result["quarters"]["2014Q2"]["balance_missing"] == 1


def test_a_check_that_compared_nothing_stops(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2475")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    with factory() as db:
        assert written(db) == {}


def test_a_financial_company_s_not_applicable_lines_are_null(factory, tmp_path):
    with factory() as db:
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0)
        add_instrument(db, "2837")  # a delisted bank
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2330", eps="4.00"), company("2837", industry="basi")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "success", result
    delisted = result["quarters"]["2014Q2"]["groups"]["delisted"]
    # Not applicable lines are neither missing nor in the denominator.
    assert "current_assets" not in delisted["applicable"]
    assert delisted["missing"] == {}
    with factory() as db:
        bank = written(db)[("TWSE", "2837")]
        assert bank.current_assets is None and bank.gross_profit_ytd is None
        assert bank.operating_income_ytd is None
        assert bank.total_assets == 10000.0 and bank.cfo_ytd == 800.0
        assert "current_assets" in bank.data_json["not_applicable"]
        assert bank.data_json["report_format"] == "bank"
        # Banks' Q2 deadline is 8/31 (a Sunday in 2014): the next weekday.
        assert bank.data_json["statutory_deadline"] == "2014-09-01"


def test_an_unreadable_member_is_counted_and_skipped(factory, tmp_path):
    with factory() as db:
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0)
        add_instrument(db, "2475")
        db.commit()
    bad = statement_xml(
        [("ifrs:Assets", "I", "1000")], prolog='<!DOCTYPE xbrl [<!ENTITY e "x">]>'
    )
    members = dict([company("2330", eps="4.00")])
    members[company("2475")[0]] = bad
    store(tmp_path, Q, archive(members), page_html({"2330": ("10000", "6000")}))
    result = apply(factory, tmp_path)
    assert result["status"] == "success"
    assert result["quarters"]["2014Q2"]["unreadable"] == 1
    assert "DOCTYPE" in result["quarters"]["2014Q2"]["errors"][0]
    with factory() as db:
        assert set(written(db)) == {("TWSE", "2330")}


def test_a_member_over_its_limit_fails_the_quarter(factory, tmp_path, monkeypatch):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    monkeypatch.setattr(qx, "MAX_MEMBER_BYTES", 100)
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert "over 100 bytes" in result["quarters"]["2014Q2"]["error"]
    with factory() as db:
        assert written(db) == {}


def test_the_total_read_is_limited(factory, tmp_path, monkeypatch):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    monkeypatch.setattr(qx, "MAX_TOTAL_BYTES", 3000)
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert "over 3000 bytes uncompressed" in result["quarters"]["2014Q2"]["error"]


def test_an_excluded_instrument_is_not_written(factory, tmp_path):
    with factory() as db:
        seed(db)
        delisted = db.scalar(select(Instrument.id).where(Instrument.symbol == "2475"))
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    apply(factory, tmp_path)
    result = apply(factory, tmp_path, excluded=frozenset({delisted}))
    quarter = result["quarters"]["2014Q2"]
    assert quarter["excluded"] == 1 and quarter["excluded_already_written"] == 1


def test_a_quarter_without_its_archive_or_page_refuses_before_anything(
    factory, tmp_path
):
    with factory() as db:
        seed(db)
    assert "not downloaded: 2014Q2" in apply(factory, tmp_path)["error"]
    store(tmp_path, Q, archive(SEED_ARCHIVE))
    result = apply(factory, tmp_path)
    assert result["status"] == "failed" and "statements-check-fetch" in result["error"]
    with factory() as db:
        assert db.scalar(select(IngestionRun.id)) is None


def test_a_page_that_is_not_the_manifest_s_is_refused(factory, tmp_path):
    with factory() as db:
        seed(db)
    store(tmp_path, Q, archive(SEED_ARCHIVE), SEED_PAGE)
    (tmp_path / qs.CHECK_DIR / "2014Q2-sii.html").write_text(
        "changed", encoding="utf-8"
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert "t163sb05 manifest" in result["quarters"]["2014Q2"]["error"]


def test_the_fixtures_apply_end_to_end(factory, tmp_path):
    """3671 delisted (the 2014Q2 .xml) and 4205 delisted (the 2024Q3 inline .html)."""

    later = Quarter(2024, 3)
    with factory() as db:
        add_instrument(db, "3671", exchange="TPEx")
        item = add_instrument(db, "4205", exchange="TPEx", bars=())
        db.add(
            MarketBar(
                instrument_id=item.id,
                trading_date=date(2024, 10, 1),
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1000,
            )
        )
        # Each quarter's checks compare one active company.
        for quarter, eps in ((Q, 4.0), (later, 5.0)):
            survivor = add_instrument(db, f"23{quarter.quarter}0", status="active")
            add_t163sb04(db, survivor, eps, quarter=quarter)
        db.commit()
    store(
        tmp_path,
        Q,
        archive(
            {
                XML_MEMBER.name: XML_MEMBER.read_bytes(),
                **dict([company("2320", eps="4.00")]),
            }
        ),
        page_html({"2320": ("10000", "6000")}),
    )
    store(
        tmp_path,
        later,
        archive(
            {
                HTML_MEMBER.name: HTML_MEMBER.read_bytes(),
                **dict([company("2330", eps="5.00", quarter=later)]),
            }
        ),
        page_html({"2330": ("10000", "6000")}, later),
    )
    for quarter in (Q, later):
        result = apply(factory, tmp_path, quarter, quarter)
        assert result["status"] == "success", result
    with factory() as db:
        rows = written(db)
        old = rows[("TPEx", "3671")]
        assert old.total_assets == 23270.0 and old.gross_profit_ytd == -1432.0
        new = rows[("TPEx", "4205")]
        assert new.period_end == later.period_end
        assert new.equity_parent == 1977633.0 and new.capex_ytd == -72968.0
        assert new.data_json["elements"]["equity_parent"] == ["Equity", "AsOf20240930"]
        assert new.data_json["report_kind"] == "ir"


def test_insurers_use_the_ifrs17_format_from_2026():
    for quarter in qx.quarters_between(Quarter(2013, 1), Quarter(2025, 4)):
        assert qx.report_format_of("ins", quarter) == "insurance_legacy"
    assert qx.report_format_of("ins", Quarter(2026, 1)) == "insurance"
    assert qx.report_format_of("ci", Quarter(2026, 1)) == "general"
    assert qx.report_format_of("zz", Quarter(2026, 1)) is None


# --- commands -----------------------------------------------------------------------------


def _cli(monkeypatch, argv):
    import sys

    import worker.cli as cli_module

    monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
    try:
        cli_module.main()
    except SystemExit as exc:
        return exc.code
    return 0


APPLY_ARGV = [
    "fundamentals",
    "statements-apply",
    "--start",
    "2014Q2",
    "--end",
    "2014Q2",
]


@pytest.mark.parametrize("dry_run", [False, True])
def test_apply_refuses_without_the_research_marker(
    monkeypatch, tmp_path, capsys, dry_run
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")

    def never(*args, **kwargs):
        raise AssertionError("no session without the research marker")

    monkeypatch.setattr(cli_module, "run_statements_apply", never)
    argv = APPLY_ARGV + ["--dir", str(tmp_path)] + (["--dry-run"] if dry_run else [])
    assert _cli(monkeypatch, argv) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]


def test_apply_holds_maintenance_mode_and_a_dry_run_does_not(monkeypatch, tmp_path):
    import argparse

    import worker.cli as cli_module

    def args(dry_run):
        return argparse.Namespace(
            command="fundamentals",
            fundamentals_command="statements-apply",
            dry_run=dry_run,
        )

    assert (
        cli_module.maintenance_guarded(args(False)) == "fundamentals statements-apply"
    )
    assert cli_module.maintenance_guarded(args(True)) is None
    fetch = argparse.Namespace(
        command="fundamentals", fundamentals_command="statements-check-fetch"
    )
    assert cli_module.maintenance_guarded(fetch) is None
    assert cli_module.backfill_command(fetch) == "fundamentals statements-check-fetch"
    assert cli_module.research_command_refusal(fetch) is None


def test_the_cli_parses_both_commands(monkeypatch, tmp_path):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    (tmp_path / "research-db.json").write_text('{"purpose": "research_history"}')
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")
    seen = {}
    monkeypatch.setattr(
        cli_module,
        "run_check_fetch",
        lambda *a: seen.setdefault("fetch", a) and {"status": "success"},
    )
    monkeypatch.setattr(
        cli_module,
        "run_statements_apply",
        lambda *a, **k: seen.setdefault("apply", (a, k)) and {"status": "success"},
    )
    base = ["--start", "2013Q1", "--end", "2026Q3", "--dir", "/x"]
    assert _cli(monkeypatch, ["fundamentals", "statements-check-fetch", *base]) == 0
    argv = ["fundamentals", "statements-apply", *base, "--dry-run"]
    assert _cli(monkeypatch, argv) == 0
    assert seen["fetch"] == ("/x", "2013Q1", "2026Q3")
    assert seen["apply"] == (
        ("/x", "2013Q1", "2026Q3"),
        {"dry_run": True, "exclude_file": None},
    )


def _xbrl_insurer(factory, tmp_path, quarter, stored_format):
    """xbrl-apply on a delisted insurer and a listed one t163sb04 has as STORED_FORMAT."""

    with factory() as db:
        listed = add_instrument(db, "2823", status="active")
        db.add(
            FundamentalSnapshot(
                instrument_id=listed.id,
                period_end=quarter.period_end,
                fiscal_period=f"Q{quarter.quarter}",
                announcement_date=quarter.period_end,
                eps=1.0,
                data_json={"report_format": stored_format},
                source=qx.T163SB04_SOURCE,
                data_as_of=quarter.period_end.isoformat(),
            )
        )
        gone = add_instrument(db, "2833", bars=())
        db.add(
            MarketBar(
                instrument_id=gone.id,
                trading_date=quarter.period_end + timedelta(days=10),
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1000,
            )
        )
        db.commit()
    members = dict(
        [
            company("2823", eps="1.00", industry="ins", quarter=quarter),
            company("2833", eps="0.50", industry="ins", quarter=quarter),
        ]
    )
    store(tmp_path, quarter, archive(members))
    with factory() as db:
        return qx.apply_archives(db, tmp_path, quarter, quarter)


def test_xbrl_apply_before_2026_still_checks_insurers_as_the_legacy_format(
    factory, tmp_path
):
    first = _xbrl_insurer(factory, tmp_path, Q, "insurance_legacy")
    assert first["status"] == "success", first
    assert first["quarters"]["2014Q2"]["inserted"] == 1
    with factory() as db:
        row = db.scalar(
            select(FundamentalSnapshot).where(FundamentalSnapshot.source == qx.SOURCE)
        )
        assert row.data_json["report_format"] == "insurance_legacy"
    with factory() as db:
        again = qx.apply_archives(db, tmp_path, Q, Q)
    assert again["status"] == "success"
    assert again["quarters"]["2014Q2"]["inserted"] == 0
    assert again["quarters"]["2014Q2"]["unchanged"] == 1


@pytest.mark.parametrize(
    "stored_format, status", [("insurance", "success"), ("insurance_legacy", "failed")]
)
def test_xbrl_apply_from_2026_checks_insurers_as_ifrs17(
    factory, tmp_path, stored_format, status
):
    result = _xbrl_insurer(factory, tmp_path, Quarter(2026, 1), stored_format)
    assert result["status"] == status, result


def test_too_many_eps_differences_stop(factory, tmp_path):
    with factory() as db:
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0)
        other = add_instrument(db, "6005", status="active")
        add_t163sb04(db, other, 9.9)
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2330", eps="4.00"), company("6005", eps="1.00")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "failed" and "eps different 1" in result["aborted"]
    with factory() as db:
        assert written(db) == {}


def test_a_quarter_with_no_income_row_to_compare_stops(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    store(
        tmp_path,
        Q,
        archive(dict([company("2475"), company("2330")])),
        page_html({"2330": ("10000", "6000")}),
    )
    result = apply(factory, tmp_path)
    assert result["status"] == "failed"
    assert "t163sb04／snapshot" in result["aborted"]


def test_post_once_asks_once_and_refuses_anything_but_200(monkeypatch):
    throttled, posted = [], []
    monkeypatch.setattr(sources, "_throttle_official_host", throttled.append)

    class Answer:
        def __init__(self, status):
            self.status_code, self.text = status, "<html>page</html>"

    answers = iter([Answer(503), Answer(200)])

    def post(url, **kwargs):
        posted.append(kwargs["data"])
        return next(answers)

    monkeypatch.setattr(qs.httpx, "post", post)
    form = {"TYPEK": "sii"}
    with pytest.raises(OfficialDataError, match="HTTP 503"):
        qs.post_once(qs.CHECK_ENDPOINT, form)
    assert posted == [form] and throttled == [qs.CHECK_ENDPOINT]
    assert qs.post_once(qs.CHECK_ENDPOINT, form) == "<html>page</html>"
    assert len(posted) == 2


# --- availability: a foreign issuer's Q2 (#1101) -----------------------------------------


@pytest.mark.parametrize(
    "quarter, foreign_day, domestic_day",
    [
        # Before 2021 a foreign issuer's Q2 is due with everyone's, 8/14.
        (Quarter(2020, 2), date(2020, 8, 14), date(2020, 8, 14)),
        # From 2021 it is 8/31; 8/14/2021 was a Saturday, so the others' is 8/16.
        (Quarter(2021, 2), date(2021, 8, 31), date(2021, 8, 16)),
        # 8/31/2024 was a Saturday: moved to the next session.
        (Quarter(2024, 2), date(2024, 9, 2), date(2024, 8, 14)),
    ],
)
def test_a_foreign_issuer_s_q2_is_available_on_its_own_deadline(
    factory, tmp_path, quarter, foreign_day, domestic_day
):
    with factory() as db:
        for symbol, name in (("8427", "基勝-KY"), ("1234", "國內")):
            item = Instrument(
                market="TW",
                exchange="TWSE",
                symbol=symbol,
                name=name,
                instrument_type="stock",
                status="delisted",
            )
            db.add(item)
            db.flush()
            db.add(
                MarketBar(
                    instrument_id=item.id,
                    trading_date=quarter.period_end + timedelta(days=10),
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adj_close=10,
                    volume=1000,
                )
            )
        survivor = add_instrument(db, "2330", status="active")
        add_t163sb04(db, survivor, 4.0, quarter=quarter)
        db.commit()
    store(
        tmp_path,
        quarter,
        archive(
            dict(
                company(symbol, eps=eps, quarter=quarter)
                for symbol, eps in (
                    ("8427", "1.00"),
                    ("1234", "2.00"),
                    ("2330", "4.00"),
                )
            )
        ),
        page_html({"2330": ("10000", "6000")}, quarter),
    )
    result = apply(factory, tmp_path, quarter, quarter)
    assert result["status"] == "success", result
    with factory() as db:
        rows = written(db)
    foreign = rows[("TWSE", "8427")]
    assert foreign.announcement_date == foreign_day
    assert foreign.data_json["statutory_deadline"] == foreign_day.isoformat()
    for symbol in ("1234", "2330"):
        row = rows[("TWSE", symbol)]
        assert row.announcement_date == domestic_day
        assert "deadline_rule" not in row.data_json
        assert "foreign_issuer_basis" not in row.data_json
    if quarter.year >= 2021:
        assert foreign.data_json["deadline_rule"] == qf.FOREIGN_RULE
        assert foreign.data_json["foreign_issuer_basis"] == fi.BASIS_NAME
    else:
        assert "deadline_rule" not in foreign.data_json
    # The run keys its deadline cache by the rule, so a rerun changes nothing.
    assert apply(factory, tmp_path, quarter, quarter)["changed"] == 0
