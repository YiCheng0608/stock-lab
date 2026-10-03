"""Synthetic 2026-09-04 legacy volume cases; direct unittest uses no I/O.

Run with Python -B -X utf8 and STOCK_TEST_DEPS pointing to read-only deps.
The standalone config stub and audit guard never affect ordinary test imports.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


BLOCKED_OPERATIONS = []


def _standalone_sources():
    sys.dont_write_bytecode = True

    def no_io(event, arguments):
        denied = event in {
            "os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link",
            "os.symlink", "os.truncate", "os.chmod", "os.utime",
            "subprocess.Popen", "socket.__new__", "socket.connect",
            "socket.bind", "socket.sendto", "socket.getaddrinfo",
        }
        if event == "open":
            mode, flags = arguments[1:3]
            denied = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
                ))
            )
        if denied:
            BLOCKED_OPERATIONS.append(event)
            raise AssertionError("standalone memory test attempted I/O: " + event)

    sys.addaudithook(no_io)
    backend = Path(__file__).resolve().parents[1]
    dependencies = os.environ["STOCK_TEST_DEPS"].split(os.pathsep)
    sys.path[:0] = [str(backend), *dependencies]
    config = ModuleType("app.config")
    config.OFFICIAL_MAX_BACKFILL_DAYS = 93
    config.RAW_DIR = Path("memory-unused/raw")
    with patch.dict(sys.modules, {"app.config": config}):
        from worker import sources as imported_sources
    return imported_sources


if __name__ == "__main__":
    sources = _standalone_sources()
else:
    from worker import sources


DAY = date(2026, 9, 4)
ODD_VOLUME = 9007199254740993
MAX_VOLUME = 9223372036854775807
MARKETS = (
    (sources.parse_twse_daily_rows, "Code", "TradeVolume", "TradeValue", "TWSE"),
    (sources.parse_tpex_daily_rows, "SecuritiesCompanyCode", "TradingShares", "TransactionAmount", "TPEx"),
)


def _row(symbol_key, volume_key, amount_key, value):
    return {
        symbol_key: "1101", "Date": DAY.isoformat(),
        "OpeningPrice": "100", "HighestPrice": "105", "LowestPrice": "98", "ClosingPrice": "103",
        "Open": "100", "High": "105", "Low": "98", "Close": "103",
        volume_key: value, amount_key: "103000",
    }


def _table(row):
    return {"fields": list(row), "data": [list(row.values())]}


def _tpex_report(value, day=DAY):
    row = _row("SecuritiesCompanyCode", "TradingShares", "TransactionAmount", value)
    row["Date"] = day.isoformat()
    return {"date": day.strftime("%Y%m%d"), "tables": [_table(row)]}


def _captured(endpoint, payload, data_as_of):
    # _fetch is replaced at its persistence boundary; only metadata is used.
    return sources.FetchedPayload(
        "synthetic", endpoint, payload, data_as_of,
        datetime(2026, 9, 5, tzinfo=timezone.utc), Path("memory-unused/body.json"), "a" * 64,
    )


class LegacyDailyVolumeMemoryTests(unittest.TestCase):
    subcase_count = 0

    def subTest(self, *args, **kwargs):
        type(self).subcase_count += 1
        return super().subTest(*args, **kwargs)

    def test_exact_supported_values_and_zero_in_both_markets(self):
        cases = [
            (0, 0), ("0", 0), (" +0.000 ", 0), (Decimal("-0"), 0),
            (1234, 1234), ("1,234", 1234), ("+1,234.000", 1234),
            ("001234", 1234), (Decimal("1E+3"), 1000),
            (ODD_VOLUME, ODD_VOLUME), (str(ODD_VOLUME), ODD_VOLUME),
            ("9,007,199,254,740,993.0", ODD_VOLUME), (Decimal(ODD_VOLUME), ODD_VOLUME),
            (MAX_VOLUME, MAX_VOLUME), (str(MAX_VOLUME) + ".000", MAX_VOLUME),
            (Decimal(MAX_VOLUME), MAX_VOLUME),
        ]
        for parser, symbol_key, volume_key, amount_key, exchange in MARKETS:
            for value, expected in cases:
                with self.subTest(exchange=exchange, value=value):
                    bars = parser([_row(symbol_key, volume_key, amount_key, value)], payload_sha256="a" * 64)
                    self.assertEqual(len(bars), 1)
                    bar = bars[0]
                    self.assertIs(type(bar.volume), int)
                    self.assertEqual(bar.volume, expected)
                    self.assertEqual((bar.symbol, bar.trading_date, bar.exchange), ("1101", DAY, exchange))
                    self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100, 105, 98, 103))
                    self.assertEqual((bar.data_as_of, bar.payload_sha256), (DAY.isoformat(), "a" * 64))

    def test_invalid_values_reject_whole_row_in_both_markets(self):
        invalid = [
            None, "", "  ", "--", "-", "---", "X", "N/A", "\u7121",
            True, False, 0.0, 1234.0, float(ODD_VOLUME), float("nan"), float("inf"),
            [], {}, (1234,), b"1234", object(),
            -1, "-1", "-0", "1.5", Decimal("1.5"), Decimal("-1"),
            Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"),
            "1234 shares", "shares 1234", "1 234", "1,23", "12,34,567", "1234,567",
            "1,,234", ",123", "1_234", "1e3", "1E+3", ".0", "1.", "++1", "\uff11\uff12\uff13",
            MAX_VOLUME + 1, str(MAX_VOLUME + 1), Decimal(MAX_VOLUME + 1), "9" * 5000, 10**5000,
        ]
        for parser, symbol_key, volume_key, amount_key, exchange in MARKETS:
            for index, value in enumerate(invalid):
                with self.subTest(exchange=exchange, case=index, kind=type(value).__name__):
                    self.assertEqual(parser([_row(symbol_key, volume_key, amount_key, value)]), [])

    def test_alias_order_preserves_zero_and_does_not_hide_invalid_primary(self):
        for parser, symbol_key, volume_key, amount_key, exchange in MARKETS:
            for alias in (volume_key, "\u6210\u4ea4\u80a1\u6578", "\u6210\u4ea4\u91cf"):
                with self.subTest(exchange=exchange, alias=alias):
                    row = _row(symbol_key, volume_key, amount_key, None)
                    row[alias] = "1,234"
                    self.assertEqual(parser([row])[0].volume, 1234)
            for primary, expected in [(None, 1234), (" ", 1234), (0, 0), ("0", 0), ("1.5", None), (0.0, None), (False, None)]:
                with self.subTest(exchange=exchange, primary=primary):
                    row = _row(symbol_key, volume_key, amount_key, primary)
                    row["\u6210\u4ea4\u80a1\u6578"] = "1234"
                    row["\u6210\u4ea4\u91cf"] = "5678"
                    bars = parser([row])
                    self.assertEqual([bar.volume for bar in bars], [] if expected is None else [expected])
            with self.subTest(exchange=exchange, invalid_first_chinese_alias=True):
                row = _row(symbol_key, volume_key, amount_key, None)
                row["\u6210\u4ea4\u80a1\u6578"], row["\u6210\u4ea4\u91cf"] = "1.5", "1234"
                self.assertEqual(parser([row]), [])

    def test_table_wrappers_preserve_exact_values_and_reject_fraction(self):
        for parser, symbol_key, volume_key, amount_key, exchange in MARKETS:
            for value, expected in [(str(ODD_VOLUME), [ODD_VOLUME]), ("1.5", [])]:
                row = _row(symbol_key, volume_key, amount_key, value)
                wrappers = [row, [row], {"data": [row]}, _table(row), {"tables": [_table(row)]},
                            *({key: [row]} for key in ("rows", "items", "result"))]
                for index, payload in enumerate(wrappers):
                    with self.subTest(exchange=exchange, value=value, wrapper=index):
                        self.assertEqual([bar.volume for bar in parser(payload)], expected)

    def test_valid_volume_keeps_turnover_availability_and_invalid_neighbor_is_omitted(self):
        for parser, symbol_key, volume_key, amount_key, exchange in MARKETS:
            for amount, expected in [(None, (0.0, "unavailable", "missing")), ("bad", (0.0, "unavailable", "invalid")), ("0", (0.0, "available", None))]:
                with self.subTest(exchange=exchange, amount=amount):
                    row = _row(symbol_key, volume_key, amount_key, "0")
                    row[amount_key] = amount
                    invalid = _row(symbol_key, volume_key, amount_key, "1.5")
                    invalid[symbol_key] = "BAD"
                    bars = parser([invalid, row])
                    self.assertEqual([(bar.symbol, bar.volume) for bar in bars], [("1101", 0)])
                    self.assertEqual((bars[0].turnover, bars[0].turnover_status, bars[0].turnover_reason), expected)

    def test_twse_history_and_mi_index_parser_routes(self):
        for value, expected in [(str(ODD_VOLUME), [ODD_VOLUME]), ("1.5", [])]:
            with self.subTest(value=value, route="history"):
                row = _row("Code", "TradeVolume", "TradeValue", value)
                del row["Code"]
                bars = sources.parse_twse_historical_payload(_table(row), symbol="1101")
                self.assertEqual([(bar.symbol, bar.volume) for bar in bars], [("1101", v) for v in expected])
            with self.subTest(value=value, route="MI_INDEX"):
                row = _row("\u8b49\u5238\u4ee3\u865f", "\u6210\u4ea4\u80a1\u6578", "\u6210\u4ea4\u91d1\u984d", value)
                del row["Date"]
                payload = {"date": "20260904", "tables": [_table(row)]}
                bars = sources.parse_twse_all_daily_payload(payload, requested_date=DAY)
                self.assertEqual([bar.volume for bar in bars], expected)

    def test_twse_adapter_current_and_history_routes_without_fetch_or_persistence(self):
        for value, expected in [(str(ODD_VOLUME), [ODD_VOLUME]), ("1.5", [])]:
            with self.subTest(value=value):
                row = _row("Code", "TradeVolume", "TradeValue", value)
                index = {"title": "\u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)",
                         "fields": ["\u6307\u6578", "\u6536\u76e4\u6307\u6578"], "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "24000"]]}
                history = {"date": "20260904", "tables": [index, _table(row)]}
                calls = []
                def fetched(endpoint, data_as_of=None, **kwargs):
                    calls.append(endpoint)
                    if endpoint == sources.TWSE_DAILY_ENDPOINT:
                        payload = [row]
                    elif endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT + "?"):
                        payload = history
                    else:
                        self.fail("unexpected endpoint: " + endpoint)
                    return _captured(endpoint, payload, data_as_of)
                adapter = sources.TwseAdapter()
                with patch.object(adapter, "_fetch", side_effect=fetched):
                    bars, payloads = adapter.fetch_bars(["1101"], DAY, DAY)
                self.assertEqual([bar.volume for bar in bars if bar.symbol == "1101"], expected)
                self.assertEqual([bar.symbol for bar in bars if bar.symbol == "TAIEX"], ["TAIEX"])
                self.assertEqual(len(payloads), 2)
                self.assertEqual(calls[0], sources.TWSE_DAILY_ENDPOINT)
                self.assertEqual(adapter.no_data_dates, [])

    def test_tpex_adapter_empty_vs_nonempty_invalid_tables(self):
        cases = [("valid", _tpex_report(str(ODD_VOLUME)), [ODD_VOLUME], False),
                 ("invalid", _tpex_report("1.5"), [], False)]
        for key in ("data", "rows", "items", "result"):
            cases.append((key + "_empty", {"date": "20260904", key: []}, [], True))
            cases.append((key + "_invalid", {"date": "20260904", key: [_row("SecuritiesCompanyCode", "TradingShares", "TransactionAmount", "1.5")]}, [], False))
        cases.append(("table_empty", {"date": "20260904", "tables": [{"fields": ["TradingShares"], "data": []}]}, [], True))
        for label, payload, expected, no_data in cases:
            with self.subTest(label=label):
                adapter = sources.TpexAdapter()
                with patch.object(adapter, "_fetch", return_value=_captured(sources.TPEX_HISTORY_API, payload, DAY.isoformat())) as fetched:
                    bars, payloads = adapter.fetch_bars(["1101"], DAY, DAY)
                self.assertEqual([bar.volume for bar in bars], expected)
                self.assertEqual(adapter.no_data_dates, [DAY] if no_data else [])
                self.assertEqual(len(payloads), 1)
                self.assertEqual(fetched.call_args.kwargs["method"], "POST")

    def test_tpex_existing_date_and_prior_session_guards_remain_fail_closed(self):
        for reported in (None, "20260903"):
            with self.subTest(reported=reported):
                payload = _tpex_report("1.5")
                if reported is None:
                    del payload["date"]
                else:
                    payload["date"] = reported
                adapter = sources.TpexAdapter()
                with patch.object(adapter, "_fetch", return_value=_captured(sources.TPEX_HISTORY_API, payload, DAY.isoformat())):
                    with self.assertRaises(sources.OfficialDataError):
                        adapter.fetch_bars(["1101"], DAY, DAY)
                self.assertEqual(adapter.no_data_dates, [])
        start = date(2026, 9, 3)
        for prior, current, should_fail in [("1.5", "1.5", True), ("1.5", "1234", True), ("empty", "empty", False), ("1234", "1.5", False)]:
            with self.subTest(prior=prior, current=current):
                adapter = sources.TpexAdapter()
                def fetched(endpoint, data_as_of=None, **kwargs):
                    day = date.fromisoformat(data_as_of)
                    value = prior if day == start else current
                    payload = ({"date": day.strftime("%Y%m%d"), "tables": [{"fields": ["TradingShares"], "data": []}]}
                               if value == "empty" else _tpex_report(value, day))
                    return _captured(endpoint, payload, data_as_of)
                with patch.object(adapter, "_fetch", side_effect=fetched):
                    if should_fail:
                        with self.assertRaisesRegex(sources.OfficialDataError, "no prior-session OHLCV"):
                            adapter.fetch_bars(["1101"], start, DAY)
                    else:
                        bars, _ = adapter.fetch_bars(["1101"], start, DAY)
                        self.assertEqual([bar.volume for bar in bars], [] if prior == "empty" else [1234])
                self.assertEqual(adapter.no_data_dates, [start, DAY] if prior == "empty" else [])

    def test_shared_integer_and_mops_behavior_is_unchanged(self):
        for value, expected in [("115", 115), ("115.5", 115), ("year 115", 115), ("1e3", 1)]:
            with self.subTest(value=value):
                self.assertEqual(sources.parse_integer(value), expected)
        self.assertEqual(sources._mops_year("115"), 2026)
        self.assertEqual(sources._mops_period_end({"Year": "115", "Quarter": "2"}), (date(2026, 6, 30), "Q2"))
        self.assertEqual(sources._mops_period_end({"DataMonth": "11509"}), (date(2026, 9, 30), "M09"))


if __name__ == "__main__":
    print("Python=" + sys.version.split()[0] + " httpx=" + sources.httpx.__version__, flush=True)
    run = unittest.main(exit=False, verbosity=2)
    print("subcases=" + str(LegacyDailyVolumeMemoryTests.subcase_count)
          + " blocked_io=" + str(len(BLOCKED_OPERATIONS)), flush=True)
    sys.exit(0 if run.result.wasSuccessful() and not BLOCKED_OPERATIONS else 1)
