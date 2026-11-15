"""Quarterly EPS of delisted and transferred companies from the MOPS XBRL archives (#781).

The two fixtures are single members of archives fetched while probing (2026-11-15,
#781 AC-2): 3671's consolidated 2014Q2 instance (``.xml``) and 4205's individual
2024Q3 instance (inline ``.html``), line endings LF and trailing blanks removed.  Each
test builds its archive in memory from them or from small instances written here.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import zipfile
from datetime import date, datetime, timedelta, timezone
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
    RawPayload,
)
from worker import quarterly_xbrl as qx
from worker import sources
from worker.quarterly_fundamentals import Quarter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mops_tifrs"
XML_MEMBER = "tifrs-fr1-m2-ci-cr-3671-2014Q2.xml"
HTML_MEMBER = "tifrs-fr1-m1-ci-ir-4205-2024Q3.html"
Q = Quarter(2014, 2)
NOW = datetime(2026, 11, 16, 3, 0)  # 11:00 Taipei
FETCHED = "2026-11-16T03:00:00+00:00"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in XBRL archive tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    frozen_utcnow.at = NOW
    return frozen_utcnow


# --- instances and archives -----------------------------------------------------------


def instance(
    facts: list[tuple[str, str]],
    quarter: Quarter = Q,
    *,
    concept: str = "ifrs:BasicEarningsLossPerShare",
    prolog: str = "",
) -> bytes:
    """A small XML instance; FACTS are (context id, text) of the EPS concept."""

    start, end = f"{quarter.year}-01-01", quarter.period_end.isoformat()
    three = (quarter.period_end - timedelta(days=80)).replace(day=1).isoformat()
    body = "".join(
        f'<{concept} contextRef="{context}" decimals="2" unitRef="TWD">{text}</{concept}>'
        for context, text in facts
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{prolog}'
        '<xbrl xmlns="http://www.xbrl.org/2003/instance"'
        ' xmlns:ifrs="http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs"'
        ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
        f'<context id="YTD"><entity><identifier scheme="s">1</identifier></entity>'
        f"<period><startDate>{start}</startDate><endDate>{end}</endDate></period></context>"
        f'<context id="QTR"><entity><identifier scheme="s">1</identifier></entity>'
        f"<period><startDate>{three}</startDate><endDate>{end}</endDate></period></context>"
        f'<context id="YTD_dim"><entity><identifier scheme="s">1</identifier>'
        '<segment><xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></segment>'
        f"</entity><period><startDate>{start}</startDate><endDate>{end}</endDate></period>"
        f"</context>{body}</xbrl>"
    ).encode("utf-8")


def inline(attributes: str, text: str, quarter: Quarter = Q) -> bytes:
    """A small inline XBRL instance with one EPS fact in the year-to-date context."""

    start, end = f"{quarter.year}-01-01", quarter.period_end.isoformat()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'
        ' xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><body>'
        '<xbrli:context id="YTD"><xbrli:entity><xbrli:identifier scheme="s">1'
        "</xbrli:identifier></xbrli:entity><xbrli:period>"
        f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
        "</xbrli:period></xbrli:context>"
        '<ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare" contextRef="YTD"'
        f' unitRef="EarningsPerShare" decimals="2" {attributes}>{text}</ix:nonFraction>'
        "</body></html>"
    ).encode("utf-8")


def member_name(symbol: str, *, industry: str = "ci", kind: str = "cr", quarter=Q):
    return f"tifrs-fr1-m1-{industry}-{kind}-{symbol}-{quarter.label}.xml"


def archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, data in members.items():
            handle.writestr(name, data)
    return buffer.getvalue()


def eps_member(symbol: str, eps: str, **name) -> tuple[str, bytes]:
    quarter = name.get("quarter", Q)
    # A first quarter's three months are its year to date: the same EPS.
    three_months = eps if quarter.quarter == 1 else "0.01"
    return member_name(symbol, **name), instance(
        [("YTD", eps), ("QTR", three_months)], quarter
    )


def store(directory: Path, quarter: Quarter, data: bytes) -> None:
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


# --- parsing --------------------------------------------------------------------------


def _fact_text(data: bytes, context: str) -> str:
    pattern = (
        rb'<ifrs:BasicEarningsLossPerShare\b[^>]*contextRef="'
        + context.encode()
        + rb'"[^>]*>([^<]*)<'
    )
    return re.search(pattern, data).group(1).decode().strip()


def test_the_xml_fixture_reads_the_year_to_date_basic_eps():
    data = (FIXTURES / XML_MEMBER).read_bytes()
    eps, context = qx.parse_eps(data, Q)
    assert context == "From20140101To20140630"
    assert eps == float(_fact_text(data, "From20140101To20140630"))


def test_the_inline_fixture_reads_the_year_to_date_basic_eps():
    data = (FIXTURES / HTML_MEMBER).read_bytes()
    quarter = Quarter(2024, 3)
    eps, context = qx.parse_eps(data, quarter)
    assert context == "From20240101To20240930"
    fact = re.search(
        rb'<ix:nonFraction[^>]*name="ifrs-full:BasicEarningsLossPerShare"'
        rb'[^>]*contextRef="From20240101To20240930"[^>]*>([^<]*)<',
        data,
    )
    text = fact.group(1).decode().strip().replace(",", "")
    sign = -1 if 'sign="-"' in fact.group(0).decode() else 1
    assert eps == sign * float(text)


def test_the_quarter_and_dimension_contexts_are_not_read():
    data = instance([("QTR", "9.99"), ("YTD_dim", "8.88"), ("YTD", "1.25")])
    assert qx.parse_eps(data, Q) == (1.25, "YTD")
    assert qx.parse_eps(instance([("QTR", "9.99")]), Q) == (None, None)


def test_a_first_quarter_reads_every_context_of_its_three_months():
    first = Quarter(2014, 1)
    assert qx.parse_eps(instance([("YTD", "0.50"), ("QTR", "0.50")], first), first) == (
        0.5,
        "QTR,YTD",
    )
    with pytest.raises(qx.MemberError, match="disagree"):
        qx.parse_eps(instance([("YTD", "0.50"), ("QTR", "0.51")], first), first)


def test_duplicate_facts_must_agree():
    assert qx.parse_eps(instance([("YTD", "1.25"), ("YTD", "1.25")]), Q)[0] == 1.25
    with pytest.raises(qx.MemberError, match="disagree"):
        qx.parse_eps(instance([("YTD", "1.25"), ("YTD", "1.26")]), Q)


def test_the_concept_is_matched_by_its_local_name():
    data = instance([("YTD", "-0.40")], concept="ifrs:BasicEarningsLossPerShare")
    assert qx.parse_eps(data, Q)[0] == -0.4
    other = instance([("YTD", "0.40")], concept="ifrs:DilutedEarningsLossPerShare")
    assert qx.parse_eps(other, Q) == (None, None)


@pytest.mark.parametrize(
    "attributes, text, expected",
    [
        ('format="ixt:numdotdecimal" scale="0"', "1.25", 1.25),
        ('format="ixt:num-dot-decimal" scale="0" sign="-"', "0.37", -0.37),
        ('format="ixt:numdotdecimal" scale="0"', "1,001.50", 1001.5),
        ('format="ixt:numdotdecimal" scale="-2"', "125", 1.25),
        ('format="ixt:fixed-zero"', "-", 0.0),
        ('xsi:nil="true"', "", None),
    ],
)
def test_inline_formats_scale_sign_and_nil(attributes, text, expected):
    assert qx.parse_eps(inline(attributes, text), Q)[0] == expected


def test_an_unknown_inline_format_is_refused():
    with pytest.raises(qx.MemberError, match="unknown inline XBRL format"):
        qx.parse_eps(inline('format="ixt:numwordsen"', "one"), Q)


@pytest.mark.parametrize(
    "prolog",
    [
        '<!DOCTYPE xbrl [<!ENTITY e "x">]>',
        '<!DOCTYPE xbrl SYSTEM "http://example.test/x.dtd">',
    ],
)
def test_a_doctype_or_entity_is_refused_before_parsing(prolog):
    with pytest.raises(qx.MemberError, match="DOCTYPE or an entity"):
        qx.parse_eps(instance([("YTD", "1.00")], prolog=prolog), Q)


def test_not_xml_is_a_member_error():
    with pytest.raises(qx.MemberError, match="not XML"):
        qx.parse_eps(b"<xbrl><unclosed></xbrl>", Q)


# --- the archive ----------------------------------------------------------------------


def test_member_names_are_checked_and_the_best_kind_is_chosen():
    data = archive(
        {
            member_name("1101", kind="ir"): b"x",
            member_name("1101", kind="cr"): b"x",
            member_name("5864", industry="bd", kind="er"): b"x",
            member_name("5864", industry="bd", kind="ir"): b"x",
            member_name("6026", kind="xx"): b"x",
        }
    )
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        chosen = qx.best_members(qx.archive_members(handle, Q))
    assert {symbol: m.kind for symbol, m in chosen.items()} == {
        "1101": "cr",
        "5864": "ir",
    }


def test_two_instances_of_one_kind_fail_the_archive():
    data = archive(
        {member_name("1101"): b"x", member_name("1101", industry="basi"): b"x"}
    )
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        with pytest.raises(qx.ArchiveError, match="two cr instances of 1101"):
            qx.best_members(qx.archive_members(handle, Q))


@pytest.mark.parametrize(
    "name, message",
    [
        ("../tifrs-fr1-m1-ci-cr-1101-2014Q2.xml", "unexpected member"),
        ("tifrs-fr1-m1-ci-cr-1101-2014Q2.exe", "unexpected member"),
        ("tifrs-fr1-m1-ci-cr-1101-2014Q3.xml", "another quarter"),
    ],
)
def test_an_unexpected_member_fails_the_archive(name, message):
    data = archive({name: b"x"})
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        with pytest.raises(qx.ArchiveError, match=message):
            qx.archive_members(handle, Q)


def test_the_member_count_is_limited(monkeypatch):
    monkeypatch.setattr(qx, "MAX_MEMBERS", 2)
    data = archive({member_name(s): b"x" for s in ("1101", "1102", "1103")})
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        with pytest.raises(qx.ArchiveError, match="limit 2"):
            qx.archive_members(handle, Q)


def test_a_member_over_its_limit_is_refused_while_it_is_read(monkeypatch):
    monkeypatch.setattr(qx, "MAX_MEMBER_BYTES", 1000)
    monkeypatch.setattr(qx, "READ_CHUNK", 100)
    data = archive({member_name("1101"): b"a" * 5000})
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        (member,) = qx.archive_members(handle, Q)
        with pytest.raises(qx.ArchiveError, match="over 1000 bytes"):
            qx.ReadBudget().read(handle, member)


def test_the_total_read_is_limited():
    data = archive({member_name("1101"): b"a" * 600, member_name("1102"): b"b" * 600})
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        first, second = qx.archive_members(handle, Q)
        budget = qx.ReadBudget(limit=1000)
        assert budget.read(handle, first) == b"a" * 600
        with pytest.raises(qx.ArchiveError, match="over 1000 bytes uncompressed"):
            budget.read(handle, second)


def test_a_truncated_archive_is_not_a_zip(tmp_path):
    path = tmp_path / "cut.zip"
    path.write_bytes(archive(dict([eps_member("1101", "1.00")]))[:-30])
    with pytest.raises(qx.ArchiveError, match="not a whole zip"):
        qx.check_archive(path, Q)


def test_the_window_comes_from_the_evidence_rule():
    # Five quarters of at most 92 days, the 200-day staleness of
    # tools/research/evidence_lib.py, and a margin (#781 decision 6894553670).
    assert qx.EVIDENCE_WINDOW_DAYS == 5 * 92 + 200 + 10 == 670


# --- apply ----------------------------------------------------------------------------


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'xbrl.db'}")
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


def add_t163sb04(db, item, eps, report_format="general"):
    db.add(
        FundamentalSnapshot(
            instrument_id=item.id,
            period_end=Q.period_end,
            fiscal_period="Q2",
            announcement_date=date(2014, 8, 14),
            eps=eps,
            data_json={"report_format": report_format},
            source=qx.T163SB04_SOURCE,
            data_as_of=Q.period_end.isoformat(),
        )
    )


def seed(db):
    """The listed survivor 2330, delisted 2475, transferred 1597 and its listed twin."""

    survivor = add_instrument(db, "2330", status="active")
    add_t163sb04(db, survivor, 4.0)
    add_instrument(db, "2475")
    twin = add_instrument(db, "1597", status="active")
    add_t163sb04(db, twin, 2.5)
    add_instrument(db, "1597", exchange="TPEx", status="transferred")
    db.commit()


SEED_ARCHIVE = dict(
    [
        eps_member("2330", "4.00"),
        eps_member("2475", "-0.31"),
        eps_member("1597", "2.50"),
        eps_member("8888", "1.00"),  # a code the database does not know
    ]
)


def apply(factory, directory, start=Q, end=Q, **kwargs):
    with factory() as db:
        return qx.apply_archives(db, directory, start, end, **kwargs)


def written(db):
    query = (
        select(Instrument.exchange, Instrument.symbol, FundamentalSnapshot)
        .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
        .where(FundamentalSnapshot.source == qx.SOURCE)
        .order_by(Instrument.symbol, Instrument.exchange)
    )
    return {(ex, sym): row for ex, sym, row in db.execute(query).all()}


def test_only_delisted_and_transferred_instruments_get_the_quarter(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(SEED_ARCHIVE))
    result = apply(factory, directory)
    assert result["status"] == "success", result
    counts = result["quarters"]["2014Q2"]
    assert (counts["check_same"], counts["check_different"]) == (2, 0)
    assert counts["inserted"] == 2 and counts["not_in_db"] == 1
    assert counts["not_target"] == 1  # 2330 is active only
    with factory() as db:
        rows = written(db)
        assert set(rows) == {("TWSE", "2475"), ("TPEx", "1597")}
        row = rows[("TWSE", "2475")]
        assert row.eps == -0.31 and row.fiscal_period == "Q2" and row.revenue is None
        # 2014-08-14 is a Thursday: the general deadline, no calendar stored.
        assert row.announcement_date == date(2014, 8, 14)
        assert row.data_json["announcement_basis"] == "statutory_deadline"
        assert row.data_json["report_format"] == "general"
        assert row.data_json["member"] == member_name("2475")
        assert (
            row.data_json["member_sha256"]
            == hashlib.sha256(SEED_ARCHIVE[member_name("2475")]).hexdigest()
        )
        raw = db.get(RawPayload, row.raw_payload_id)
        data = (directory / "tifrs-2014Q2.zip").read_bytes()
        assert (
            raw.source == qx.RAW_SOURCE
            and raw.sha256 == hashlib.sha256(data).hexdigest()
        )
        assert raw.endpoint == qx.archive_url(Q)
        stored = Path(raw.payload_path)
        assert stored.read_bytes() == data and stored.name == f"{raw.sha256}.zip"
        assert stored.parent == sources.RAW_DIR / "mops_tifrs" / "2026" / "11" / "16"
        assert (
            json.loads(stored.with_name(f"{raw.sha256}.meta.json").read_text())[
                "sha256"
            ]
            == raw.sha256
        )
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == qx.RUN_TYPE)
        )
        assert run.status == "success" and run.records == 2
        used = run.metadata_json["coverage_manifest"]["2014Q2"]["used_members"]
        assert sorted(used) == [member_name("1597"), member_name("2475")]


def test_a_rerun_changes_nothing_and_a_new_instrument_is_written(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    data = archive({**SEED_ARCHIVE, **dict([eps_member("2384", "0.10")])})
    store(directory, Q, data)
    assert apply(factory, directory)["quarters"]["2014Q2"]["inserted"] == 2
    with factory() as db:
        before = {key: row.id for key, row in written(db).items()}
        # A research batch created an older delisted company since.
        add_instrument(db, "2384")
        db.commit()
    again = apply(factory, directory)["quarters"]["2014Q2"]
    assert (again["inserted"], again["unchanged"]) == (1, 2)
    with factory() as db:
        rows = written(db)
        assert {key: rows[key].id for key in before} == before
        assert ("TWSE", "2384") in rows
        assert db.scalar(select(RawPayload.id).where(RawPayload.id > 1)) is None


@pytest.mark.parametrize("offset, inserted", [(669, 1), (670, 1), (671, 0)])
def test_the_window_edge(factory, tmp_path, offset, inserted):
    with factory() as db:
        add_instrument(db, "2475", bars=(offset,))
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2475", "1.00")])))
    counts = apply(factory, directory)["quarters"]["2014Q2"]
    assert counts["inserted"] == inserted
    assert counts["outside_window"] == 1 - inserted


def test_a_bar_before_the_quarter_end_does_not_count(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475", bars=(-1,))
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2475", "1.00")])))
    assert apply(factory, directory)["quarters"]["2014Q2"]["outside_window"] == 1


def test_a_row_of_another_source_is_kept(factory, tmp_path):
    with factory() as db:
        item = add_instrument(db, "2475")
        add_t163sb04(db, item, 9.0)  # the check reads it too
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2475", "9.00")])))
    counts = apply(factory, directory)["quarters"]["2014Q2"]
    assert counts["existing_other_source"] == 1 and counts["inserted"] == 0


def test_excluded_and_unknown_format_companies_are_counted(factory, tmp_path):
    with factory() as db:
        reused = add_instrument(db, "2475")
        add_instrument(db, "6666")
        db.commit()
        reused_id = reused.id
    directory = tmp_path / "xbrl"
    store(
        directory,
        Q,
        archive(
            dict(
                [eps_member("2475", "1.00"), eps_member("6666", "1.00", industry="zz")]
            )
        ),
    )
    counts = apply(factory, directory, excluded=frozenset({reused_id}))["quarters"][
        "2014Q2"
    ]
    assert (counts["excluded"], counts["unknown_format"], counts["inserted"]) == (
        1,
        1,
        0,
    )


def test_the_deadline_follows_the_industry_code(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2888")
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2888", "0.50", industry="fh")])))
    apply(factory, directory)
    with factory() as db:
        row = written(db)[("TWSE", "2888")]
        assert row.data_json["report_format"] == "holding"
        assert row.announcement_date == date(2014, 9, 1)  # 8/31 is a Sunday


def test_a_different_eps_stops_before_the_quarter_is_written(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    earlier = Quarter(2014, 1)
    store(
        directory, earlier, archive(dict([eps_member("2475", "0.10", quarter=earlier)]))
    )
    with factory() as db:
        add_instrument(db, "2475", exchange="TPEx", bars=(-80,))
        db.commit()
    changed = {**SEED_ARCHIVE, **dict([eps_member("2330", "4.01")])}
    store(directory, Q, archive(changed))
    result = apply(factory, directory, start=earlier, end=Q)
    assert result["status"] == "failed"
    assert "停下來問" in result["aborted"] and "different 1" in result["aborted"]
    assert result["quarters"]["2014Q1"]["status"] == "success"
    assert result["quarters"]["2014Q2"]["status"] == "failed"
    with factory() as db:
        periods = {row.period_end for row in written(db).values()}
        assert periods == {earlier.period_end}
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == qx.RUN_TYPE)
        )
        assert run.status == "failed" and "2014Q2" in run.error


def test_a_different_report_format_also_stops(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    members = {k: v for k, v in SEED_ARCHIVE.items() if "-2330-" not in k}
    store(
        directory,
        Q,
        archive({**members, **dict([eps_member("2330", "4.00", industry="basi")])}),
    )
    result = apply(factory, directory)
    assert result["status"] == "failed" and "format mismatch 1" in result["aborted"]
    with factory() as db:
        assert written(db) == {}


def test_an_archive_that_is_not_the_manifests_is_refused(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(SEED_ARCHIVE))
    (directory / "tifrs-2014Q2.zip").write_bytes(
        archive(dict([eps_member("2475", "9")]))
    )
    result = apply(factory, directory)
    assert result["status"] == "failed" and "is not the manifest's" in result["aborted"]


def test_a_quarter_not_downloaded_refuses_before_anything(factory, tmp_path):
    result = apply(factory, tmp_path / "xbrl")
    assert result == {"status": "failed", "error": "not downloaded: 2014Q2"}
    with factory() as db:
        assert db.scalar(select(IngestionRun.id)) is None


def test_a_dry_run_writes_nothing(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(SEED_ARCHIVE))
    result = apply(factory, directory, dry_run=True)
    assert result["status"] == "success" and result["run_id"] is None
    assert result["quarters"]["2014Q2"]["would_insert"] == 2
    with factory() as db:
        assert written(db) == {} and db.scalar(select(RawPayload.id)) is None
    assert not (sources.RAW_DIR / "mops_tifrs").exists()


def test_an_unreadable_member_is_counted_and_skipped(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive({member_name("2475"): b"<!DOCTYPE x><xbrl/>"}))
    counts = apply(factory, directory)["quarters"]["2014Q2"]
    assert counts["unreadable"] == 1 and counts["inserted"] == 0


def test_the_fixtures_apply_end_to_end(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "3671")
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive({XML_MEMBER: (FIXTURES / XML_MEMBER).read_bytes()}))
    assert apply(factory, directory)["quarters"]["2014Q2"]["inserted"] == 1


# --- fetch ----------------------------------------------------------------------------


class Getter:
    """Answers each URL with the given bytes (or status), and records the calls."""

    def __init__(self, answers):
        self.answers = answers
        self.urls: list[str] = []

    def __call__(self, url, target, max_bytes):
        self.urls.append(url)
        answer = self.answers[url]
        if isinstance(answer, int):
            return answer
        target.write_bytes(answer)
        return 200


def fake_clock():
    state = {"now": 0.0, "sleeps": []}

    def clock():
        return state["now"]

    def sleep(seconds):
        state["sleeps"].append(seconds)
        state["now"] += seconds

    return state, clock, sleep


DAYTIME = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)  # 11:00 Taipei


def fetch(directory, getter, start=Q, end=Q, *, now=DAYTIME):
    state, clock, sleep = fake_clock()
    result = qx.fetch_archives(
        directory, start, end, getter=getter, sleep=sleep, clock=clock, now=lambda: now
    )
    return result, state


def test_fetch_stores_the_archive_and_keeps_it_on_a_rerun(tmp_path):
    data = archive(SEED_ARCHIVE)
    getter = Getter({qx.archive_url(Q): data})
    result, _ = fetch(tmp_path, getter)
    assert result["status"] == "success" and result["downloaded"] == ["2014Q2"]
    entry = qx.read_manifest(tmp_path)["quarters"]["2014Q2"]
    assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    assert entry["members"] == 4 and entry["fetched_at"] == DAYTIME.isoformat()
    again, _ = fetch(tmp_path, getter)
    assert again["kept"] == ["2014Q2"] and len(getter.urls) == 1
    assert not list(tmp_path.glob("*.part"))


def test_fetch_waits_between_requests(tmp_path):
    quarters = [Quarter(2014, 1), Q, Quarter(2014, 3)]
    getter = Getter(
        {
            qx.archive_url(q): archive(dict([eps_member("1101", "1", quarter=q)]))
            for q in quarters
        }
    )
    result, state = fetch(tmp_path, getter, start=quarters[0], end=quarters[-1])
    assert result["status"] == "success" and len(getter.urls) == 3
    assert state["sleeps"] == [qx.REQUEST_INTERVAL_SECONDS] * 2


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc),  # 20:30 Taipei
        datetime(2026, 11, 16, 15, 29, tzinfo=timezone.utc),  # 23:29
        datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc),  # 08:00
    ],
)
def test_fetch_sends_nothing_in_quiet_hours(tmp_path, moment):
    getter = Getter({})
    result, _ = fetch(tmp_path, getter, now=moment)
    assert result["status"] == "partial" and "quiet hours" in result["stopped"]
    assert getter.urls == []


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc),  # 09:00 Taipei
        datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc),  # 23:30
    ],
)
def test_quiet_hours_end_where_they_say(moment):
    assert not qx.in_quiet_hours(moment)


def test_fetch_stops_after_three_failed_quarters(tmp_path):
    quarters = qx.quarters_between(Quarter(2014, 1), Quarter(2015, 1))
    answers = {qx.archive_url(q): 500 for q in quarters}
    answers[qx.archive_url(Quarter(2014, 2))] = b""  # empty
    answers[qx.archive_url(Quarter(2014, 3))] = b"not a zip"
    getter = Getter(answers)
    result, _ = fetch(tmp_path, getter, start=quarters[0], end=quarters[-1])
    assert result["status"] == "failed" and "停下來問" in result["stopped"]
    assert len(getter.urls) == 3
    assert set(result["failed"]) == {"2014Q1", "2014Q2", "2014Q3"}
    assert "HTTP 500" in result["failed"]["2014Q1"]
    assert "empty" in result["failed"]["2014Q2"]
    assert "not a whole zip" in result["failed"]["2014Q3"]
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.zip"))


def test_fetch_refuses_an_archive_of_another_quarter(tmp_path):
    other = Quarter(2014, 3)
    getter = Getter(
        {qx.archive_url(Q): archive(dict([eps_member("1101", "1", quarter=other)]))}
    )
    result, _ = fetch(tmp_path, getter)
    assert (
        result["status"] == "partial"
        and "another quarter" in result["failed"]["2014Q2"]
    )


def test_quarters_start_at_2013q1():
    with pytest.raises(ValueError, match="2013Q1"):
        qx.quarters_between(Quarter(2012, 4), Q)
    assert len(qx.quarters_between(Quarter(2013, 1), Quarter(2024, 3))) == 47


def test_the_cli_parses_both_commands(monkeypatch, tmp_path):
    import sys

    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    (tmp_path / "research-db.json").write_text('{"purpose": "research_history"}')
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")
    seen = {}
    monkeypatch.setattr(
        cli_module,
        "run_xbrl_fetch",
        lambda *args: seen.setdefault("fetch", args) and {"status": "success"},
    )
    monkeypatch.setattr(
        cli_module,
        "run_xbrl_apply",
        lambda *args, **kwargs: seen.setdefault("apply", (args, kwargs))
        and {"status": "success"},
    )
    for argv in (
        [
            "fundamentals",
            "xbrl-fetch",
            "--start",
            "2013Q1",
            "--end",
            "2024Q3",
            "--dir",
            "/x",
        ],
        [
            "fundamentals",
            "xbrl-apply",
            "--start",
            "2013Q1",
            "--end",
            "2024Q3",
            "--dir",
            "/x",
            "--dry-run",
        ],
    ):
        monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
        cli_module.main()
    assert seen["fetch"] == ("/x", "2013Q1", "2024Q3")
    assert seen["apply"] == (
        ("/x", "2013Q1", "2024Q3"),
        {"dry_run": True, "exclude_file": None},
    )


# --- review of PR #783 ----------------------------------------------------------------


def test_every_quarter_of_a_run_is_in_its_coverage_manifest(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    directory = tmp_path / "xbrl"
    earlier = Quarter(2014, 1)
    store(
        directory, earlier, archive(dict([eps_member("2475", "0.10", quarter=earlier)]))
    )
    store(directory, Q, archive(dict([eps_member("2475", "0.20")])))
    result = apply(factory, directory, start=earlier, end=Q)
    assert result["status"] == "success"
    with factory() as db:  # a new session reads what was committed
        run = db.get(IngestionRun, result["run_id"])
        manifest = run.metadata_json["coverage_manifest"]
        assert sorted(manifest) == ["2014Q1", "2014Q2"]
        assert list(manifest["2014Q1"]["used_members"]) == [
            member_name("2475", quarter=earlier)
        ]
        assert list(manifest["2014Q2"]["used_members"]) == [member_name("2475")]
        assert run.records == 2


def test_a_check_that_compared_nothing_stops(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    unreadable = {name: b"<xbrl/>" for name in SEED_ARCHIVE}  # no EPS anywhere
    store(directory, Q, archive(unreadable))
    result = apply(factory, directory)
    assert result["status"] == "failed" and "same 0" in result["aborted"]
    with factory() as db:
        assert written(db) == {}


def test_more_than_one_percent_missing_in_the_check_stops(factory, tmp_path):
    with factory() as db:
        seed(db)
    directory = tmp_path / "xbrl"
    members = {k: v for k, v in SEED_ARCHIVE.items() if "-1597-" not in k}
    store(directory, Q, archive(members))
    result = apply(factory, directory)
    assert result["status"] == "failed" and "missing 1" in result["aborted"]
    assert qx.CHECK_MISSING_LIMIT == 0.01


def _bad_crc(data: bytes, name: str) -> bytes:
    """DATA with one byte of NAME's stored content changed (its CRC no longer matches)."""

    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        info = handle.getinfo(name)
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    mutable = bytearray(data)
    mutable[start + info.compress_size // 2] ^= 0xFF
    return bytes(mutable)


def test_a_member_with_a_bad_crc_fails_the_quarter_and_the_run(factory, tmp_path):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    name, content = eps_member("2475", "0.20")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as handle:
        handle.writestr(name, content)
    directory = tmp_path / "xbrl"
    store(directory, Q, _bad_crc(buffer.getvalue(), name))
    result = apply(factory, directory)
    assert result["status"] == "failed" and "cannot be read" in result["aborted"]
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert run.status == "failed" and written(db) == {}


def test_an_unexpected_error_marks_the_run_failed(factory, tmp_path, monkeypatch):
    with factory() as db:
        add_instrument(db, "2475")
        db.commit()
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2475", "0.20")])))

    def broken(*args, **kwargs):
        raise KeyError("fixture bug")

    monkeypatch.setattr(qx, "apply_quarter", broken)
    with pytest.raises(KeyError):
        apply(factory, directory)
    with factory() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == qx.RUN_TYPE)
        )
        assert run.status == "failed" and "fixture bug" in run.error
        assert run.finished_at is not None


@pytest.mark.parametrize(
    "data",
    [
        "<xbrl/>".encode("utf-16"),
        b"<xbrl>\x00</xbrl>",
        b"<xbrl>" + b" " * 5000 + b"<!DOCTYPE x></xbrl>",
    ],
)
def test_utf16_nul_and_a_late_doctype_are_refused(data):
    with pytest.raises(qx.MemberError):
        qx.parse_eps(data, Q)


def test_a_scale_that_is_not_an_integer_is_a_member_error():
    with pytest.raises(qx.MemberError, match="scale"):
        qx.parse_eps(inline('format="ixt:numdotdecimal" scale="x"', "1.25"), Q)


def test_two_instances_of_a_lower_kind_also_fail_the_archive():
    data = archive(
        {
            member_name("1101", kind="cr"): b"x",
            member_name("1101", kind="ir"): b"x",
            member_name("1101", industry="basi", kind="ir"): b"x",
        }
    )
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        with pytest.raises(qx.ArchiveError, match="two ir instances of 1101"):
            qx.best_members(qx.archive_members(handle, Q))


def test_an_excluded_instrument_already_written_is_counted(factory, tmp_path):
    with factory() as db:
        item = add_instrument(db, "2475")
        db.commit()
        item_id = item.id
    directory = tmp_path / "xbrl"
    store(directory, Q, archive(dict([eps_member("2475", "0.20")])))
    assert apply(factory, directory)["quarters"]["2014Q2"]["inserted"] == 1
    counts = apply(factory, directory, excluded=frozenset({item_id}))["quarters"][
        "2014Q2"
    ]
    assert (counts["excluded"], counts["excluded_already_written"]) == (1, 1)


def test_the_inline_fixture_applies_end_to_end(factory, tmp_path):
    quarter = Quarter(2024, 3)
    with factory() as db:
        item = add_instrument(db, "4205", bars=())
        db.add(
            MarketBar(
                instrument_id=item.id,
                trading_date=quarter.period_end + timedelta(days=5),
                close=10,
                adj_close=10,
            )
        )
        db.commit()
    directory = tmp_path / "xbrl"
    store(
        directory,
        quarter,
        archive({HTML_MEMBER: (FIXTURES / HTML_MEMBER).read_bytes()}),
    )
    result = apply(factory, directory, start=quarter, end=quarter)
    assert result["quarters"]["2024Q3"]["inserted"] == 1
    with factory() as db:
        row = written(db)[("TWSE", "4205")]
        assert row.data_json["report_kind"] == "ir"
        assert row.data_json["context"] == "From20240101To20240930"
        assert row.announcement_date == date(2024, 11, 14)


def test_the_staleness_matches_the_research_tools():
    source = (
        Path(__file__).resolve().parents[2] / "tools" / "research" / "evidence_lib.py"
    ).read_text(encoding="utf-8")
    stated = re.search(r"^QUARTER_STALE_DAYS = (\d+)$", source, re.M)
    assert stated and int(stated.group(1)) == qx.QUARTER_STALE_DAYS


class FakeResponse:
    def __init__(self, status, chunks):
        self.status_code = status
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self):
        yield from self.chunks


def test_download_stops_over_its_limit_and_is_throttled(tmp_path, monkeypatch):
    throttled = []
    monkeypatch.setattr(sources, "_throttle_official_host", throttled.append)
    monkeypatch.setattr(
        qx.httpx, "stream", lambda *a, **k: FakeResponse(200, [b"a" * 600, b"b" * 600])
    )
    with pytest.raises(qx.ArchiveError, match="over 1000 bytes"):
        qx.download("https://mopsov.twse.com.tw/x", tmp_path / "x.part", 1000)
    assert throttled == ["https://mopsov.twse.com.tw/x"]
    monkeypatch.setattr(qx.httpx, "stream", lambda *a, **k: FakeResponse(503, []))
    assert qx.download("https://mopsov.twse.com.tw/x", tmp_path / "y.part", 1000) == 503


def _cli(monkeypatch, argv):
    import sys

    import worker.cli as cli_module

    monkeypatch.setattr(sys, "argv", ["worker.cli", *argv])
    try:
        cli_module.main()
    except SystemExit as exc:
        return exc.code
    return 0


APPLY_ARGV = ["fundamentals", "xbrl-apply", "--start", "2014Q2", "--end", "2014Q2"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_apply_refuses_without_the_research_marker(
    monkeypatch, tmp_path, capsys, dry_run
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")

    def never(*args, **kwargs):
        raise AssertionError("no session without the research marker")

    monkeypatch.setattr(cli_module, "run_xbrl_apply", never)
    argv = APPLY_ARGV + ["--dir", str(tmp_path)] + (["--dry-run"] if dry_run else [])
    assert _cli(monkeypatch, argv) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "research-db.json" in out["error"]


def test_a_failed_apply_exits_1_and_a_dry_run_holds_no_maintenance(
    monkeypatch, tmp_path
):
    import worker.cli as cli_module

    (tmp_path / "stock.db").write_bytes(b"")
    (tmp_path / "research-db.json").write_text('{"purpose": "research_history"}')
    monkeypatch.setattr(cli_module, "DB_PATH", tmp_path / "stock.db")
    monkeypatch.setattr(
        cli_module, "run_xbrl_apply", lambda *a, **k: {"status": "failed"}
    )

    class NoHold:
        def __init__(self, *args, **kwargs):
            raise AssertionError("a dry run holds no maintenance mode")

    monkeypatch.setattr(cli_module.scheduled_job, "MaintenanceHold", NoHold)
    argv = APPLY_ARGV + ["--dir", str(tmp_path), "--dry-run"]
    assert _cli(monkeypatch, argv) == 1
