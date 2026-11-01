"""Official ex-right history backfill and the factor check on write (#386)."""

import socket
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.corporate_action_sync as sync
import worker.pipeline as pipeline
import worker.sources as sources
from worker.indicator_batch import compute_market_indicators, load_indicator_bars
from app.db import enable_sqlite_foreign_keys
from app.indicators import compute_indicators
from app.migrations import upgrade_database
from app.models import (
    CorporateAction,
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TechnicalFeature,
    TechnicalIndicator,
)

# 4549 2026-09-08 as published by tpex_exright_daily (raw payload of the
# production row that #386 found with stock_dividend_ratio 2.02941).
TPEX_4549 = {
    "Date": "1150908",
    "SecuritiesCompanyCode": "4549",
    "CompanyName": "桓達",
    "ClosePriceBeforeExRightsDiviend": "103.50",
    "ExRightsDiviendQuote": "101.47",
    "StockDividend": "2.029410",
    "CashDividend": "0.000000",
    "StockDividendPlusCashDividend": "2.029410",
    "ExRightsDiviend": "除權",
    "LimitUp": "111.50",
    "LimitDown": "91.40",
    "OpeningReferencePrice": "101.50",
    "DividendDeductedQuote": "101.47",
    "CashDivdend": "0.00000000",
    "StockDivdendThousandShares": "19.99998421",
    "CashCapitalIncreaseShares": "0",
    "SubscriptionPricePerShare": "0.00",
    "AllocatedForPublicUnderwriting": "0",
    "SubscribedByEmployees": "0",
    "SubscribedByExistingShareholders": "0",
    "SubscribedProRataThousandShares": "0.00000000",
}
# 3691 2026-10-27: a cash capital increase (現增認股).  Its 除權息參考價
# 106.15 includes the subscription, its 減除股利參考價 109.00 does not.
TPEX_3691 = {
    **TPEX_4549,
    "Date": "1151027",
    "SecuritiesCompanyCode": "3691",
    "CompanyName": "碩禾",
    "ClosePriceBeforeExRightsDiviend": "109.00",
    "ExRightsDiviendQuote": "106.15",
    "StockDividend": "2.846391",
    "StockDividendPlusCashDividend": "2.846391",
    "LimitUp": "119.50",
    "LimitDown": "95.60",
    "OpeningReferencePrice": "109.00",
    "DividendDeductedQuote": "109.00",
    "StockDivdendThousandShares": "0.00000000",
    "CashCapitalIncreaseShares": "10000000",
    "SubscriptionPricePerShare": "80.00",
    "AllocatedForPublicUnderwriting": "1000000",
    "SubscribedByEmployees": "1500000",
    "SubscribedByExistingShareholders": "7500000",
    "SubscribedProRataThousandShares": "81.62517242",
}
EXDAILYQ_FIELDS = list(sources.TPEX_ACTION_HISTORY_FIELDS)
TWT49U_FIELDS = [
    "資料日期",
    "股票代號",
    "股票名稱",
    "除權息前收盤價",
    "除權息參考價",
    "權值+息值",
    "權/息",
    "漲停價格",
    "跌停價格",
    "開盤競價基準",
    "減除股利參考價",
    "詳細資料",
    "最近一次申報資料 季別/日期",
    "最近一次申報每股 (單位)淨值",
    "最近一次申報每股 (單位)盈餘",
]
# Rows of TWT49U 2026-09-09..2026-09-16 as published.
TWT49U_3706 = ["115年09月09日", "3706", "神達", "91.30", "80.27", "11.027273", "權息", "88.20", "72.30", "80.30", "80.27", "3706,20260909", "115年第2季", "57.46", "2.58"]  # fmt: skip
TWT49U_3059 = ["115年09月09日", "3059", "華晶科", "38.50", "37.50", "0.998614", "息", "41.25", "33.75", "37.50", "37.50", "3059,20260909", "115年第2季", "33.10", "0.64"]  # fmt: skip
TWT49U_4912 = ["115年09月10日", "4912", "聯德控股-KY", "97.50", "96.69", "0.800477", "息", "106.00", "87.10", "96.70", "96.69", "4912,20260910", "115年第2季", "62.51", "2.85"]  # fmt: skip
DETAIL_FIELDS = [
    "股票代號",
    "股票名稱",
    "(每股配發現金股利)除息",
    "(增資配股) 除權",
    "A. 按普通股股東持股比例每千股無償配股",
    "B. 員工紅利轉增資",
    "C. (有償) 現金增資",
    "每股認購金額",
    "a. 公開承銷",
    "b. 員工認購",
    " c. 原股東認購",
    "按股東持股比例每千股認購",
]
DETAIL_3706 = ["3706  ", "神達            ", "3 元／股", "", "100 股", "0 股", "0 股", "0 元／股", "0 股", "0 股", "0 股", "0.00000000 股"]  # fmt: skip
NO_DATA = {"stat": "很抱歉，沒有符合條件的資料!"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in corporate-action sync tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def exdailyq_row(openapi_row):
    inverse = {value: key for key, value in sources.TPEX_ACTION_HISTORY_FIELDS.items()}
    row = {inverse[key]: value for key, value in openapi_row.items()}
    day = row["除權息日期"]
    row["除權息日期"] = f"{day[:3]}/{day[3:5]}/{day[5:]}"
    row["名稱"] = f"{row['名稱']}        "
    return [row[name] for name in EXDAILYQ_FIELDS]


def exdailyq(start, end, *rows):
    return {
        "date": f"{start:%Y%m%d}~{end:%Y%m%d}",
        "stat": "ok",
        "tables": [
            {
                "title": "",
                "totalCount": len(rows),
                "fields": EXDAILYQ_FIELDS,
                "data": list(rows),
            }  # fmt: skip
        ],
    }


def twt49u(*rows):
    return {"stat": "OK", "fields": TWT49U_FIELDS, "data": list(rows)}


class Fetcher:
    """Answers by URL prefix; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        for prefix, answer in self.routes:
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer(url) if callable(answer) else answer
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with maker() as db:
        for exchange, symbol in [
            ("TPEx", "4549"),
            ("TPEx", "3691"),
            ("TWSE", "3706"),
            ("TWSE", "3059"),
            ("TWSE", "4912"),
        ]:
            db.add(
                Instrument(
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type="stock",
                    status="active",
                )
            )
        db.commit()
    yield maker
    engine.dispose()


def instruments(db):
    return {
        (item.exchange, item.symbol): item for item in db.scalars(select(Instrument))
    }


def stored(db, symbol):
    return db.scalar(
        select(CorporateAction)
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(Instrument.symbol == symbol)
    )


def test_the_4549_raw_row_parses_to_its_official_share_ratio():
    record = sources.tpex_action_record(TPEX_4549, payload_sha256="a")
    assert record.stock_dividend_ratio == pytest.approx(0.01999998421)
    check = pipeline.action_factor_check(record)
    assert check["passed"] and check["difference"] < 0.005


def test_the_4549_ratio_stored_as_a_rights_value_is_not_written(factory):
    # The parser before StockDivdendThousandShares read StockDividend (元).
    wrong = replace(
        sources.tpex_action_record(TPEX_4549, payload_sha256=None),
        stock_dividend_ratio=2.02941,
    )
    with factory() as db:
        pipeline._upsert_action(db, wrong, instruments(db), None)
        db.flush()
        row = stored(db, "4549")
        assert (row.stock_dividend_ratio, row.cash_dividend, row.split_ratio) == (
            None,
            None,
            None,
        )
        assert row.details_json["factor_check"]["passed"] is False
        assert pipeline._corporate_action_factor([row])[0] == 1.0
        quality = db.scalar(select(DataQuality))
        assert (quality.entity_type, quality.entity_key, quality.status) == (
            "corporate_action",
            "TPEx:4549:corporate_action",
            "factor_mismatch",
        )
        assert quality.as_of_date == date(2026, 9, 8)
        assert quality.checks_json["stock_dividend_ratio"] == 2.02941
        assert quality.checks_json["implied_reference"] == pytest.approx(34.165068)
        assert quality.checks_json["official_reference"] == 101.47

        # The official ratio replaces the row and closes the quality record.
        right = sources.tpex_action_record(TPEX_4549, payload_sha256=None)
        pipeline._upsert_action(db, right, instruments(db), None)
        db.flush()
        assert stored(db, "4549").stock_dividend_ratio == pytest.approx(0.02, abs=1e-7)
        assert db.scalar(select(DataQuality.status)) == "complete"


def test_a_cash_capital_increase_is_not_mistaken_for_a_mismatch(factory):
    record = sources.tpex_action_record(TPEX_3691, payload_sha256=None)
    check = pipeline.action_factor_check(record)
    assert check["field_factor"] == 1.0 and check["official_factor"] == 1.0
    # The subscription-inclusive 除權息參考價 would have been 0.026 off.
    assert 106.15 / 109.00 == pytest.approx(0.9739, abs=1e-4)
    with factory() as db:
        pipeline._upsert_action(db, record, instruments(db), None)
        db.flush()
        assert stored(db, "3691").stock_dividend_ratio == 0.0
        assert db.scalar(select(func.count(DataQuality.id))) == 0


def test_a_published_reference_cut_to_the_cent_passes():
    # 97.50 - 0.800477 = 96.6995; TWT49U publishes 96.69.
    [row] = sources.parse_twse_action_history(
        twt49u(TWT49U_4912), start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    record = sources.twse_action_history_record(
        row, None, payload_sha256=None, detail_sha256=None
    )
    check = pipeline.action_factor_check(record)
    assert check["passed"] and 0.009 < check["difference"] < 0.01


def test_a_row_without_official_prices_is_written_unchecked(factory):
    record = sources.ActionRecord(
        symbol="3059",
        action_date=date(2026, 9, 9),
        action_type="corporate_action",
        cash_dividend=0.998614,
        details={"Code": "3059", "Date": "1150909", "Exdividend": "息"},
    )
    assert pipeline.action_factor_check(record) is None
    with factory() as db:
        pipeline._upsert_action(db, record, instruments(db), None)
        db.flush()
        assert stored(db, "3059").cash_dividend == 0.998614


def test_twt49u_rows_take_the_breakdown_of_their_detail():
    rows = sources.parse_twse_action_history(
        twt49u(TWT49U_3706, TWT49U_3059), start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    detail = sources.parse_twse_action_detail(
        {"stat": "ok", "fields": DETAIL_FIELDS, "data": [DETAIL_3706]}, "3706"
    )
    right = sources.twse_action_history_record(
        rows[0], detail, payload_sha256="p", detail_sha256="d"
    )
    dividend = sources.twse_action_history_record(
        rows[1], None, payload_sha256="p", detail_sha256=None
    )
    assert (right.cash_dividend, right.stock_dividend_ratio, right.reference_price) == (
        3.0,
        0.1,
        91.3,
    )
    assert (dividend.cash_dividend, dividend.stock_dividend_ratio) == (0.998614, None)
    assert right.details["detail"]["c. 原股東認購"] == "0 股"
    assert right.details["detail_sha256"] == "d"
    assert pipeline.action_factor_check(right)["passed"]
    # The TWT48U keys the stock page classifies a TWSE row by.
    assert {key: right.details[key] for key in ("Code", "Date", "Exdividend")} == {
        "Code": "3706",
        "Date": "1150909",
        "Exdividend": "權息",
    }
    with pytest.raises(ValueError):
        sources.twse_action_history_record(
            rows[0], None, payload_sha256=None, detail_sha256=None
        )


# TWT49U and TWT49UDetail as published: the detail prints free shares per
# thousand to one decimal.
TWT49U_2442 = ["115年09月08日", "2442", "新美齊", "19.45", "16.26", "3.188314", "權息", "17.85", "14.65", "16.25", "16.26", "2442,20260908", "115年第2季", "21.30", "1.16"]  # fmt: skip
DETAIL_2442 = ["2442  ", "新美齊          ", "2.031861 元／股", "", "71.1 股", "0 股", "0 股", "0 元／股", "0 股", "0 股", "0 股", "0.00000000 股"]  # fmt: skip
TWT49U_6446 = ["115年07月09日", "6446", "藥華藥", "1,530.00", "1,377.93", "152.067614", "權息", "1,515.00", "1,245.00", "1,380.00", "1,377.93", "6446,20260709", "115年第2季", "98.54", "11.35"]  # fmt: skip
DETAIL_6446 = ["6446  ", "藥華藥          ", "1.490152 元／股", "", "109.3 股", "0 股", "0 股", "0 元／股", "0 股", "0 股", "0 股", "0.00000000 股"]  # fmt: skip
TWT49U_7610 = ["115年07月13日", "7610", "聯友金屬-創", "2,650.00", "2,181.01", "468.983979", "權息", "2,425.00", "1,965.00", "2,210.00", "2,207.80", "7610,20260713", "115年第2季", "64.14", "25.37"]  # fmt: skip
DETAIL_7610 = ["7610  ", "聯友金屬-創     ", "0.5 元／股", "", "200.1 股", "0 股", "2,000,000 股", "1,400 元／股", "200,000 股", "300,000 股", "1,500,000 股", "30.87343732 股"]  # fmt: skip


def history_record(row, detail):
    [parsed] = sources.parse_twse_action_history(
        twt49u(row), start=date(2026, 7, 1), end=date(2026, 9, 30)
    )
    return sources.twse_action_history_record(
        parsed,
        sources.parse_twse_action_detail(
            {"stat": "ok", "fields": DETAIL_FIELDS, "data": [detail]}, row[1]
        ),
        payload_sha256=None,
        detail_sha256=None,
    )


@pytest.mark.parametrize(
    "row,detail,ratio,source",
    [
        # TWT48U published 0.07111516 for the same event.
        (TWT49U_2442, DETAIL_2442, 0.07111516, "權值+息值"),
        # A price of 1,530: the printed 0.1093 would be 0.03 yuan off.
        (TWT49U_6446, DETAIL_6446, 0.10927783, "權值+息值"),
        # A cash capital increase: 權值+息值 includes the subscription.
        (TWT49U_7610, DETAIL_7610, 0.20006341, "減除股利參考價"),
        # The printed ratio is exact: kept as printed.
        (TWT49U_3706, DETAIL_3706, 0.1, "權值+息值"),
    ],
    ids=["2442", "6446", "7610", "3706"],
)
def test_the_ex_right_ratio_is_recovered_to_the_precision_twse_used(
    row, detail, ratio, source
):
    record = history_record(row, detail)
    assert record.stock_dividend_ratio == pytest.approx(ratio, abs=2e-7)
    assert record.details["stock_ratio_source"]["from"] == source
    assert pipeline.action_factor_check(record)["passed"]


def test_a_printed_ratio_the_reference_does_not_support_is_kept_and_rejected():
    # The same 6446 event if the detail printed another ratio.
    wrong = [*DETAIL_6446[:4], "100.0 股", *DETAIL_6446[5:]]
    record = history_record(TWT49U_6446, wrong)
    assert record.stock_dividend_ratio == 0.1
    assert record.details["stock_ratio_source"]["disagrees"] is True
    assert not pipeline.action_factor_check(record)["passed"]


def test_a_backfilled_twse_row_keeps_the_identity_of_the_daily_row():
    daily = sources.TwseAdapter(
        lambda *args, **kwargs: [
            {
                "Date": "1150909",
                "Code": "3706",
                "Exdividend": "權息",
                "CashDividend": "3.0",
                "StockDividendRatio": "0.1",
            }  # fmt: skip
        ]
    ).fetch_actions(date(2026, 9, 9))[0][0]
    [row] = sources.parse_twse_action_history(
        twt49u(TWT49U_3706), start=date(2026, 9, 9), end=date(2026, 9, 9)
    )
    detail = sources.parse_twse_action_detail(
        {"stat": "ok", "fields": DETAIL_FIELDS, "data": [DETAIL_3706]}, "3706"
    )
    backfilled = sources.twse_action_history_record(
        row, detail, payload_sha256=None, detail_sha256=None
    )
    assert (backfilled.symbol, backfilled.action_date, backfilled.action_type) == (
        daily.symbol,
        daily.action_date,
        daily.action_type,
    )
    assert (backfilled.cash_dividend, backfilled.stock_dividend_ratio) == (
        daily.cash_dividend,
        daily.stock_dividend_ratio,
    )


def test_the_exdailyq_row_is_stored_like_the_daily_row():
    [record] = sources.parse_tpex_action_history(
        exdailyq(date(2026, 9, 1), date(2026, 9, 30), exdailyq_row(TPEX_4549)),
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        payload_sha256="h",
    )
    assert record == sources.tpex_action_record(TPEX_4549, payload_sha256="h")


@pytest.mark.parametrize(
    "payload",
    [
        exdailyq(date(2026, 9, 1), date(2026, 9, 29)),
        {"stat": "fail", "date": "20260901~20260930", "tables": []},
        exdailyq(
            date(2026, 9, 1),
            date(2026, 9, 30),
            exdailyq_row({**TPEX_4549, "Date": "1151001"}),
        ),
        exdailyq(date(2026, 9, 1), date(2026, 9, 30), exdailyq_row(TPEX_4549)[:-1]),
    ],
    ids=["other_range", "not_ok", "row_outside_range", "missing_column"],
)
def test_an_exdailyq_answer_for_anything_else_fails(payload):
    with pytest.raises(sources.OfficialDataError):
        sources.parse_tpex_action_history(
            payload, start=date(2026, 9, 1), end=date(2026, 9, 30), payload_sha256=None
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"stat": "查詢日期大於今日"},
        {"stat": "OK"},
        twt49u(TWT49U_4912),
    ],
    ids=["error_stat", "no_table", "row_outside_range"],
)
def test_a_twt49u_answer_for_anything_else_fails(payload):
    with pytest.raises(sources.OfficialDataError):
        sources.parse_twse_action_history(
            payload, start=date(2026, 9, 1), end=date(2026, 9, 9)
        )


def test_a_twt49u_range_without_events_is_empty():
    assert (
        sources.parse_twse_action_history(
            NO_DATA, start=date(2024, 9, 30), end=date(2024, 9, 30)
        )
        == []
    )


def test_month_windows_cover_the_range_once():
    assert sources._month_windows(date(2024, 9, 30), date(2024, 11, 2)) == [
        (date(2024, 9, 30), date(2024, 9, 30)),
        (date(2024, 10, 1), date(2024, 10, 31)),
        (date(2024, 11, 1), date(2024, 11, 2)),
    ]


def routes(detail):
    return [
        (sources.TWSE_ACTION_DETAIL_ENDPOINT, detail),
        (
            sources.TWSE_ACTION_HISTORY_ENDPOINT,
            lambda url: twt49u(TWT49U_3706, TWT49U_3059, TWT49U_4912)
            if "startDate=20260901" in url
            else NO_DATA,
        ),
        (
            sources.TPEX_ACTION_HISTORY_ENDPOINT,
            lambda url: exdailyq(
                date(2026, 9, 1),
                date(2026, 9, 30),
                exdailyq_row(TPEX_4549),
                exdailyq_row({**TPEX_3691, "Date": "1150915"}),
            )
            if "startDate=2026%2F09%2F01" in url
            else exdailyq(date(2026, 10, 1), date(2026, 10, 5)),
        ),
    ]


def test_sync_backfills_fixes_and_reruns_to_the_same_rows(factory):
    fetcher = Fetcher(
        routes({"stat": "ok", "fields": DETAIL_FIELDS, "data": [DETAIL_3706]})
    )
    with factory() as db:
        # The production 4549 row written before the parser fix.
        db.add(
            CorporateAction(
                instrument_id=instruments(db)[("TPEx", "4549")].id,
                action_date=date(2026, 9, 8),
                action_type="corporate_action",
                cash_dividend=0.0,
                stock_dividend_ratio=2.02941,
                reference_price=101.5,
                details_json=TPEX_4549,
                source="tpex",
            )
        )
        db.commit()
        checked = sync.check_corporate_actions(db)
        assert [item["symbol"] for item in checked["mismatches"]] == ["4549"]

        dry = sync.sync_corporate_actions(
            db, start=date(2026, 9, 1), end=date(2026, 10, 5), fetcher=fetcher
        )
        assert dry["status"] == "dry_run"
        assert db.scalar(select(func.count(CorporateAction.id))) == 1
        assert (dry["new_rows"], dry["changed_rows"], dry["factor_mismatches"]) == (
            4,
            1,
            [],
        )
        assert dry["changes"][0]["after"]["stock_dividend_ratio"] == pytest.approx(
            0.02, abs=1e-7
        )

        applied = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        assert applied["status"] == "success"
        assert applied["before"]["rows"] == 1 and applied["after"]["rows"] == 5
        assert applied["after"]["earliest"] == "2026-09-08"
        assert stored(db, "4549").stock_dividend_ratio == pytest.approx(0.02, abs=1e-7)
        assert stored(db, "3706").cash_dividend == 3.0
        run = db.get(IngestionRun, applied["run_id"])
        assert run.run_type == "corporate_action_sync"
        # Every row points at the raw payload it was parsed from.
        rows = db.scalars(select(CorporateAction)).all()
        assert all(row.raw_payload_id for row in rows)
        assert {
            db.get(RawPayload, row.raw_payload_id).endpoint.split("?")[0]
            for row in rows
        } == {  # fmt: skip
            sources.TWSE_ACTION_HISTORY_ENDPOINT,
            sources.TPEX_ACTION_HISTORY_ENDPOINT,
        }
        assert sync.check_corporate_actions(db)["mismatches"] == []

        again = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        assert (again["new_rows"], again["changed_rows"]) == (0, 0)
        assert db.scalar(select(func.count(CorporateAction.id))) == 5
    # One TWT49UDetail request: only 3706 is an ex-right.
    details = [url for url in fetcher.calls if url.startswith(sources.TWSE_ACTION_DETAIL_ENDPOINT)]  # fmt: skip
    assert len(details) == 3 and all("STK_NO=3706" in url for url in details)


def test_each_capture_is_registered_once_with_the_dates_it_covers(factory):
    # DB review C3 (#386): one snapshot was registered as raw_payloads of
    # every day it was used for.  A sync registers each response once.
    fetcher = Fetcher(
        routes({"stat": "ok", "fields": DETAIL_FIELDS, "data": [DETAIL_3706]})
    )
    with factory() as db:
        result = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        raws = db.scalars(
            select(RawPayload).where(RawPayload.ingestion_run_id == result["run_id"])
        ).all()
    assert sorted(raw.endpoint for raw in raws) == sorted(fetcher.calls)
    assert len(raws) == result["payloads"] == 5
    covered = {raw.endpoint.split("?")[0] + " " + raw.data_as_of for raw in raws}
    assert covered == {
        f"{sources.TWSE_ACTION_HISTORY_ENDPOINT} 2026-09-01~2026-09-30",
        f"{sources.TWSE_ACTION_HISTORY_ENDPOINT} 2026-10-01~2026-10-05",
        f"{sources.TWSE_ACTION_DETAIL_ENDPOINT} 2026-09-09",
        f"{sources.TPEX_ACTION_HISTORY_ENDPOINT} 2026-09-01~2026-09-30",
        f"{sources.TPEX_ACTION_HISTORY_ENDPOINT} 2026-10-01~2026-10-05",
    }


def test_a_one_day_range_is_registered_as_that_day():
    assert sources._covered_dates(date(2026, 9, 9), date(2026, 9, 9)) == "2026-09-09"


def test_an_unreadable_detail_leaves_the_event_out_with_a_warning(factory):
    fetcher = Fetcher(routes(sources.OfficialDataError("timeout")))
    with factory() as db:
        result = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        assert result["status"] == "partial"
        assert any("3706" in item for item in result["warnings"])
        assert stored(db, "3706") is None
        assert stored(db, "3059").cash_dividend == 0.998614


def test_a_failed_window_writes_nothing(factory):
    fetcher = Fetcher(
        [
            (sources.TWSE_ACTION_HISTORY_ENDPOINT, NO_DATA),
            (sources.TPEX_ACTION_HISTORY_ENDPOINT, {"stat": "fail"}),
        ]
    )
    with factory() as db:
        with pytest.raises(sources.OfficialDataError):
            sync.sync_corporate_actions(
                db,
                start=date(2026, 9, 1),
                end=date(2026, 9, 30),
                apply=True,
                fetcher=fetcher,
            )
        db.rollback()
        assert db.scalar(select(func.count(CorporateAction.id))) == 0
        assert db.scalar(select(func.count(IngestionRun.id))) == 0


def _weekdays(start, end):
    days, cursor = [], start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(db, instrument, days, base):
    for index, day in enumerate(days):
        close = round(base + (index % 5) * 0.7 - (index % 3) * 0.4, 2)
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                adj_close=close,
                volume=1000 + index,
                turnover=close * 1000,
                source="fixture",
            )
        )


def test_rebuild_recomputes_only_what_the_sync_changed(factory):
    days = _weekdays(date(2026, 6, 1), date(2026, 10, 5))
    with factory() as db:
        index = Instrument(
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        db.add(index)
        db.flush()
        known = instruments(db)
        _bars(db, index, days, 20000)
        _bars(db, known[("TPEx", "4549")], days, 100)
        _bars(db, known[("TWSE", "3706")], days, 90)
        db.add(
            CorporateAction(
                instrument_id=known[("TPEx", "4549")].id,
                action_date=date(2026, 9, 8),
                action_type="corporate_action",
                cash_dividend=0.0,
                stock_dividend_ratio=2.02941,
                reference_price=101.5,
                details_json=TPEX_4549,
                source="tpex",
            )
        )
        db.flush()
        compute_market_indicators(db)
        db.commit()
        untouched = {
            row.trading_date: row.computed_at
            for row in db.scalars(
                select(TechnicalIndicator).where(
                    TechnicalIndicator.instrument_id == known[("TWSE", "3706")].id
                )
            )
        }
        wrong_ma60 = db.scalar(
            select(TechnicalIndicator.ma60).where(
                TechnicalIndicator.instrument_id == known[("TPEx", "4549")].id,
                TechnicalIndicator.trading_date == days[-1],
            )
        )

        fetcher = Fetcher(
            [
                (sources.TWSE_ACTION_HISTORY_ENDPOINT, NO_DATA),
                (
                    sources.TPEX_ACTION_HISTORY_ENDPOINT,
                    lambda url: exdailyq(
                        date(2026, 9, 1), date(2026, 9, 30), exdailyq_row(TPEX_4549)
                    )
                    if "startDate=2026%2F09%2F01" in url
                    else exdailyq(date(2026, 10, 1), date(2026, 10, 5)),
                ),
            ]
        )
        applied = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        assert applied["affected"] == {str(known[("TPEx", "4549")].id): "2026-09-08"}
        result = sync.rebuild_after_sync(db, applied["run_id"], checkpoint=db.commit)
        db.commit()

        assert result["indicators"]["instruments"] == 1
        assert result["feature_instruments"] == 1
        sessions = [day for day in days if day >= date(2026, 9, 8)]
        assert result["group_score_dates"] == {
            "since": "2026-09-08",
            "count": len(sessions),
            "first": sessions[0].isoformat(),
            "last": sessions[-1].isoformat(),
        }
        assert result["signals_upserted"] == {}
        expected = compute_indicators(
            load_indicator_bars(db, known[("TPEx", "4549")].id, days[-1])
        )[-1]
        rebuilt = db.scalar(
            select(TechnicalIndicator).where(
                TechnicalIndicator.instrument_id == known[("TPEx", "4549")].id,
                TechnicalIndicator.trading_date == days[-1],
            )
        )
        assert rebuilt.ma60 == pytest.approx(expected.values["ma60"], abs=1e-9)
        assert rebuilt.ma60 > wrong_ma60 * 1.5
        feature = db.scalar(
            select(TechnicalFeature).where(
                TechnicalFeature.instrument_id == known[("TPEx", "4549")].id,
                TechnicalFeature.trading_date == days[-1],
            )
        )
        assert feature.features_json[
            "corporate_action_factor_signal_to_score_raw"
        ] == pytest.approx(1 / 1.01999998421)
        assert {
            row.trading_date: row.computed_at
            for row in db.scalars(
                select(TechnicalIndicator).where(
                    TechnicalIndicator.instrument_id == known[("TWSE", "3706")].id
                )
            )
        } == untouched

        # A rerun of a run that changed nothing has nothing to rebuild.
        again = sync.sync_corporate_actions(
            db,
            start=date(2026, 9, 1),
            end=date(2026, 10, 5),
            apply=True,
            fetcher=fetcher,
        )
        db.commit()
        assert sync.rebuild_after_sync(db, again["run_id"])["status"] == "no_change"


def test_rebuild_refuses_a_run_that_is_not_a_finished_sync(factory):
    with factory() as db:
        run = IngestionRun(
            run_type="collect", source="official", run_date=date(2026, 10, 5)
        )
        db.add(run)
        db.flush()
        with pytest.raises(sync.RebuildError):
            sync.rebuild_after_sync(db, run.id)
        with pytest.raises(sync.RebuildError):
            sync.rebuild_after_sync(db, run.id + 1)
