"""The gate-closing DB audit, tools/audit/ (Issue #391).

Every item has a correct and a wrong fixture.  Where the product can write
the rows (indicators, group scores, candidates), the worker writes them on a
small database and the audit, which recomputes independently, must pass
them; a test then puts back a wrong value and the item must fail.  The
official raw captures live in ``tmp_path`` and are read only with ``rb``.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, null
from sqlalchemy.orm import sessionmaker

import app.coverage as product_coverage
import app.indicators as product_indicators
import worker.mops_events as mops_events
import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    Event,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    Signal,
    TechnicalIndicator,
    ThemeGroup,
)
from worker.candidates import compute_daily_candidates
from worker.indicator_batch import compute_market_indicators

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "audit"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import audit  # noqa: E402
import audit_checks  # noqa: E402
import audit_lib  # noqa: E402
import audit_series  # noqa: E402

T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
DAILY_QUOTES = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
MI_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TWT48U = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
TWT49U = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
QUOTE_FIELDS = [
    "證券代號",
    "證券名稱",
    "成交股數",
    "成交筆數",
    "成交金額",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
]
T86_FIELDS = [
    "證券代號",
    "證券名稱",
    "外陸資買賣超股數(不含外資自營商)",
    "投信買賣超股數",
    "自營商買賣超股數",
]
MARGIN_FIELDS = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額"]
# The 4549 2026-09-08 row as the TPEx result table published it (#386 A1).
TPEX_4549 = {
    "Date": "1150908",
    "SecuritiesCompanyCode": "4549",
    "CompanyName": "桓達",
    "ClosePriceBeforeExRightsDiviend": "103.50",
    "ExRightsDiviendQuote": "101.47",
    "StockDividend": "2.029410",
    "CashDividend": "0.000000",
    "ExRightsDiviend": "除權",
    "DividendDeductedQuote": "101.47",
    "StockDivdendThousandShares": "19.99998421",
}


def sessions(start: date, count: int) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


DAYS = sessions(date(2026, 1, 5), 130)
T = DAYS[-1]


class Fixture:
    """A database with the product schema and raw captures in ``tmp_path``."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.path = tmp_path / "stock.db"
        self.engine = create_engine(f"sqlite:///{self.path}")
        enable_sqlite_foreign_keys(self.engine)
        upgrade_database(self.engine)
        self.factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.db = self.factory()
        self.raw_dir = tmp_path / "stock-data" / "raw"

    def close(self) -> None:
        self.db.close()
        self.engine.dispose()

    def instrument(
        self, exchange: str, symbol: str, kind: str = "stock", status: str = "active"
    ) -> Instrument:
        row = Instrument(
            market="TW",
            exchange=exchange,
            symbol=symbol,
            name=symbol,
            instrument_type=kind,
            status=status,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def raw(
        self,
        endpoint: str,
        day: date | str,
        payload,
        *,
        hour: int = 10,
        query: str = "?date=x",
    ) -> RawPayload:
        name = hashlib.sha256(
            f"{endpoint}{day}{hour}{json.dumps(payload, ensure_ascii=False)}".encode()
        ).hexdigest()
        path = self.raw_dir / "src" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        day_text = day if isinstance(day, str) else day.isoformat()
        row = RawPayload(
            source="fixture",
            endpoint=endpoint + query,
            payload_path=str(path),
            sha256=name,
            data_as_of=day_text,
            collected_at=datetime.fromisoformat(day_text[:10]) + timedelta(hours=hour),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def bar(
        self,
        instrument: Instrument,
        day: date,
        close: float,
        *,
        high=None,
        low=None,
        open_=None,
        volume=1000,
        raw=None,
        source=None,
        suspended=False,
        turnover=None,
    ):
        high = close if high is None else high
        low = close if low is None else low
        open_ = close if open_ is None else open_
        bar = MarketBar(
            instrument_id=instrument.id,
            trading_date=day,
            open=open_,
            high=high,
            low=low,
            close=close,
            adj_close=close,
            volume=volume,
            turnover=close * volume if turnover is None else turnover,
            source=source or instrument.exchange.lower(),
            data_as_of=datetime.combine(day, datetime.min.time()),
            collected_at=datetime.combine(day, datetime.min.time())
            + timedelta(hours=11),
            raw_payload_id=None if raw is None else raw.id,
            is_suspended=suspended,
        )
        self.db.add(bar)
        return bar

    def chip(
        self,
        instrument: Instrument,
        day: date,
        flow=(10.0, 10.0, 10.0),
        margin=100.0,
        *,
        raw=None,
        collected_hour: int = 11,
    ):
        when = datetime.combine(day, datetime.min.time()) + timedelta(
            hours=collected_hour
        )
        chip = ChipSnapshot(
            instrument_id=instrument.id,
            trading_date=day,
            foreign_buy=flow[0],
            trust_buy=flow[1],
            dealer_buy=flow[2],
            margin_balance=margin,
            margin_change=0.0,
            source="twse_t86+twse_margin",
            data_as_of=datetime.combine(day, datetime.min.time()),
            collected_at=when,
            raw_payload_id=None if raw is None else raw.id,
        )
        self.db.add(chip)
        return chip

    def commit(self) -> None:
        self.db.commit()

    def context(self) -> audit_checks.Context:
        ctx = audit_checks.Context(audit_lib.connect(self.path), audit_lib.RawFiles())
        ctx.load()
        return ctx

    def sql(self, statement: str, *args) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute(statement, args)


@pytest.fixture
def fx(tmp_path):
    fixture = Fixture(tmp_path)
    yield fixture
    fixture.close()


def results(checks) -> dict[str, str]:
    return {check.key: check.result for check in checks}


def by_key(checks, key):
    return next(check for check in checks if check.key == key)


# --- AC-1：只讀副本、拒絕正式 DB 與 daily 時段（#466 起 21:30～23:30）------------


def test_a_database_inside_stock_lab_data_is_refused(tmp_path):
    db = tmp_path / "stock-lab-data" / "stock.db"
    db.parent.mkdir()
    db.write_bytes(b"")
    noon = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
    problems = audit.refusals(db, {}, noon, 20.0, 5.0)
    assert problems and "stock-lab-data" in problems[0]


def test_a_hard_link_to_the_production_file_is_refused(tmp_path):
    data = tmp_path / "prod"
    data.mkdir()
    production = data / "stock.db"
    production.write_bytes(b"production")
    link = tmp_path / "copy" / "stock.db"
    link.parent.mkdir()
    os.link(production, link)
    noon = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
    environ = {"STOCK_DATA_DIR": str(tmp_path / "elsewhere")}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            audit,
            "production_problem",
            lambda db, env: audit_checks_production(db, env, [production]),
        )
        problems = audit.refusals(link, environ, noon, 20.0, 5.0)
    assert problems == [f"{link} is the same file as the production {production}"]
    copy = tmp_path / "real-copy" / "stock.db"
    copy.parent.mkdir()
    copy.write_bytes(b"production")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            audit,
            "production_problem",
            lambda db, env: audit_checks_production(db, env, [production]),
        )
        assert audit.refusals(copy, environ, noon, 20.0, 5.0) == []


def audit_checks_production(db, environ, production):
    from backtest_research import production_problem

    return production_problem(db, environ, production)


@pytest.mark.parametrize(
    ("utc", "refused"),
    [((13, 29), False), ((13, 30), True), ((15, 29), True), ((15, 30), False)],
)
def test_the_daily_window_is_refused(tmp_path, utc, refused):
    db = tmp_path / "stock.db"
    db.write_bytes(b"")
    now = datetime(
        2026, 11, 3, *utc, tzinfo=timezone.utc
    )  # 21:29, 21:30, 23:29, 23:30 Taipei
    problems = audit.refusals(db, {}, now, 20.0, 5.0)
    assert bool(problems) is refused
    if refused:
        assert "21:30-23:30" in problems[0]


def test_low_memory_is_refused(tmp_path):
    db = tmp_path / "stock.db"
    db.write_bytes(b"")
    noon = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
    assert audit.refusals(db, {}, noon, 4.9, 5.0) == [
        "free memory 4.9 GB is under 5.0 GB"
    ]


def test_main_exits_2_before_reading_a_refused_database(tmp_path, monkeypatch, capsys):
    db = tmp_path / "stock-lab-data" / "stock.db"
    db.parent.mkdir()
    db.write_bytes(b"not a database")
    monkeypatch.setattr(audit, "free_memory_gb", lambda: 20.0)
    assert audit.main(["--db", str(db), "--out", str(tmp_path / "out")]) == 2
    assert "refused" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_a_run_that_reaches_the_window_marks_the_rest_undetermined(fx):
    stock = fx.instrument("TWSE", "1101")
    for day in DAYS[:3]:
        fx.bar(stock, day, 10)
    fx.commit()
    taipei_2145 = datetime(2026, 11, 3, 13, 45, tzinfo=timezone.utc)
    checks, _facts = audit.run(
        fx.path, None, audit.KEYS, False, clock=lambda: taipei_2145
    )
    assert {check.result for check in checks} == {"undetermined"}
    assert all("21:30-23:30" in check.skipped for check in checks)


# A fixed daytime clock (Taipei 10:00): inside the daily window the audit skips every
# item (#391), so a test on the real clock checks nothing or fails then (#451: CI at
# Taipei 18:41 failed test_summary_lists_every_item_with_its_result with exit 3).
TAIPEI_1000 = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)


def test_the_audit_never_writes_the_database(fx):
    stock = fx.instrument("TWSE", "1101")
    for day in DAYS[:30]:
        fx.bar(stock, day, 10)
    fx.commit()
    fx.close()
    before = fx.path.read_bytes()
    checks, _facts = audit.run(
        fx.path, None, audit.KEYS, False, clock=lambda: TAIPEI_1000
    )
    assert not any(check.skipped for check in checks)
    assert fx.path.read_bytes() == before
    con = audit_lib.connect(fx.path)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("delete from market_bars")
    con.close()


def test_raw_files_are_opened_only_for_reading_bytes(fx, monkeypatch):
    stock = fx.instrument("TWSE", "1101")
    raw = fx.raw(
        MI_INDEX,
        T,
        {
            "tables": [
                {
                    "fields": QUOTE_FIELDS,
                    "data": [
                        ["1101", "x", "1,000", "1", "10,000", "10", "10", "10", "10"]
                    ],
                }
            ]
        },
    )
    fx.bar(stock, T, 10, raw=raw)
    fx.commit()
    modes = []
    original = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        if str(fx.raw_dir) in str(file):
            modes.append(mode)
        return original(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    checks = audit_checks.bars_raw(fx.context())
    assert modes and set(modes) == {"rb"}
    assert by_key(checks, "bars_raw_values").result == "pass"


def test_an_unreadable_raw_file_is_undetermined_not_failed(fx):
    stock = fx.instrument("TWSE", "1101")
    raw = fx.raw(
        MI_INDEX,
        T,
        {
            "tables": [
                {
                    "fields": QUOTE_FIELDS,
                    "data": [
                        ["1101", "x", "1,000", "1", "10,000", "10", "10", "10", "10"]
                    ],
                }
            ]
        },
    )
    fx.bar(stock, T, 10, raw=raw)
    fx.commit()
    Path(raw.payload_path).unlink()
    checks = audit_checks.bars_raw(fx.context())
    assert results(checks)["bars_raw_values"] == "undetermined"
    assert results(checks)["bars_raw_missing"] == "undetermined"
    assert not any(check.failures for check in checks)


def test_raw_files_find_a_capture_through_payload_file(tmp_path, monkeypatch):
    """#418: the path comes from app.raw_paths.payload_file; --raw-dir only adds a raw copy."""

    from app import config

    stored = r"C:\Users\YiCheng\stock-lab-data\raw\twse\2026\11\02\abc.json"
    parts = ("twse", "2026", "11", "02", "abc.json")
    mounted = tmp_path / "mount"
    monkeypatch.setattr(config, "RAW_DIR", mounted)
    monkeypatch.delenv("STOCK_STORED_RAW_DIR", raising=False)
    # A stored file that does not exist here (a container): read under STOCK_RAW_DIR,
    # or under --raw-dir when that is not there either.
    copy = tmp_path / "copy"
    assert audit_lib.RawFiles().path(stored) == mounted.joinpath(*parts)
    assert audit_lib.RawFiles(copy).path(stored) == copy.joinpath(*parts)
    mounted.joinpath(*parts[:-1]).mkdir(parents=True)
    mounted.joinpath(*parts).write_bytes(b"{}")
    assert audit_lib.RawFiles(copy).path(stored) == mounted.joinpath(*parts)
    existing = tmp_path / "x.json"
    existing.write_bytes(b"{}")
    assert audit_lib.RawFiles(tmp_path / "copy").path(str(existing)) == existing
    assert audit_lib.RawFiles().path("/data/raw/x.json") == Path("/data/raw/x.json")


# --- AC-2：每一項的正確與錯誤 fixture --------------------------------------------


def test_bars_integrity(fx):
    stock = fx.instrument("TWSE", "1101")
    for day in DAYS[:5]:
        fx.bar(stock, day, 10, high=11, low=9)
    fx.commit()
    assert audit_checks.bars_integrity(fx.context()).result == "pass"
    fx.sql(
        "update market_bars set high = 8 where trading_date = ?", DAYS[2].isoformat()
    )
    check = audit_checks.bars_integrity(fx.context())
    assert check.result == "fail" and set(check.failures) >= {"high_below_low"}


def test_bars_coverage_flags_a_drop_in_common_stock_rows(fx):
    stocks = [fx.instrument("TWSE", f"{1100 + i}") for i in range(40)] + [
        fx.instrument("TPEx", f"{6100 + i}") for i in range(40)
    ]
    for day in DAYS[:7]:
        for stock in stocks:
            fx.bar(stock, day, 10)
    fx.commit()
    assert audit_checks.bars_coverage(fx.context()).result == "pass"
    fx.sql(
        "delete from market_bars where trading_date = ? and instrument_id in (select id from instruments where exchange='TPEx' and symbol < '6102')",
        DAYS[6].isoformat(),
    )
    check = audit_checks.bars_coverage(fx.context())
    assert check.result == "fail" and list(check.failures) == ["row_count_drop"]


def quotes(*rows):
    return {"tables": [{"fields": QUOTE_FIELDS, "data": [list(row) for row in rows]}]}


def test_bars_raw_values_compare_each_bar_with_its_capture(fx):
    stock = fx.instrument("TWSE", "2330")
    raw = fx.raw(
        MI_INDEX,
        T,
        quotes(
            [
                "2330",
                "台積電",
                "1,496,730",
                "9",
                "191,331,712",
                "134.00",
                "135.00",
                "117.50",
                "128.50",
            ]
        ),
    )
    fx.bar(
        stock,
        T,
        128.5,
        open_=134.0,
        high=135.0,
        low=117.5,
        volume=1496730,
        turnover=191331712,
        raw=raw,
    )
    fx.commit()
    assert results(audit_checks.bars_raw(fx.context()))["bars_raw_values"] == "pass"
    fx.sql("update market_bars set close = 128.0")
    check = by_key(audit_checks.bars_raw(fx.context()), "bars_raw_values")
    assert check.result == "fail" and list(check.failures) == ["value"]


def test_bars_raw_missing_finds_the_7710_first_day(fx):
    """#388 A4: raw has the 10/27 quote of 7710, created later, without a bar."""

    listed = fx.instrument("TWSE", "7710", kind="ipo")
    other = fx.instrument("TWSE", "2330")
    raw = fx.raw(
        MI_INDEX,
        T,
        quotes(
            [
                "7710",
                "東擎科技",
                "1,496,730",
                "9",
                "191,331,712",
                "134.00",
                "135.00",
                "117.50",
                "128.50",
            ],
            ["2330", "台積電", "1,000", "1", "10,000", "10", "10", "10", "10"],
        ),
    )
    fx.bar(other, T, 10, raw=raw, turnover=10000)
    fx.commit()
    check = by_key(audit_checks.bars_raw(fx.context()), "bars_raw_missing")
    assert check.result == "fail"
    assert check.examples["raw_row_without_bar"] == [
        ["TWSE", "7710", T.isoformat(), "ipo", "active", 128.5, 1496730.0]
    ]
    fx.bar(
        listed,
        T,
        128.5,
        open_=134.0,
        high=135.0,
        low=117.5,
        volume=1496730,
        turnover=191331712,
        raw=raw,
    )
    fx.commit()
    checks = audit_checks.bars_raw(fx.context())
    assert results(checks)["bars_raw_missing"] == "pass"
    assert results(checks)["bars_raw_values"] == "pass"


def t86(*rows):
    return {"fields": T86_FIELDS, "data": [list(row) for row in rows]}


def test_chips_raw_institutional_uses_the_latest_capture_of_the_day(fx):
    """#387 A3: 2313 on 10/19, the 18:30 capture is revised at 21:30."""

    stock = fx.instrument("TWSE", "2313")
    first = fx.raw(T86, T, t86(["2313", "華通", "1,000", "-162,968", "5,000"]), hour=10)
    fx.raw(T86, T, t86(["2313", "華通", "1,000", "1,133,032", "5,000"]), hour=13)
    fx.chip(stock, T, (1000.0, -162968.0, 5000.0), raw=first)
    fx.commit()
    check = by_key(audit_checks.chips_raw(fx.context()), "chips_raw_institutional")
    assert check.result == "fail" and list(check.failures) == ["value"]
    fx.sql("update chip_snapshots set trust_buy = 1133032")
    assert (
        results(audit_checks.chips_raw(fx.context()))["chips_raw_institutional"]
        == "pass"
    )


def test_chips_raw_margin(fx):
    stock = fx.instrument("TWSE", "2330")
    fx.raw(
        MI_MARGN,
        T,
        {
            "tables": [
                {
                    "fields": MARGIN_FIELDS,
                    "data": [["2330", "台積電", "1", "1", "0", "1,000", "1,020"]],
                }
            ]
        },
    )
    chip = fx.chip(stock, T, margin=1020.0)
    chip.margin_change = 20.0
    fx.commit()
    assert results(audit_checks.chips_raw(fx.context()))["chips_raw_margin"] == "pass"
    fx.sql("update chip_snapshots set margin_balance = 1000")
    check = by_key(audit_checks.chips_raw(fx.context()), "chips_raw_margin")
    assert check.result == "fail" and list(check.failures) == ["value"]


def action(
    fx,
    stock,
    day: date,
    *,
    ratio=None,
    cash=None,
    reference=None,
    details=None,
    collected=None,
) -> CorporateAction:
    row = CorporateAction(
        instrument_id=stock.id,
        action_date=day,
        action_type="corporate_action",
        cash_dividend=cash,
        stock_dividend_ratio=ratio,
        reference_price=reference,
        details_json=details or {},
        source="fixture",
        data_as_of=day.isoformat(),
        collected_at=collected or datetime.combine(day, datetime.min.time()),
    )
    fx.db.add(row)
    fx.db.flush()
    return row


def test_actions_fields_find_the_4549_ratio_stored_as_a_rights_value(fx):
    """#386 A1: 4549 2026-09-08 stored 2.02941 (權值), the official ratio is 0.02."""

    stock = fx.instrument("TPEx", "4549")
    row = action(
        fx,
        stock,
        date(2026, 9, 8),
        ratio=2.02941,
        cash=0.0,
        reference=103.5,
        details=TPEX_4549,
    )
    fx.commit()
    check = audit_checks.actions_fields(fx.context())
    assert check.result == "fail"
    assert set(check.failures) == {
        "stock_ratio_vs_thousand_shares",
        "implied_reference",
    }
    row.stock_dividend_ratio = 0.019999984210000002
    fx.commit()
    assert audit_checks.actions_fields(fx.context()).result == "pass"


def twt48u(*rows):
    return [
        {
            "Code": code,
            "Date": roc,
            "Exdividend": "息",
            "CashDividend": cash,
            "StockDividendRatio": "",
        }
        for code, roc, cash in rows
    ]


def test_actions_missing_finds_an_announced_event_that_was_not_stored(fx):
    """#386 A2: TWT48U announced 2330 2026-09-16 cash 7.0; corporate_actions has nothing."""

    stock = fx.instrument("TWSE", "2330")
    for day in (date(2026, 9, 15), date(2026, 9, 16)):
        fx.bar(stock, day, 2385)
    fx.raw(TWT48U, "2026-06-08", twt48u(("2330", "1150916", "7.000001")))
    fx.commit()
    check = audit_checks.actions_missing(fx.context())
    assert check.result == "fail"
    assert check.examples["event_not_stored"] == [
        ["TWSE", "2330", "2026-09-16", "stock", ["TWT48U_ALL"]]
    ]
    action(fx, stock, date(2026, 9, 16), cash=7.000001)
    fx.commit()
    assert audit_checks.actions_missing(fx.context()).result == "pass"


def test_an_announcement_the_result_table_does_not_have_was_not_executed(fx):
    """2323 2026-10-01: TWT48U announced it, TWT49U covering the date has no row (#386)."""

    stock = fx.instrument("TWSE", "2323")
    for day in (date(2026, 9, 30), date(2026, 10, 1)):
        fx.bar(stock, day, 11)
    fx.raw(TWT48U, "2026-06-08", twt48u(("2323", "1151001", "0.2")))
    fx.raw(
        TWT49U,
        "2026-09-01~2026-12-31",
        {"stat": "OK", "fields": ["資料日期", "股票代號"], "data": []},
    )
    fx.commit()
    check = audit_checks.actions_missing(fx.context())
    assert check.result == "pass"
    assert "TWSE:2323 2026-10-01" in check.notes[0]


def test_provenance(fx):
    stock = fx.instrument("TWSE", "2330")
    raw = fx.raw(
        MI_INDEX,
        T,
        quotes(["2330", "x", "1,000", "1", "10,000", "10", "10", "10", "10"]),
    )
    fx.bar(stock, T, 10, raw=raw)
    fx.commit()
    fx.sql(
        "update market_bars set collected_at = ?",
        (datetime.combine(T, datetime.min.time()) + timedelta(hours=11)).isoformat(" "),
    )
    check = audit_checks.provenance(fx.context())
    assert "market_bars:raw_payload_missing" not in check.failures
    fx.sql("update market_bars set raw_payload_id = null")
    check = audit_checks.provenance(fx.context())
    assert "market_bars:raw_payload_missing" in check.failures


def test_a_multi_date_report_only_has_to_reach_the_row_day(fx):
    # One FRED CSV (Issue #547) holds many days; data_as_of is its last row.
    spx = fx.instrument("US", "SPX", kind="index")
    spx.market = "US"
    csv_raw = fx.raw("https://fred.stlouisfed.org/graph/fredgraph.csv", T, {"csv": ""})
    earlier = T - timedelta(days=1)
    fx.bar(
        spx, earlier, 6400.0, raw=csv_raw, source="fred_close", volume=None, turnover=0
    )
    fx.commit()
    fx.sql(
        "update market_bars set collected_at = ?",
        (datetime.combine(T, datetime.min.time()) + timedelta(hours=11)).isoformat(" "),
    )
    check = audit_checks.provenance(fx.context())
    assert "market_bars:raw_date_not_trading_date" not in check.failures
    assert "market_bars:raw_date_before_trading_date" not in check.failures
    # A row after the report's last day is not in that report.
    fx.sql(
        "update raw_payloads set data_as_of = ?",
        (earlier - timedelta(days=1)).isoformat(),
    )
    check = audit_checks.provenance(fx.context())
    assert "market_bars:raw_date_before_trading_date" in check.failures
    # The audit's date range is the Taiwan bars'; this database has none.
    assert fx.context().first_day is None


# --- 指標、比率、候選、族群：產品寫入的列要通過 -------------------------------------


def price(i: int, base: float = 100.0) -> float:
    """A deterministic zig-zag so every indicator moves."""

    return round(base * (1 + 0.03 * ((i * 7) % 11 - 5) / 5 + 0.002 * i), 2)


def build_market(fx: Fixture, *, with_actions: bool = True) -> dict[str, Instrument]:
    taiex = fx.instrument("TWSE", "TAIEX", kind="index")
    stocks = {
        symbol: fx.instrument(exchange, symbol)
        for exchange, symbol in (
            ("TWSE", "1101"),
            ("TWSE", "1102"),
            ("TPEx", "4549"),
            ("TWSE", "2330"),
        )
    }
    for i, day in enumerate(DAYS):
        fx.bar(taiex, day, price(i, 20000), volume=0, source="twse_index")
        for k, (symbol, stock) in enumerate(stocks.items()):
            close = price(i + 3 * k, 50 + 10 * k)
            suspended = symbol == "1102" and i == 40
            fx.bar(
                stock,
                day,
                close,
                high=round(close * 1.02, 2),
                low=round(close * 0.98, 2),
                open_=round(close * 0.99, 2),
                volume=1000 + 37 * ((i + k) % 9),
                suspended=suspended,
            )
            fx.chip(
                stock,
                day,
                flow=(float(10 * ((i + k) % 5) - 20), 5.0, -3.0),
                margin=1000.0 + 7 * ((i * (k + 1)) % 13),
            )
    if with_actions:
        # TPEx with official prices that the fields reproduce (field factor), a
        # cash capital increase the fields do not (official ratio, #394), and a
        # TWT48U row without official prices (field formula).
        action(
            fx,
            stocks["4549"],
            DAYS[30],
            ratio=0.02,
            cash=0.0,
            reference=price(29 + 6, 70),
            details={
                "ClosePriceBeforeExRightsDiviend": f"{price(29 + 6, 70):.2f}",
                "ExRightsDiviendQuote": f"{price(29 + 6, 70) / 1.02:.2f}",
                "DividendDeductedQuote": f"{price(29 + 6, 70) / 1.02:.2f}",
                "StockDivdendThousandShares": "20.0",
            },
        )
        action(
            fx,
            stocks["4549"],
            DAYS[50],
            cash=0.0,
            details={
                "ClosePriceBeforeExRightsDiviend": "109.00",
                "ExRightsDiviendQuote": "106.15",
                "DividendDeductedQuote": "109.00",
            },
        )
        action(
            fx,
            stocks["2330"],
            DAYS[45],
            cash=1.5,
            details={
                "Code": "2330",
                "Exdividend": "息",
                "CashDividend": "1.5",
                "StockDividendRatio": "",
            },
        )
    fx.commit()
    return {"TAIEX": taiex, **stocks}


def test_indicators_written_by_the_worker_pass_and_a_changed_value_fails(fx):
    build_market(fx)
    result = compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    assert result["rows_written"] == len(DAYS) * 5
    ind = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "indicators")
    assert ind.result == "pass", (dict(ind.failures), ind.examples)
    assert ind.compared == len(DAYS) * 5
    fx.sql(
        "update technical_indicators set ma60 = ma60 * 1.01 where trading_date = ? and instrument_id = (select id from instruments where symbol='4549')",
        DAYS[60].isoformat(),
    )
    ind = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "indicators")
    assert ind.result == "fail" and list(ind.failures) == ["value"]
    fx.sql(
        "update technical_indicators set price_basis = 'as_of_date_raw_basis' where trading_date = ?",
        DAYS[10].isoformat(),
    )
    assert (
        "older_price_basis"
        in by_key(
            audit_checks.derived_checks(fx.context(), lambda: None), "indicators"
        ).failures
    )


def test_indicators_follow_the_official_ratio_of_a_cash_capital_increase(fx):
    """The 4549 rows the A1 bug wrote: a factor the official prices do not support."""

    build_market(fx)
    compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    # The indicators of a database whose factor was the field one (v1 basis).
    fx.sql(
        "update corporate_actions set details_json = '{}' where action_date = ?",
        DAYS[50].isoformat(),
    )
    ind = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "indicators")
    assert ind.result == "fail" and "value" in ind.failures


# --- #557：開高低或量是 null 的日線（#552 指數與台指期、#547 美股）-----------------

NO_OHLC_DAY, INVALID_OHLC_DAY, NO_VOLUME_DAY = 60, 70, 90


def index_with_null_bars(
    fx: Fixture,
    exchange: str,
    symbol: str,
    source: str,
    nulls: dict[int, str],
    *,
    kind: str = "index",
) -> Instrument:
    """A full OHLCV series whose ``nulls`` days are stored the #552 way.

    ``nulls`` maps a day index to ``source_missing_ohlc``/``source_invalid_ohlc``
    (open/high/low NULL with that ``price_reason``) or ``volume`` (volume NULL).
    """

    item = fx.instrument(exchange, symbol, kind=kind)
    for i, day in enumerate(DAYS):
        close = price(i, 300)
        bar = fx.bar(
            item,
            day,
            close,
            high=round(close * 1.01, 2),
            low=round(close * 0.98, 2),
            open_=round(close * 0.995, 2),
            volume=5000 + 113 * (i % 7),
            source=source,
        )
        reason = nulls.get(i)
        if reason == "volume":
            bar.volume = null()  # the column defaults to 0 on insert
        elif reason is not None:
            bar.open = bar.high = bar.low = None
            bar.price_reason = reason
    fx.commit()
    return item


def stored_indicators(fx: Fixture, item: Instrument) -> dict[str, dict]:
    with sqlite3.connect(fx.path) as con:
        con.row_factory = sqlite3.Row
        return {
            row["trading_date"]: dict(row)
            for row in con.execute(
                "select * from technical_indicators where instrument_id = ?",
                (item.id,),
            )
        }


def indicators_check(fx: Fixture):
    return by_key(audit_checks.derived_checks(fx.context(), lambda: None), "indicators")


def test_an_index_day_without_open_high_low_counts_and_nulls_only_kd(fx):
    """AC-1: the bar counts, the close fields go on, KD is null from that day on."""

    tpex = index_with_null_bars(
        fx,
        "TPEx",
        "TPEX",
        "tpex_index_ohlcv",
        {NO_OHLC_DAY: "source_missing_ohlc"},
    )
    compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    stored = stored_indicators(fx, tpex)
    day, before = DAYS[NO_OHLC_DAY].isoformat(), DAYS[NO_OHLC_DAY - 1].isoformat()
    assert stored[day]["bar_count"] == NO_OHLC_DAY + 1
    assert stored[day]["ma20"] is not None and stored[day]["rsi6"] is not None
    assert stored[day]["vol_ma5"] is not None
    assert stored[day]["kd_k"] is None and stored[T.isoformat()]["kd_d"] is None
    assert stored[before]["kd_k"] is not None
    ind = indicators_check(fx)
    assert ind.result == "pass", (dict(ind.failures), ind.examples)
    assert ind.compared == len(DAYS)


def test_invalid_open_high_low_and_a_day_without_volume_null_only_their_fields(fx):
    """AC-2: source_invalid_ohlc nulls KD; a day without volume nulls the volume averages of its windows."""

    tx = index_with_null_bars(
        fx,
        "TAIFEX",
        "TX",
        "taifex_daily_futures",
        {INVALID_OHLC_DAY: "source_invalid_ohlc", NO_VOLUME_DAY: "volume"},
        kind="futures",
    )
    taiex = index_with_null_bars(
        fx, "TWSE", "TAIEX", "twse_index_ohlcv", {NO_VOLUME_DAY: "volume"}
    )
    compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    futures = stored_indicators(fx, tx)
    assert futures[DAYS[INVALID_OHLC_DAY].isoformat()]["kd_k"] is None
    assert futures[DAYS[INVALID_OHLC_DAY].isoformat()]["ma60"] is not None
    assert futures[DAYS[INVALID_OHLC_DAY - 1].isoformat()]["kd_k"] is not None
    index = stored_indicators(fx, taiex)
    for offset in range(5):
        row = index[DAYS[NO_VOLUME_DAY + offset].isoformat()]
        assert row["bar_count"] == NO_VOLUME_DAY + offset + 1
        assert row["vol_ma5"] is None and row["ma5"] is not None
        assert row["kd_k"] is not None
    assert index[DAYS[NO_VOLUME_DAY + 5].isoformat()]["vol_ma5"] is not None
    assert index[DAYS[NO_VOLUME_DAY + 19].isoformat()]["vol_ma20"] is None
    assert index[DAYS[NO_VOLUME_DAY + 20].isoformat()]["vol_ma20"] is not None
    ind = indicators_check(fx)
    assert ind.result == "pass", (dict(ind.failures), ind.examples)
    assert ind.compared == len(DAYS) * 2


def test_a_complete_but_inconsistent_stock_bar_stays_invalid(fx):
    """AC-2: open/high/low all present but inconsistent is still an invalid bar."""

    stock = fx.instrument("TWSE", "1101")
    for i, day in enumerate(DAYS[:40]):
        close = price(i)
        high, low = round(close * 1.02, 2), round(close * 0.98, 2)
        if i == 20:
            high = close - 1  # high below the close
        if i == 30:
            low = close + 0.5  # low above the open and the close
        fx.bar(stock, day, close, high=high, low=low, open_=close)
    fx.commit()
    compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    stored = stored_indicators(fx, stock)
    for i in (20, 30):
        row = stored[DAYS[i].isoformat()]
        assert row["ma5"] is None and json.loads(row["null_reasons"])["ma5"] == (
            "invalid_bar"
        )
    assert stored[DAYS[39].isoformat()]["bar_count"] == 38
    ctx = fx.context()
    bars = audit_series.load_series(ctx.con, ctx.instruments[stock.id][:5], set()).bars
    assert not audit_series.usable(bars[20], 1.0)
    assert not audit_series.usable(bars[30], 1.0)
    assert audit_series.usable(bars[21], 1.0)
    ind = indicators_check(fx)
    assert ind.result == "pass", (dict(ind.failures), ind.examples)
    # Treating such a bar as usable would be found.
    fx.sql(
        "update technical_indicators set bar_count = bar_count + 1 where trading_date = ?",
        DAYS[25].isoformat(),
    )
    assert "bar_count" in indicators_check(fx).failures


def test_a_close_only_us_index_passes_the_whole_audit(fx, tmp_path, monkeypatch):
    """AC-3: the FRED series (#547): open, high, low and volume NULL on every row."""

    spx = fx.instrument("US", "SPX", kind="index")
    spx.market = "US"
    stock = fx.instrument("TWSE", "1101")
    for i, day in enumerate(DAYS):
        fx.bar(stock, day, price(i), volume=1000 + 37 * (i % 9))
        bar = fx.bar(
            spx, day, price(i, 6000), volume=0, turnover=0, source="fred_close"
        )
        bar.open = bar.high = bar.low = None
        bar.volume = null()
        bar.price_reason = "source_missing_ohlc"
        bar.turnover_status, bar.turnover_reason = "unavailable", "not_published"
    fx.commit()
    compute_market_indicators(fx.db, rebuild=True)
    fx.commit()
    stored = stored_indicators(fx, spx)
    assert stored[T.isoformat()]["bar_count"] == len(DAYS)
    assert stored[T.isoformat()]["ma120"] is not None
    assert stored[T.isoformat()]["kd_k"] is None
    assert stored[T.isoformat()]["vol_ma5"] is None
    monkeypatch.setattr(audit, "free_memory_gb", lambda: 20.0)
    monkeypatch.setattr(audit, "refusals", lambda *args: [])
    monkeypatch.setattr(audit, "daily_window_problem", lambda now: None)
    out = tmp_path / "out"
    assert audit.main(["--db", str(fx.path), "--out", str(out)]) in (0, 1)
    checks = {
        check["key"]: check
        for check in json.loads((out / "findings.json").read_text(encoding="utf-8"))[
            "checks"
        ]
    }
    assert checks["indicators"]["result"] == "pass", checks["indicators"]
    assert checks["indicators"]["compared"] == 2 * len(DAYS)
    assert checks["bars_integrity"]["result"] == "pass", checks["bars_integrity"]
    for check in checks.values():
        assert not {"null_mismatch", "bar_count"} & set(check["failures"]), check


def test_the_audit_pins_the_product_versions_it_recomputes():
    assert audit_lib.INDICATOR_VERSION == product_indicators.INDICATOR_VERSION
    assert audit_lib.PRICE_BASIS == product_indicators.PRICE_BASIS
    assert audit_lib.REFERENCE_TOLERANCE == pipeline.ACTION_REFERENCE_TOLERANCE
    assert (
        audit_lib.SESSION_BASIS_START
        == product_coverage.SESSION_BASIS_START.isoformat()
    )


def test_index_history_before_the_stock_history_is_never_a_stock_session(fx):
    """Issue #563: TAIEX rows from 2023-09 on, stocks from 2024-09-30 on."""
    basis = product_coverage.SESSION_BASIS_START
    pre = [basis - timedelta(days=offset) for offset in (3, 4, 5, 6, 7)]
    sessions = [basis + timedelta(days=offset) for offset in (0, 1, 2, 3, 4, 7)]
    taiex = fx.instrument("TWSE", "TAIEX", "index")
    stock = fx.instrument("TWSE", "2330")
    for i, day in enumerate(sorted(pre) + sessions):
        fx.bar(taiex, day, 21000.0 + i, source="twse_index_ohlcv")
    for i, day in enumerate(sessions):
        fx.bar(stock, day, 1000.0 + i, volume=2000 * (i + 1))
    fx.commit()

    ctx = fx.context()

    assert (ctx.first_day, ctx.last_day) == (
        basis.isoformat(),
        sessions[-1].isoformat(),
    )
    assert audit_checks._catalyst_window(ctx, sessions[2].isoformat()) == [
        day.isoformat() for day in sessions[:3]
    ]
    assert (
        audit_checks.liquidity_lots(ctx, stock.id, sessions[2].isoformat(), 3, 1000)
        == (2000 + 4000 + 6000) / 3 / 1000
    )
    assert ctx.taiex_days == [day.isoformat() for day in sessions]


def evidence(
    fx,
    stock: Instrument,
    day: date,
    *,
    flow,
    margin,
    version="institutional-flow/v2-shares-per-share-volume",
    created=None,
) -> Signal:
    row = Signal(
        signal_key=f"analysis-{stock.exchange}-{stock.symbol}-{day}-breakout_v3-3.0.0",
        signal_date=day,
        instrument_id=stock.id,
        status="observation",
        entry_type="breakout",
        rule_evidence_json={
            "inputs": {
                "strategy_institutional_flow_to_average_volume_ratio_5d": flow,
                "margin_balance_change_ratio_5d": margin,
                "institutional_flow_formula_version": version,
            }
        },
        created_at=created
        or datetime.combine(day, datetime.min.time()) + timedelta(hours=12),
    )
    fx.db.add(row)
    return row


def test_chips_ratios_of_the_signals(fx):
    market = build_market(fx, with_actions=False)
    stock = market["1101"]
    dates = DAYS[-20:]
    volumes = [1000 + 37 * ((DAYS.index(d)) % 9) for d in dates]
    flows = sum(10 * (DAYS.index(d) % 5) - 20 + 5.0 - 3.0 for d in dates[-5:])
    flow = flows / (sum(volumes) / 20)
    margins = [1000.0 + 7 * ((DAYS.index(d) * 1) % 13) for d in DAYS[-6:]]
    margin = (margins[-1] - margins[0]) / margins[0]
    row = evidence(fx, stock, T, flow=flow, margin=margin)
    fx.commit()
    ratios = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "chips_ratios"
    )
    assert ratios.result == "pass" and ratios.compared == 2
    row.rule_evidence_json = {
        "inputs": {
            **row.rule_evidence_json["inputs"],
            "strategy_institutional_flow_to_average_volume_ratio_5d": flow * 2,
        }
    }
    fx.commit()
    ratios = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "chips_ratios"
    )
    assert ratios.result == "fail" and list(ratios.failures) == [
        "institutional_flow_5d"
    ]
    # A chip row collected after the signal: the stored value is not judged.
    fx.sql(
        "update chip_snapshots set collected_at = ?, trust_buy = 999 where trading_date = ? and instrument_id = ?",
        "2099-01-01 00:00:00",
        T.isoformat(),
        stock.id,
    )
    ratios = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "chips_ratios"
    )
    assert ratios.result == "undetermined" and set(ratios.unknown) == {
        "inputs_changed_after_write"
    }


def test_a_late_action_outside_what_a_ratio_reads_keeps_a_wrong_ratio_failed(fx):
    """#418 review 1: a dividend collected after the signal does not move its chip ratios."""

    market = build_market(fx, with_actions=False)
    stock = market["1101"]
    dates = DAYS[-20:]
    volumes = [1000 + 37 * ((DAYS.index(d)) % 9) for d in dates]
    flows = sum(10 * (DAYS.index(d) % 5) - 20 + 5.0 - 3.0 for d in dates[-5:])
    flow = flows / (sum(volumes) / 20)
    margins = [1000.0 + 7 * ((DAYS.index(d) * 1) % 13) for d in DAYS[-6:]]
    margin = (margins[-1] - margins[0]) / margins[0]
    evidence(fx, stock, T, flow=flow * 2, margin=margin)
    fx.commit()
    before = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "chips_ratios"
    )
    assert before.result == "fail" and dict(before.failures) == {
        "institutional_flow_5d": 1
    }
    action(fx, stock, DAYS[5], cash=0.5, reference=50.0, collected=datetime(2099, 1, 1))
    action(
        fx, stock, DAYS[-2], cash=0.5, reference=50.0, collected=datetime(2099, 1, 1)
    )
    fx.commit()
    after = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "chips_ratios"
    )
    assert after.result == "fail" and dict(after.failures) == {
        "institutional_flow_5d": 1
    }
    assert not after.unknown


def scored_market(
    fx: Fixture,
    covered: bool = False,
    events: tuple[tuple[str, date], ...] = (("1101", T), ("4549", DAYS[-10])),
) -> dict[str, Instrument]:
    """Groups scored on the last three days; ``covered`` answers their event windows."""

    market = build_market(fx)
    group = ThemeGroup(
        id="official-industry-fixture",
        name="水泥",
        group_type="official_industry",
        active=True,
    )
    fx.db.add(group)
    fx.db.flush()
    for symbol in ("1101", "1102", "2330"):
        fx.db.add(
            GroupMembership(
                group_id=group.id, instrument_id=market[symbol].id, valid_from=DAYS[0]
            )
        )
    other = ThemeGroup(
        id="official-industry-other",
        name="其他",
        group_type="official_industry",
        active=True,
    )
    fx.db.add(other)
    fx.db.flush()
    for symbol in ("4549", "1101", "2330"):
        fx.db.add(
            GroupMembership(
                group_id=other.id, instrument_id=market[symbol].id, valid_from=DAYS[0]
            )
        )
    fx.commit()
    compute_market_indicators(fx.db, rebuild=True)
    for instrument in market.values():
        pipeline._calculate_features(fx.db, instrument)
    fx.commit()
    if covered:
        # hot_group 1.3.0 (#474): dated MOPS answers for every window session,
        # by default one member with an event on T and one 10 sessions before.
        fx.db.add(
            IngestionRun(
                run_type=mops_events.RUN_TYPE,
                source="official",
                run_date=T,
                status="success",
                metadata_json={
                    "coverage_manifest": {
                        day.isoformat(): {
                            "event_coverage": mops_events.date_coverage(day, None)
                        }
                        for day in DAYS[-25:]
                    }
                },
            )
        )
        for symbol, day in events:
            fx.db.add(
                Event(
                    instrument_id=market[symbol].id,
                    event_date=day,
                    event_type="material_information",
                    title=f"fixture {symbol}",
                    source=mops_events.EVENT_SOURCE,
                )
            )
        fx.commit()
    for day in DAYS[-3:]:
        pipeline._calculate_group_scores(fx.db, day)
    fx.commit()
    return market


def test_group_scores_written_by_the_worker_pass_and_a_changed_score_fails(fx):
    scored_market(fx)
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "pass", (
        dict(groups.failures),
        groups.examples,
        dict(groups.unknown),
    )
    assert groups.compared > 50
    fx.sql(
        "update group_daily_scores set score = score + 1 where trading_date = ? and group_id = 'official-industry-fixture'",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "score" in groups.failures


def test_a_catalyst_without_full_coverage_fails(fx):
    # hot_group 1.2.0 (#453): the fixture has no dated MOPS coverage, so every
    # catalyst is null; a value there is not backed by its window.
    scored_market(fx)
    fx.sql(
        "update group_daily_scores set catalyst = 0.5 where trading_date = ? and group_id = 'official-industry-fixture'",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "catalyst_without_coverage" in groups.failures


FIXTURE_GROUP = "trading_date = ? and group_id = 'official-industry-fixture'"


def covered_groups(fx, **kwargs):
    scored_market(fx, covered=True, **kwargs)
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "pass", (
        dict(groups.failures),
        groups.examples,
        dict(groups.unknown),
    )
    return groups


def test_a_covered_catalyst_is_recomputed_from_its_events(fx):
    # #474: 1.3.0 rows on a covered window pass the recount; the fixture group
    # (1101 has an event on T) has a value, and later events do not count.
    covered_groups(fx)
    row = (
        sqlite3.connect(fx.path)
        .execute(
            f"select catalyst, details_json from group_daily_scores where {FIXTURE_GROUP}",
            (T.isoformat(),),
        )
        .fetchone()
    )
    details = json.loads(row[1])
    assert details["hot_group_version"] == "1.3.0"
    assert details["catalyst_coverage"]["complete"] is True
    assert details["raw_values"]["catalyst"] == pytest.approx(1 / 3)
    assert row[0] is not None
    fx.db.add(
        Event(
            instrument_id=details["member_returns"][1]["instrument_id"],
            event_date=T,
            event_type="material_information",
            title="collected after the run",
            source=mops_events.EVENT_SOURCE,
        )
    )
    fx.commit()
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "pass", dict(groups.failures)


def test_a_changed_raw_catalyst_fails(fx):
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json, '$.raw_values.catalyst', 0.9)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "group_raw_catalyst" in groups.failures


def test_a_catalyst_off_its_board_percentile_fails(fx):
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set catalyst = 0.25,"
        " details_json = json_set(details_json, '$.normalized_values.catalyst', 0.25)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "percentile_catalyst" in groups.failures


def test_a_null_catalyst_with_full_coverage_fails(fx):
    # #474 (PR #478 review 2): the reverse of catalyst_without_coverage.
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set catalyst = null,"
        " details_json = json_set(details_json, '$.normalized_values.catalyst', null)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert (
        groups.result == "fail"
        and "catalyst_null_with_full_coverage" in groups.failures
    )


def test_a_complete_window_of_fewer_sessions_fails(fx):
    # #474 (PR #478 review 1): complete needs all 20 sessions.
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json, '$.catalyst_coverage.sessions', 19)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "catalyst_coverage_window" in groups.failures


def test_a_1_2_0_complete_window_of_fewer_sessions_is_undetermined(fx):
    # #501: 1.2.0 called any answered window complete, a TAIEX history under
    # 20 sessions too; the 20-session rule is 1.3.0's (#474), so the audit
    # cannot hold a 1.2.0 row to it.  As a 1.2.0 row the catalyst is the raw
    # value (no board percentile).
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json,"
        " '$.hot_group_version', '1.2.0',"
        " '$.catalyst_coverage.sessions', 19,"
        " '$.catalyst_coverage.window[0]', ?,"
        " '$.raw_values.catalyst', json_extract(details_json, '$.normalized_values.catalyst'))"
        f" where {FIXTURE_GROUP}",
        DAYS[-19].isoformat(),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "undetermined", (dict(groups.failures), groups.examples)
    assert groups.unknown["catalyst_window_short_before_1_3_0"] == 1
    assert groups.unknown_examples["catalyst_window_short_before_1_3_0"] == [
        [
            T.isoformat(),
            "official-industry-fixture",
            "1.2.0",
            19,
            [DAYS[-19].isoformat(), T.isoformat()],
        ]
    ]


def test_a_window_changed_after_the_row_is_undetermined(fx):
    # #501: the row stored the 20 sessions TAIEX had when it was scored; a
    # TAIEX bar backfilled (or is_suspended changed) inside the window later
    # gives another window now.  The audit cannot tell that from a wrong
    # write, so the catalyst is undetermined, not a failure.
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json,"
        " '$.catalyst_coverage.window[0]', ?)"
        f" where {FIXTURE_GROUP}",
        DAYS[-21].isoformat(),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "undetermined", (dict(groups.failures), groups.examples)
    assert groups.unknown["catalyst_window_changed_after_write"] == 1
    assert groups.unknown_examples["catalyst_window_changed_after_write"] == [
        [
            T.isoformat(),
            "official-industry-fixture",
            [DAYS[-21].isoformat(), T.isoformat()],
            [DAYS[-20].isoformat(), T.isoformat()],
        ]
    ]


NULL_CATALYST = (
    "catalyst = null, details_json = json_set(details_json,"
    " '$.normalized_values.catalyst', null, '$.raw_values.catalyst', null"
)


@pytest.mark.parametrize(
    "mutation, category",
    [
        (f"{NULL_CATALYST})", "catalyst_null_with_full_coverage"),
        (
            "details_json = json_remove(details_json,"
            " '$.catalyst_inputs.events_through_id')",
            "catalyst_inputs_missing",
        ),
    ],
    ids=["null_catalyst", "no_events_through_id"],
)
def test_a_changed_window_does_not_hide_a_wrong_row(fx, mutation, category):
    # #501 (PR #507 review 1): what the row says about itself is judged before
    # the window against TAIEX now; an undetermined window must not hide it.
    covered_groups(fx)
    fx.sql(
        f"update group_daily_scores set {mutation} where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json,"
        " '$.catalyst_coverage.window[0]', ?)"
        f" where {FIXTURE_GROUP}",
        DAYS[-21].isoformat(),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and category in groups.failures
    assert "catalyst_window_changed_after_write" not in groups.unknown


def test_a_1_2_0_short_window_does_not_hide_a_null_catalyst(fx):
    # #501 (PR #507 review 1): a complete 1.2.0 window with eligible members
    # has a value whatever its length.
    covered_groups(fx)
    fx.sql(
        f"update group_daily_scores set {NULL_CATALYST},"
        " '$.hot_group_version', '1.2.0',"
        " '$.catalyst_coverage.sessions', 19,"
        " '$.catalyst_coverage.window[0]', ?)"
        f" where {FIXTURE_GROUP}",
        DAYS[-19].isoformat(),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail"
    assert "catalyst_null_with_full_coverage" in groups.failures
    assert "catalyst_window_short_before_1_3_0" not in groups.unknown


def test_a_window_not_ending_on_the_score_date_fails(fx):
    # #501 (PR #507 review 2): a later TAIEX bar or suspension moves only the
    # start of the window; another end is a wrong write.
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set details_json = json_set(details_json,"
        " '$.catalyst_coverage.window[1]', ?)"
        f" where {FIXTURE_GROUP}",
        DAYS[-2].isoformat(),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail", dict(groups.unknown)
    assert groups.examples["catalyst_window_end_not_score_date"] == [
        [
            T.isoformat(),
            "official-industry-fixture",
            [DAYS[-20].isoformat(), DAYS[-2].isoformat()],
        ]
    ]


def test_a_tied_nonzero_catalyst_takes_the_mid_rank(fx):
    # #501 (PR #500 review): two groups with the same non-zero member share
    # both take the mid rank 0.5; 0 is only for no event.
    covered_groups(fx, events=(("1101", T), ("1102", DAYS[-10]), ("4549", DAYS[-10])))
    rows = dict(
        sqlite3.connect(fx.path).execute(
            "select group_id, details_json from group_daily_scores where trading_date = ?",
            (T.isoformat(),),
        )
    )
    values = {gid: json.loads(d) for gid, d in rows.items()}
    raws = {gid: d["raw_values"]["catalyst"] for gid, d in values.items()}
    assert raws["official-industry-fixture"] == pytest.approx(0.4)
    assert raws["official-industry-other"] == pytest.approx(0.4)
    for gid in ("official-industry-fixture", "official-industry-other"):
        assert values[gid]["normalized_values"]["catalyst"] == 0.5
    fx.sql(
        "update group_daily_scores set catalyst = 1.0,"
        " details_json = json_set(details_json, '$.normalized_values.catalyst', 1.0)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "percentile_catalyst" in groups.failures


def test_an_off_percentile_catalyst_on_a_changed_board_is_undetermined(fx, monkeypatch):
    # #501 (PR #500 review 3): like the other percentiles, a board whose
    # member inputs changed after the write is not judged.
    monkeypatch.setattr(audit_lib, "EXAMPLES", 10_000)
    covered_groups(fx)
    fx.sql(
        "update group_daily_scores set"
        " details_json = json_set(details_json, '$.normalized_values.catalyst', 0.25)"
        f" where {FIXTURE_GROUP}",
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert "percentile_catalyst" in groups.failures
    stock = fx.db.query(Instrument).filter_by(symbol="1102").one()
    action(
        fx, stock, DAYS[-5], cash=0.5, reference=40.0, collected=datetime(2099, 1, 1)
    )
    fx.commit()
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert "percentile_catalyst" not in groups.failures
    assert any(
        "percentile_catalyst" in example
        for example in groups.unknown_examples["inputs_changed_after_write"]
    )


def test_a_member_return_of_another_price_basis_fails(fx):
    scored_market(fx)
    details = json.loads(
        sqlite3.connect(fx.path)
        .execute(
            "select details_json from group_daily_scores where trading_date=? and group_id='official-industry-other'",
            (T.isoformat(),),
        )
        .fetchone()[0]
    )
    details["member_returns"][0]["excess_return_20d"] += 0.05
    fx.sql(
        "update group_daily_scores set details_json = ? where trading_date=? and group_id='official-industry-other'",
        json.dumps(details),
        T.isoformat(),
    )
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "member_excess_20d" in groups.failures


def test_candidates_written_by_the_worker_pass_and_a_changed_total_fails(fx):
    market = scored_market(fx)
    versions = pipeline._ensure_strategies(fx.db)
    fx.commit()
    # candidate_score_v6's liquidity floor (#490) walks verified TAIEX
    # sessions (a fixture source counts as one) and needs 1,000 lots: 1101
    # and 2330 trade about a thousand times their fixture volume, 1102 (with
    # one suspended session) stays at about one lot and is left out.
    fx.sql(
        "update market_bars set source = 'twse_index_fixture' where instrument_id = ?",
        market["TAIEX"].id,
    )
    fx.sql(
        "update market_bars set volume = volume * 1000 where instrument_id in (?, ?)",
        market["1101"].id,
        market["2330"].id,
    )
    fx.db.expire_all()
    for name, entry_type in (("breakout_v3", "breakout"), ("pullback_v3", "pullback")):
        for symbol in ("1101", "2330", "1102"):
            instrument = market[symbol]
            bars = (
                fx.db.query(MarketBar)
                .filter(MarketBar.instrument_id == instrument.id)
                .order_by(MarketBar.trading_date)
                .all()
            )
            prior = bars[-21:-1]
            close = bars[-1].close
            ma20 = (
                fx.db.query(TechnicalIndicator)
                .filter_by(instrument_id=instrument.id, trading_date=T)
                .one()
                .ma20
            )
            fx.db.add(
                Signal(
                    signal_key=f"analysis-{instrument.exchange}-{symbol}-{T}-{name}",
                    signal_date=T,
                    instrument_id=instrument.id,
                    strategy_version_id=versions[name].id,
                    status="conditional",
                    entry_type=entry_type,
                    reference_entry=close,
                    breakout_price=close,
                    invalid_price=close * 0.9,
                    target_1=close * 1.2,
                    rule_evidence_json={
                        "actionable": True,
                        "inputs": {
                            "prior_20_volumes": [b.volume for b in prior],
                            "prior_20_highs": [b.high for b in prior],
                            "ma20": ma20,
                        },
                    },
                )
            )
    fx.commit()
    result = compute_daily_candidates(fx.db, T)
    assert result["status"] == "success" and result["candidate_count"] >= 1, result
    assert result["exclusions"]["low_volume"] == 2, result  # 1102's two signals
    checks = audit_checks.derived_checks(fx.context(), lambda: None)
    cands = by_key(checks, "candidates")
    assert cands.result == "pass", (
        dict(cands.failures),
        cands.examples,
        dict(cands.unknown),
        cands.unknown_examples,
    )
    fx.sql(
        "update daily_candidates set total_score = total_score + 0.01 where rank = 1"
    )
    cands = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "candidates"
    )
    assert cands.result == "fail" and "total" in cands.failures
    fx.sql(
        "update daily_candidates set total_score = total_score - 0.01,"
        " components_json = json_set(components_json,"
        " '$.liquidity.average_volume_lots_20d', 999.0) where rank = 1"
    )
    cands = by_key(
        audit_checks.derived_checks(fx.context(), lambda: None), "candidates"
    )
    assert cands.result == "fail"
    assert set(cands.failures) == {"liquidity:average_volume_lots_20d"}


def test_summary_lists_every_item_with_its_result(fx, tmp_path, monkeypatch):
    stock = fx.instrument("TWSE", "1101")
    for day in DAYS[:30]:
        fx.bar(stock, day, 10)
    fx.commit()
    monkeypatch.setattr(audit, "free_memory_gb", lambda: 20.0)
    monkeypatch.setattr(audit, "refusals", lambda *args: [])
    # The run also stops between items inside the 21:30-23:30 daily window;
    # without this the test fails (exit 3) whenever CI runs in that window.
    monkeypatch.setattr(audit, "daily_window_problem", lambda now: None)
    out = tmp_path / "out"
    code = audit.main(["--db", str(fx.path), "--out", str(out)])
    summary = (out / "summary.md").read_text(encoding="utf-8")
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert code in (0, 1)
    assert [check["key"] for check in findings["checks"]] == audit.KEYS
    for key in audit.KEYS:
        assert f"`{key}`" in summary
    assert "通過" in summary and "無法判定" in summary


def test_a_late_action_outside_the_return_window_keeps_a_wrong_member_return_failed(fx):
    """#418 review 1: only an event inside the 21 bars of the returns can explain a difference."""

    scored_market(fx)
    con = sqlite3.connect(fx.path)
    details = json.loads(
        con.execute(
            "select details_json from group_daily_scores where trading_date=? and group_id='official-industry-other'",
            (T.isoformat(),),
        ).fetchone()[0]
    )
    con.close()
    member = details["member_returns"][0]
    member["excess_return_20d"] += 0.05
    fx.sql(
        "update group_daily_scores set details_json = ? where trading_date=? and group_id='official-industry-other'",
        json.dumps(details),
        T.isoformat(),
    )
    stock = fx.db.get(Instrument, member["instrument_id"])
    action(fx, stock, DAYS[5], cash=0.5, reference=40.0, collected=datetime(2099, 1, 1))
    fx.commit()
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert groups.result == "fail" and "member_excess_20d" in groups.failures
    # An event inside the window, collected after the score date: not judged.
    action(
        fx, stock, DAYS[-5], cash=0.5, reference=40.0, collected=datetime(2099, 1, 1)
    )
    fx.commit()
    groups = by_key(audit_checks.derived_checks(fx.context(), lambda: None), "groups")
    assert "member_excess_20d" not in groups.failures
    assert groups.unknown["inputs_changed_after_write"] > 0


def link_directory(link: Path, target: Path) -> None:
    """A junction on Windows (no privilege needed), a symlink elsewhere."""

    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_an_out_directory_in_the_production_data_is_refused(tmp_path):
    """#418 review 2: --out inside stock-lab-data or STOCK_DATA_DIR, as written or through a link."""

    data = tmp_path / "prod-data"
    data.mkdir()
    environ = {"STOCK_DATA_DIR": str(data)}
    named = tmp_path / "stock-lab-data"
    named.mkdir()
    assert "stock-lab-data" in audit.out_problem(named / "audit", {})
    assert "STOCK_DATA_DIR" in audit.out_problem(data / "audit", environ)
    linked = tmp_path / "looks-safe"
    link_directory(linked, data)
    named_link = tmp_path / "also-safe"
    link_directory(named_link, named)
    try:
        assert "STOCK_DATA_DIR" in audit.out_problem(linked / "audit", environ)
        assert "stock-lab-data" in audit.out_problem(named_link / "audit", {})
        assert audit.out_problem(tmp_path / "out", environ) is None
    finally:
        os.rmdir(linked) if os.name == "nt" else linked.unlink()
        os.rmdir(named_link) if os.name == "nt" else named_link.unlink()
    assert list(data.iterdir()) == [] and list(named.iterdir()) == []


def test_main_refuses_an_out_directory_in_stock_lab_data(
    fx, tmp_path, monkeypatch, capsys
):
    stock = fx.instrument("TWSE", "1101")
    fx.bar(stock, DAYS[0], 10)
    fx.commit()
    monkeypatch.setattr(audit, "free_memory_gb", lambda: 20.0)
    monkeypatch.setattr(audit, "daily_window_problem", lambda now: None)
    out = tmp_path / "stock-lab-data" / "audit"
    assert audit.main(["--db", str(fx.path), "--out", str(out)]) == 2
    assert "--out" in capsys.readouterr().out
    assert not out.parent.exists()
