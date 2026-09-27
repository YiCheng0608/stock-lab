from datetime import date

import httpx
import pytest

import worker.sources as sources


@pytest.mark.parametrize("amount", [0, 1])
def test_direct_bar_record_without_turnover_evidence_defaults_unknown(amount):
    bar = sources.BarRecord(
        symbol="1101", trading_date=date(2026, 9, 4),
        open=100, high=101, low=99, close=100,
        volume=1000, turnover=amount,
    )
    assert (bar.turnover, bar.turnover_status, bar.turnover_reason) == (amount, "unknown", None)


class FixtureFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, **_kwargs):
        self.calls.append(url)
        if url == sources.TWSE_LISTED_ENDPOINT:
            return [
                {"Code": "1101", "Name": "TWSE Cement", "DateOfListing": "2020/01/02", "Industry": "Cement"},
                {"Code": "9999", "Name": "TWSE New", "DateOfListing": "2026/08/01", "Industry": "Technology"},
            ]
        if url == sources.TWSE_ETF_ENDPOINT:
            return [{"FundCode": "0050", "Name": "Taiwan 50 ETF", "FundType": "broad market", "DateOfListing": "2003/06/30"}]
        if url == sources.TWSE_NEW_LISTING_ENDPOINT:
            return [{"Code": "9999", "ApprovedListingDate": "2026/08/01"}]
        if url == sources.TWSE_DAILY_ENDPOINT:
            return [
                {"Code": code, "Date": "2026-09-04", "OpeningPrice": "100", "HighestPrice": "105", "LowestPrice": "98", "ClosingPrice": "103", "TradeVolume": "1000", "TradeValue": "103000"}
                for code in ("1101", "0050", "9999")
            ]
        if url == sources.TWSE_INDEX_ENDPOINT:
            return [{
                "\u6307\u6578": "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578",
                "\u65e5\u671f": "1150904",
                "\u6536\u76e4\u6307\u6578": "24000",
            }]
        if url == sources.TWSE_ACTION_ENDPOINT:
            return [
                {"Code": "1101", "Date": "2026-06-30", "CashDividend": "2.0"},
                {"Code": "1101", "Date": "2026-12-31", "CashDividend": "3.0"},
            ]
        if url == sources.TWSE_EVENT_ENDPOINT:
            return [{"Code": "1101", "AnnouncementDate": "2026-09-04", "Title": "material event"}]
        if url == sources.TWSE_FUNDAMENTAL_ENDPOINT:
            return [{"Code": "1101", "Year": "115", "Quarter": "2", "EPS": "3.2"}]
        if url == sources.TPEX_LISTED_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "CompanyName": "TPEx Company", "DateOfListing": "2020/01/02", "SecuritiesIndustryCode": "20"}]
        if url == sources.TPEX_ETF_ENDPOINT:
            return {
                "status": "success",
                "data": [{"stockNo": "00679B", "stockName": "元大美債20年", "listingDate": "2020/01/02", "indexName": ""}],
            }
        if url == sources.TPEX_DAILY_ENDPOINT:
            return [
                {"SecuritiesCompanyCode": "7001", "CompanyName": "TPEx Company", "Date": "2026-09-04", "Open": "50", "High": "52", "Low": "49", "Close": "51", "TradingShares": "2000", "TransactionAmount": "102000"},
                {"SecuritiesCompanyCode": "00679B", "CompanyName": "Bond ETF", "Date": "2026-09-04", "Open": "25", "High": "25.2", "Low": "24.8", "Close": "25", "TradingShares": "3000", "TransactionAmount": "75000"},
            ]
        if url == sources.TPEX_EMERGING_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7002", "CompanyName": "TPEx Emerging", "Date": "2026-09-04", "LatestPrice": "20", "Highest": "21", "Lowest": "19", "TransactionVolume": "500"}]
        if url == sources.TPEX_ACTION_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "Date": "2026-07-01", "CashDividend": "1.0", "OpeningReferencePrice": "50"}]
        if url == sources.TPEX_SUSPEND_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "CompanyName": "TPEx Company"}]
        if url == sources.TPEX_SUSPEND_HISTORY_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "DateOfSuspendedTrading": "2026/09/02", "DateOfResumedTrading": "2026/09/03"}]
        if url == sources.TPEX_EVENT_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "AnnouncementDate": "2026-09-04", "Title": "TPEx event"}]
        if url == sources.TPEX_FUNDAMENTAL_ENDPOINT:
            return [{"SecuritiesCompanyCode": "7001", "Year": "115", "Quarter": "2", "EPS": "1.1"}]
        if url.startswith(sources.TWSE_CHIP_ENDPOINT):
            return {"date": "20260904", "fields": ["Code", "ForeignBuySellDifferenceExcludingForeignDealer", "InvestmentTrustBuySellDifference", "DealerBuySellDifference"], "data": [["1101", "10", "2", "1"]]}
        if url.startswith(sources.TWSE_MARGIN_HISTORY_ENDPOINT):
            return {"date": "20260904", "tables": [{"fields": ["summary"], "data": [["summary"]]}, {"fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額"], "data": [["1101", "Cement", "1", "2", "0", "9787", "11242", "0", "0", "0", "0", "0", "0"]]}]}
        if url == sources.TPEX_HISTORY_API:
            return {"stat": "ok", "date": "20260904", "tables": [{"fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)"], "data": [["7001", "TPEx Company", "51", "0", "50", "52", "49", "51", "2000", "102000"], ["00679B", "元大美債20年", "25", "0", "25", "25.2", "24.8", "25", "3000", "75000"], ["700019", "Warrant", "1", "0", "1", "1", "1", "1", "100", "---"], ["7002", "Emerging", "20", "0", "19", "21", "19", "20", "500", "10000"]]}]}
        if url == sources.TPEX_CHIP_HISTORY_ENDPOINT:
            return {"stat": "ok", "date": "20260904", "tables": [{"fields": [f"f{i}" for i in range(24)], "data": [["7001", "TPEx Company", "1", "2", "10", "1", "2", "1", "1", "2", "1", "2", "3", "4", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]]}]}
        if url == sources.TPEX_MARGIN_HISTORY_ENDPOINT:
            return {"stat": "ok", "date": "20260904", "tables": [{"fields": [f"m{i}" for i in range(20)], "data": [["7001", "TPEx Company", "100", "1", "2", "3", "110", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]]}]}
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "date": "20260904",
                "tables": [
                    {
                        "title": "115\u5e7409\u670804\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                        "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                        "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "24000"]],
                    },
                    {
                        "title": "\u6bcf\u65e5\u6536\u76e4\u884c\u60c5",
                        "fields": ["Code", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"],
                        "data": [["1101", "100", "101", "99", "100", "1000", "100000"]],
                    },
                ],
            }
        if url.startswith(sources.TWSE_HISTORY_API) or url.startswith(sources.TWSE_INDEX_HISTORY_API):
            return []
        raise AssertionError(f"unexpected endpoint: {url}")


def test_official_adapters_normalize_universe_bars_actions_and_mops(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = FixtureFetcher()
    adapter = sources.OfficialMarketDataAdapter(
        twse=sources.TwseAdapter(fetcher),
        tpex=sources.TpexAdapter(fetcher),
    )

    batch = adapter.fetch(date(2026, 9, 4), date(2026, 9, 4))

    by_key = {(item.exchange, item.symbol): item for item in batch.instruments}
    assert ("TWSE", "1101") in by_key
    assert by_key[("TWSE", "0050")].instrument_type == "etf"
    assert by_key[("TWSE", "0050")].etf_category == "broad_market"
    assert by_key[("TPEx", "00679B")].instrument_type == "etf"
    assert by_key[("TPEx", "00679B")].etf_category == "bond"
    assert ("TPEx", "7002") not in by_key
    assert ("TPEx", "700019") not in by_key
    assert all(not (item.exchange == "TPEx" and item.symbol in {"7002", "700019"}) for item in batch.bars)
    assert any(item.exchange == "TWSE" for item in batch.bars)
    assert all(not item.is_suspended for item in batch.bars if item.exchange == "TPEx")
    assert any("announcements do not establish bar suspension status" in warning for warning in batch.warnings)
    assert batch.actions and batch.events and batch.fundamentals
    assert {item.event_type for item in batch.events if item.exchange == "TPEx"} >= {"suspension", "resumption", "material_information"}
    assert batch.chips and all(item.exchange in {"TWSE", "TPEx"} for item in batch.chips)
    assert {item.action_date for item in batch.actions if item.exchange == "TWSE"} == {date(2026, 6, 30)}
    assert {item.action_date for item in batch.actions if item.exchange == "TPEx"} == {date(2026, 7, 1)}
    assert len(batch.payloads) >= 14
    assert all(item.sha256 and item.payload_path.exists() for item in batch.payloads)
    assert fetcher.calls.count(sources.TPEX_SUSPEND_ENDPOINT) == 1
    assert fetcher.calls.count(sources.TPEX_SUSPEND_HISTORY_ENDPOINT) == 1


def test_historical_parser_adds_symbol_and_backfill_is_bounded():
    payload = {
        "fields": ["Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"],
        "data": [["2026/08/03", "100", "105", "98", "103", "1000", "103000"]],
    }
    rows = sources.parse_twse_historical_payload(payload, symbol="1101")
    assert len(rows) == 1
    assert rows[0].symbol == "1101"
    assert rows[0].trading_date == date(2026, 8, 3)
    with pytest.raises(ValueError):
        sources._ensure_backfill_window(date(2026, 1, 1), date(2026, 9, 4))


@pytest.mark.parametrize(
    ("parser", "symbol_key", "amount_key"),
    [
        (sources.parse_twse_daily_rows, "Code", "TradeValue"),
        (sources.parse_tpex_daily_rows, "SecuritiesCompanyCode", "TransactionAmount"),
    ],
)
@pytest.mark.parametrize(
    ("raw_amount", "expected_amount", "expected_status", "expected_reason"),
    [
        (None, 0.0, "unavailable", "missing"),
        ("---", 0.0, "unavailable", "missing"),
        ("not-a-number", 0.0, "unavailable", "invalid"),
        ("-5", 0.0, "unavailable", "invalid"),
        ("0", 0.0, "available", None),
        ("1,234", 1234.0, "available", None),
    ],
)
def test_daily_turnover_availability_preserves_price_and_volume(
    parser, symbol_key, amount_key, raw_amount, expected_amount, expected_status, expected_reason
):
    row = {
        symbol_key: "1101",
        "Date": "2026-09-04",
        "OpeningPrice": "100", "HighestPrice": "105", "LowestPrice": "98", "ClosingPrice": "103",
        "Open": "100", "High": "105", "Low": "98", "Close": "103",
        "TradeVolume": "1000", "TradingShares": "1000",
    }
    if raw_amount is not None:
        row[amount_key] = raw_amount
    bars = parser([row])
    assert len(bars) == 1
    bar = bars[0]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (100, 105, 98, 103, 1000)
    assert (bar.turnover, bar.turnover_status, bar.turnover_reason) == (
        expected_amount, expected_status, expected_reason
    )


def test_twse_all_daily_report_parser_selects_security_table():
    payload = {
        "date": "20260904",
        "tables": [
            {
                "title": "大盤統計資訊",
                "fields": ["指數", "成交量"],
                "data": [["TAIEX", "100"]],
            },
            {
                "title": "個股日成交資訊",
                "fields": [
                    "證券代號",
                    "證券名稱",
                    "成交股數",
                    "成交筆數",
                    "成交金額",
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                    "漲跌價差",
                ],
                "data": [["1101", "Cement", "1,000", "10", "103,000", "100", "105", "98", "103", "+1"]],
            },
        ],
    }
    rows = sources.parse_twse_all_daily_payload(
        payload,
        requested_date=date(2026, 9, 4),
    )
    assert len(rows) == 1
    assert rows[0].symbol == "1101"
    assert rows[0].trading_date == date(2026, 9, 4)
    assert rows[0].close == 103
    assert rows[0].volume == 1000
    assert (rows[0].turnover_status, rows[0].turnover_reason) == ("available", None)


def test_twse_mi_index_explicit_no_data_is_skipped_for_non_trading_weekday(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    calls: list[str] = []

    def fetcher(url: str, **_kwargs):
        calls.append(url)
        if url == sources.TWSE_DAILY_ENDPOINT:
            return []
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "stat": "\u5f88\u62b1\u6b49\uff0c\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u7684\u8cc7\u6599!",
                "type": "ALLBUT0999",
            }
        raise AssertionError(url)

    rows, payloads = sources.TwseAdapter(fetcher).fetch_bars(
        ["1101"], date(2026, 6, 19), date(2026, 6, 19)
    )
    assert rows == []
    assert len(payloads) == 2
    assert any(
        "date=20260619&type=ALLBUT0999&response=json" in url
        for url in calls
    )


def test_twse_mi_index_rows_without_reported_date_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def fetcher(url: str, **_kwargs):
        if url == sources.TWSE_DAILY_ENDPOINT:
            return []
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "stat": "\u5f88\u62b1\u6b49\uff0c\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u7684\u8cc7\u6599!",
                "type": "ALLBUT0999",
                "tables": [{"fields": ["Code"], "data": [["1101"]]}],
            }
        raise AssertionError(url)

    with pytest.raises(sources.OfficialDataError, match="omitted its reported date"):
        sources.TwseAdapter(fetcher).fetch_bars(
            ["1101"], date(2026, 6, 19), date(2026, 6, 19)
        )


def test_twse_mi_index_taiex_row_uses_requested_date_and_provenance():
    payload = {
        "date": "20260605",
        "tables": [
            {
                "title": "115\u5e7406\u670805\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578", "\u6f32\u8dcc"],
                "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "22123.45", "+"]],
            }
        ],
    }
    rows = sources.parse_twse_taiex_from_all_daily_payload(
        payload,
        requested_date=date(2026, 6, 5),
        payload_sha256="fixture-sha",
    )
    assert len(rows) == 1
    assert rows[0].symbol == "TAIEX"
    assert rows[0].trading_date == date(2026, 6, 5)
    assert rows[0].close == 22123.45
    assert rows[0].payload_sha256 == "fixture-sha"
    assert (rows[0].turnover, rows[0].turnover_status, rows[0].turnover_reason) == (
        0, "unavailable", "synthetic_index"
    )


def test_twse_mi_index_selects_price_table_not_return_table():
    payload = {
        "date": "20260908",
        "tables": [
            {
                "title": "115\u5e7409\u670808\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578", "\u6f32\u8dcc"],
                "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "47105.78", "-"]],
            },
            {
                "title": "115\u5e7409\u670808\u65e5 \u5831\u916c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                "fields": ["\u5831\u916c\u6307\u6578", "\u6536\u76e4\u6307\u6578", "\u6f32\u8dcc"],
                "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u5831\u916c\u6307\u6578", "108777.60", "-"]],
            },
        ],
    }
    rows = sources.parse_twse_taiex_from_all_daily_payload(
        payload,
        requested_date=date(2026, 9, 8),
    )
    assert len(rows) == 1
    assert rows[0].close == 47105.78


def test_twse_openapi_adjacent_dates_select_exact_price_row():
    price_label = "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578"
    return_label = "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u5831\u916c\u6307\u6578"
    rows_by_date = {
        "2026-09-07": [
            {"\u6307\u6578": price_label, "\u65e5\u671f": "1150907", "\u6536\u76e4\u6307\u6578": "47326.27"},
            {"\u6307\u6578": return_label, "\u65e5\u671f": "1150907", "\u6536\u76e4\u6307\u6578": "109275.93"},
        ],
        "2026-09-08": [
            {"\u6307\u6578": price_label, "\u65e5\u671f": "1150908", "\u6536\u76e4\u6307\u6578": "47105.78"},
            {"\u6307\u6578": return_label, "\u65e5\u671f": "1150908", "\u6536\u76e4\u6307\u6578": "108777.60"},
        ],
    }
    first = sources.parse_twse_taiex_from_index_payload(
        rows_by_date["2026-09-07"], requested_date=date(2026, 9, 7)
    )
    second = sources.parse_twse_taiex_from_index_payload(
        rows_by_date["2026-09-08"], requested_date=date(2026, 9, 8)
    )
    assert [row.close for row in first] == [47326.27]
    assert [row.close for row in second] == [47105.78]
    assert all(
        row.turnover_status == "unavailable" and row.turnover_reason == "synthetic_index"
        for row in [*first, *second]
    )


def test_twse_monthly_index_does_not_claim_synthetic_turnover_is_available():
    rows = sources.parse_twse_index_history_payload(
        [{"Date": "2026-09-04", "ClosingIndex": "24000"}]
    )
    assert len(rows) == 1
    assert (rows[0].turnover, rows[0].turnover_status, rows[0].turnover_reason) == (
        0, "unavailable", "synthetic_index"
    )


def test_twse_taiex_parser_rejects_wrong_date_duplicate_and_nonpositive_rows():
    base = {"\u6307\u6578": "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "\u65e5\u671f": "1150908", "\u6536\u76e4\u6307\u6578": "47105.78"}
    assert sources.parse_twse_taiex_from_index_payload(
        [base], requested_date=date(2026, 9, 7)
    ) == []
    assert sources.parse_twse_taiex_from_index_payload(
        [base, dict(base)], requested_date=date(2026, 9, 8)
    ) == []
    invalid = dict(base, **{"\u6536\u76e4\u6307\u6578": "0"})
    assert sources.parse_twse_taiex_from_index_payload(
        [invalid], requested_date=date(2026, 9, 8)
    ) == []


def test_twse_one_day_current_bars_still_fetch_date_scoped_taiex(tmp_path, monkeypatch):
    """A current security snapshot must not bypass TAIEX date validation."""

    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    requested = date(2026, 9, 8)
    calls: list[str] = []

    def fetcher(url: str, **_kwargs):
        calls.append(url)
        if url == sources.TWSE_DAILY_ENDPOINT:
            return [
                {
                    "Code": "1101",
                    "Date": requested.isoformat(),
                    "OpeningPrice": "100",
                    "HighestPrice": "101",
                    "LowestPrice": "99",
                    "ClosingPrice": "100",
                    "TradeVolume": "1000",
                    "TradeValue": "100000",
                }
            ]
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "date": "20260908",
                "tables": [
                        {
                            "title": "115\u5e7409\u670808\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                            "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                            "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "24000"]],
                        }
                ],
            }
        raise AssertionError(url)

    rows, payloads = sources.TwseAdapter(fetcher).fetch_bars(
        ["1101"], requested, requested
    )

    assert any(row.symbol == "TAIEX" and row.trading_date == requested for row in rows)
    assert any(url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT) for url in calls)
    assert len(payloads) == 2


def test_twse_holiday_calendar_excludes_known_closed_session(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    calls: list[str] = []

    def fetcher(url: str, **_kwargs):
        calls.append(url)
        if url == sources.TWSE_DAILY_ENDPOINT:
            return []
        if url == sources.TWSE_HOLIDAY_ENDPOINT:
            return [{"Date": "1150619", "Name": "\u7aef\u5348\u7bc0", "Description": "\u4f9d\u898f\u5b9a\u653e\u5047 1 \u65e5"}]
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            requested = "20260618" if "20260618" in url else "20260622"
            return {
                "date": requested,
                "tables": [
                    {
                        "title": "115\u5e7406\u670818\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                        "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                        "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "100"]],
                    },
                    {
                        "fields": ["Code", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"],
                        "data": [["1101", "100", "101", "99", "100", "1000", "100000"]],
                    },
                ],
            }
        raise AssertionError(url)

    rows, payloads = sources.TwseAdapter(fetcher).fetch_bars(
        ["1101"], date(2026, 6, 18), date(2026, 6, 22)
    )
    assert {row.trading_date for row in rows} == {date(2026, 6, 18), date(2026, 6, 22)}
    assert {row.symbol for row in rows} == {"1101", "TAIEX"}
    assert not any("date=20260619" in url for url in calls)
    assert len(payloads) == 4  # daily feed, official calendar, and two sessions


def test_twse_historical_transport_failure_is_partial_and_date_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def session_payload(requested: str):
        return {
            "date": requested,
            "tables": [
                {
                    "title": "115\u5e7406\u670818\u65e5 \u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                    "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"],
                    "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "100"]],
                },
                {
                "title": "個股日成交資訊",
                "fields": ["證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額"],
                "data": [["1101", "100", "101", "99", "100", "1000", "100000"]],
            }],
        }

    def fetcher(url: str, **_kwargs):
        if url == sources.TWSE_DAILY_ENDPOINT:
            return []
        if url == sources.TWSE_HOLIDAY_ENDPOINT:
            return []
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            if "date=20260619" in url:
                raise sources.OfficialDataError("official endpoint retry exhausted (307): " + url)
            if "date=20260618" in url:
                return session_payload("20260618")
            if "date=20260622" in url:
                return session_payload("20260622")
        raise AssertionError(url)

    adapter = sources.TwseAdapter(fetcher)
    rows, payloads = adapter.fetch_bars(
        ["1101"], date(2026, 6, 18), date(2026, 6, 22)
    )

    assert {row.trading_date for row in rows} == {date(2026, 6, 18), date(2026, 6, 22)}
    assert len(payloads) == 4  # daily feed, calendar, and two successful sessions
    assert len(adapter.fetch_warnings) == 1
    warning = adapter.fetch_warnings[0]
    assert "2026-06-19" in warning
    assert sources.TWSE_DAILY_HISTORY_ENDPOINT in warning


def test_tpex_backfill_empty_history_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def fetcher(url: str):
        if url == sources.TPEX_DAILY_ENDPOINT:
            return [
                {
                    "SecuritiesCompanyCode": "7001",
                    "Date": "2026-09-04",
                    "Open": "50",
                    "High": "52",
                    "Low": "49",
                    "Close": "51",
                    "TradingShares": "2000",
                    "TransactionAmount": "102000",
                }
            ]
        if url.startswith(sources.TPEX_HISTORY_API):
            return []
        raise AssertionError(f"unexpected endpoint: {url}")

    adapter = sources.TpexAdapter(fetcher)
    with pytest.raises(sources.OfficialDataError, match="no prior-session OHLCV"):
        adapter.fetch_bars(["7001"], date(2026, 9, 3), date(2026, 9, 4))


def test_suspension_parser_does_not_infer_from_empty_rows():
    assert sources.parse_suspended_symbols([{"SecuritiesCompanyCode": "7001"}, {"SecuritiesCompanyCode": ""}]) == {"7001"}
    assert sources.parse_suspended_symbols([]) == set()


def test_twse_margin_duplicate_headers_use_financing_positions():
    payload = {
        "date": "20260904",
        "tables": [{"fields": ["summary"], "data": [["summary"]]}, {
            "fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額"],
            "data": [["00400A", "fixture", "0", "0", "0", "9787", "11242", "0", "0", "0", "0", "77", "88"]],
        }],
    }
    rows = sources.parse_twse_margin_rows(payload, trading_date=date(2026, 9, 4))
    assert len(rows) == 1
    assert rows[0].exchange == "TWSE"
    assert rows[0].margin_balance == 11242
    assert rows[0].margin_change == 1455


def test_tpex_institutional_fixed_positions_do_not_leak_into_twse_parser():
    payload = {"tables": [{"fields": [f"f{i}" for i in range(24)], "data": [["7001", "name", "1", "2", "10", "1", "2", "3", "4", "5", "6", "7", "8", "20", "10", "11", "12", "13", "14", "15", "16", "17", "30", "40"]]}]}
    rows = sources.parse_tpex_institutional_rows(payload, trading_date=date(2026, 9, 4))
    assert rows[0].exchange == "TPEx"
    assert rows[0].foreign_buy == 10
    assert rows[0].trust_buy == 20
    assert rows[0].dealer_buy == 30
    assert rows[0].total_buy_sell == 40
    assert sources.parse_twse_margin_rows(payload, trading_date=date(2026, 9, 4)) == []


def test_tpex_wrong_reported_date_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def fetcher(url: str, **_kwargs):
        if url == sources.TPEX_HISTORY_API:
            return {"stat": "ok", "date": "20260904", "tables": [{"fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)"], "data": [["7001", "fixture", "1", "0", "1", "1", "1", "1", "1", "1"]]}]}
        raise AssertionError(url)

    with pytest.raises(sources.OfficialDataError, match="date report mismatch"):
        sources.TpexAdapter(fetcher).fetch_bars(["7001"], date(2026, 6, 5), date(2026, 6, 5))


def test_twse_historical_wrong_reported_date_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def fetcher(url: str, **_kwargs):
        if url == sources.TWSE_DAILY_ENDPOINT:
            return []
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            return {
                "date": "20260904",
                "tables": [{
                    "fields": ["證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額"],
                    "data": [["1101", "100", "101", "99", "100", "1000", "100000"]],
                }],
            }
        raise AssertionError(url)

    with pytest.raises(sources.OfficialDataError, match="date report mismatch"):
        sources.TwseAdapter(fetcher).fetch_bars(["1101"], date(2026, 6, 5), date(2026, 6, 5))


def test_twse_wrong_reported_date_is_fail_closed_for_optional_chips(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")

    def fetcher(url: str, **_kwargs):
        return {"date": "20260904", "fields": ["Code"], "data": [["1101"]]}

    rows, payloads, warnings = sources.TwseAdapter(fetcher).fetch_chips([date(2026, 6, 5)], {"1101"})
    assert rows == []
    assert len(payloads) == 2
    assert any("date report mismatch" in warning for warning in warnings)


def test_fetch_json_retries_520_then_succeeds_and_does_not_retry_4xx(monkeypatch):
    request = httpx.Request("POST", "https://fixture.example")
    responses = [httpx.Response(520, request=request), httpx.Response(200, json={"ok": True}, request=request)]
    calls = {"count": 0}

    def post(*_args, **_kwargs):
        calls["count"] += 1
        return responses.pop(0)

    monkeypatch.setattr(sources.httpx, "post", post)
    monkeypatch.setattr(sources.time, "sleep", lambda _delay: None)
    assert sources.fetch_json("https://fixture.example", method="POST") == {"ok": True}
    assert calls["count"] == 2

    calls["count"] = 0
    monkeypatch.setattr(sources.httpx, "post", lambda *_args, **_kwargs: (calls.__setitem__("count", calls["count"] + 1) or httpx.Response(404, request=request)))
    with pytest.raises(sources.OfficialDataError, match="rejected request"):
        sources.fetch_json("https://fixture.example", method="POST")
    assert calls["count"] == 1


def test_fetch_json_retries_body_bearing_307_without_location(monkeypatch):
    request = httpx.Request("GET", "https://fixture.example")
    responses = [
        httpx.Response(307, content=b"temporary CDN security response", request=request),
        httpx.Response(200, json={"ok": True}, request=request),
    ]
    calls = {"count": 0}

    def get(*_args, **_kwargs):
        calls["count"] += 1
        return responses.pop(0)

    monkeypatch.setattr(sources.httpx, "get", get)
    monkeypatch.setattr(sources.time, "sleep", lambda _delay: None)
    assert sources.fetch_json("https://fixture.example") == {"ok": True}
    assert calls["count"] == 2


def test_fetch_json_wraps_transport_retry_exhaustion_with_cause(monkeypatch):
    calls = {"count": 0}

    def post(*_args, **_kwargs):
        calls["count"] += 1
        raise httpx.TransportError("fixture network down")

    monkeypatch.setattr(sources.httpx, "post", post)
    monkeypatch.setattr(sources.time, "sleep", lambda _delay: None)
    with pytest.raises(sources.OfficialDataError, match="transport retry exhausted") as error:
        sources.fetch_json("https://fixture.example", method="POST")
    assert calls["count"] == 3
    assert isinstance(error.value.__cause__, httpx.TransportError)


def test_fetch_json_wraps_retryable_http_exhaustion_with_cause(monkeypatch):
    request = httpx.Request("GET", "https://fixture.example")
    calls = {"count": 0}

    def get(*_args, **_kwargs):
        calls["count"] += 1
        return httpx.Response(520, content=b"temporary edge failure", request=request)

    monkeypatch.setattr(sources.httpx, "get", get)
    monkeypatch.setattr(sources.time, "sleep", lambda _delay: None)
    with pytest.raises(sources.OfficialDataError, match="retry exhausted") as error:
        sources.fetch_json("https://fixture.example")
    assert calls["count"] == 3
    assert isinstance(error.value.__cause__, httpx.HTTPStatusError)
