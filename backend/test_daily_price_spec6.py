#!/usr/bin/env python3
"""Test spec-6: Daily price adapter (parse_twse and parse_tpex) for TWSE-listed and TPEx-OTC markets.

Tests that parse_twse and parse_tpex correctly:
1. Parse fixed sample responses for TWSE (上市) and TPEx (上櫃) markets
2. Output normalized OHLCV rows with correct field names, types, and values
3. Set market field correctly ("listed" for TWSE, "otc" for TPEx)
"""

import sys
import json
import datetime as dt
from decimal import Decimal
from pathlib import Path

# Add app module to path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

from app.adapters.daily_price import parse_twse, parse_tpex


def test_parse_twse():
    """Test TWSE (上市) daily price parsing with realistic fixture."""
    print("TEST 1: parse_twse with TWSE-listed market fixture...")

    # Realistic TWSE MI_INDEX response fixture
    twse_fixture = {
        "date": "20240115",  # 2024-01-15
        "tables": [
            {
                "title": "每日收盤行情",
                "data": [
                    # [symbol, name, volume_shares, count, amount, open, high, low, close, ...]
                    ["2330", "台積電", "5,432,100", "12,345", "432,156,789", "600.00", "605.50", "598.75", "603.00"],
                    ["3008", "聯發科", "2,156,000", "8,901", "215,604,321", "925.00", "932.50", "920.00", "928.00"],
                    ["2450", "聯發科", "1,000", "100", "50,000", "--", "--", "--", "--"],  # All dashes, should be skipped
                ]
            }
        ]
    }

    result = parse_twse(twse_fixture)

    # Verify we got 2 rows (third row with dashes should be skipped)
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (台積電)
    row1 = result[0]
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["open_raw"], Decimal), f"Expected open_raw to be Decimal, got {type(row1['open_raw'])}"
    assert row1["open_raw"] == Decimal("600.00"), f"Expected open 600.00, got {row1['open_raw']}"
    assert row1["high_raw"] == Decimal("605.50"), f"Expected high 605.50, got {row1['high_raw']}"
    assert row1["low_raw"] == Decimal("598.75"), f"Expected low 598.75, got {row1['low_raw']}"
    assert row1["close_raw"] == Decimal("603.00"), f"Expected close 603.00, got {row1['close_raw']}"
    assert isinstance(row1["volume"], int), f"Expected volume to be int, got {type(row1['volume'])}"
    assert row1["volume"] == 5432100, f"Expected volume 5432100, got {row1['volume']}"
    print(f"  ✓ Row 1 (2330) has correct fields, types, and values")

    # Check second row (聯發科 3008)
    row2 = result[1]
    assert row2["symbol"] == "3008", f"Expected symbol 3008, got {row2['symbol']}"
    assert row2["market"] == "listed", f"Expected market 'listed', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["open_raw"] == Decimal("925.00"), f"Expected open 925.00, got {row2['open_raw']}"
    assert row2["high_raw"] == Decimal("932.50"), f"Expected high 932.50, got {row2['high_raw']}"
    assert row2["low_raw"] == Decimal("920.00"), f"Expected low 920.00, got {row2['low_raw']}"
    assert row2["close_raw"] == Decimal("928.00"), f"Expected close 928.00, got {row2['close_raw']}"
    assert row2["volume"] == 2156000, f"Expected volume 2156000, got {row2['volume']}"
    print(f"  ✓ Row 2 (3008) has correct fields, types, and values")

    return True


def test_parse_tpex():
    """Test TPEx (上櫃) daily price parsing with realistic fixture."""
    print("\nTEST 2: parse_tpex with TPEx-OTC market fixture...")

    # Realistic TPEx daily_close_quotes response fixture
    tpex_fixture = {
        "date": "20240115",  # 2024-01-15
        "tables": [
            {
                "data": [
                    # [symbol, name, close, change, open, high, low, avg, volume_shares, ...]
                    ["4956", "光磊", "45.80", "+0.30", "45.50", "46.20", "45.35", "45.78", "1,234,567"],
                    ["5264", "宜鼎", "32.15", "-0.85", "33.00", "33.20", "31.90", "32.20", "2,345,678"],
                    ["5555", "測試股", "100.00", "+0.00", "--", "--", "--", "--", "--"],  # Missing OHLC, should be skipped
                ]
            }
        ]
    }

    result = parse_tpex(tpex_fixture)

    # Verify we got 2 rows (third row with dashes should be skipped)
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (光磊)
    row1 = result[0]
    assert row1["symbol"] == "4956", f"Expected symbol 4956, got {row1['symbol']}"
    assert row1["market"] == "otc", f"Expected market 'otc', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["open_raw"], Decimal), f"Expected open_raw to be Decimal, got {type(row1['open_raw'])}"
    assert row1["open_raw"] == Decimal("45.50"), f"Expected open 45.50, got {row1['open_raw']}"
    assert row1["high_raw"] == Decimal("46.20"), f"Expected high 46.20, got {row1['high_raw']}"
    assert row1["low_raw"] == Decimal("45.35"), f"Expected low 45.35, got {row1['low_raw']}"
    assert row1["close_raw"] == Decimal("45.80"), f"Expected close 45.80, got {row1['close_raw']}"
    assert isinstance(row1["volume"], int), f"Expected volume to be int, got {type(row1['volume'])}"
    assert row1["volume"] == 1234567, f"Expected volume 1234567, got {row1['volume']}"
    print(f"  ✓ Row 1 (4956) has correct fields, types, and values")

    # Check second row (宜鼎)
    row2 = result[1]
    assert row2["symbol"] == "5264", f"Expected symbol 5264, got {row2['symbol']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["open_raw"] == Decimal("33.00"), f"Expected open 33.00, got {row2['open_raw']}"
    assert row2["high_raw"] == Decimal("33.20"), f"Expected high 33.20, got {row2['high_raw']}"
    assert row2["low_raw"] == Decimal("31.90"), f"Expected low 31.90, got {row2['low_raw']}"
    assert row2["close_raw"] == Decimal("32.15"), f"Expected close 32.15, got {row2['close_raw']}"
    assert row2["volume"] == 2345678, f"Expected volume 2345678, got {row2['volume']}"
    print(f"  ✓ Row 2 (5264) has correct fields, types, and values")

    return True


def test_parse_twse_json_bytes():
    """Test TWSE parsing with JSON bytes input (not dict)."""
    print("\nTEST 3: parse_twse with JSON bytes input...")

    twse_data = {
        "date": "20240116",
        "tables": [
            {
                "title": "每日收盤行情",
                "data": [
                    ["1101", "台泥", "10,000", "500", "100,000", "10.00", "10.20", "9.90", "10.05"],
                ]
            }
        ]
    }

    # Pass as JSON bytes instead of dict
    json_bytes = json.dumps(twse_data).encode("utf-8")
    result = parse_twse(json_bytes)

    assert len(result) == 1, f"Expected 1 row, got {len(result)}"
    assert result[0]["symbol"] == "1101", f"Expected symbol 1101, got {result[0]['symbol']}"
    assert result[0]["date"] == dt.date(2024, 1, 16), f"Expected date 2024-01-16, got {result[0]['date']}"
    print(f"  ✓ Correctly parsed JSON bytes input")

    return True


def test_parse_tpex_json_string():
    """Test TPEx parsing with JSON string input."""
    print("\nTEST 4: parse_tpex with JSON string input...")

    tpex_data = {
        "date": "20240117",
        "tables": [
            {
                "data": [
                    ["5511", "德淵", "20.60", "+0.10", "20.50", "20.75", "20.45", "20.58", "1,500,000"],
                ]
            }
        ]
    }

    # Pass as JSON string instead of dict
    json_string = json.dumps(tpex_data)
    result = parse_tpex(json_string)

    assert len(result) == 1, f"Expected 1 row, got {len(result)}"
    assert result[0]["symbol"] == "5511", f"Expected symbol 5511, got {result[0]['symbol']}"
    assert result[0]["date"] == dt.date(2024, 1, 17), f"Expected date 2024-01-17, got {result[0]['date']}"
    print(f"  ✓ Correctly parsed JSON string input")

    return True


def test_parse_twse_non_trading_day():
    """Test TWSE parsing on non-trading day (no tables) returns empty list."""
    print("\nTEST 5: parse_twse handles non-trading day (empty tables)...")

    # Non-trading day response (no tables)
    non_trading_fixture = {
        "date": "20240213",  # Could be a holiday
        "stat": "查詢日期非交易日",
    }

    result = parse_twse(non_trading_fixture)

    assert len(result) == 0, f"Expected 0 rows for non-trading day, got {len(result)}"
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    print(f"  ✓ Non-trading day returns empty list")

    return True


def test_parse_invalid_json():
    """Test both parse functions handle invalid JSON gracefully."""
    print("\nTEST 6: Both parse functions handle invalid input gracefully...")

    # Invalid JSON string
    result_twse = parse_twse("not valid json")
    assert result_twse == [], f"Expected empty list for invalid JSON in TWSE, got {result_twse}"

    result_tpex = parse_tpex("not valid json")
    assert result_tpex == [], f"Expected empty list for invalid JSON in TPEx, got {result_tpex}"

    # None input
    result_twse = parse_twse(None)
    assert result_twse == [], f"Expected empty list for None input in TWSE, got {result_twse}"

    result_tpex = parse_tpex(None)
    assert result_tpex == [], f"Expected empty list for None input in TPEx, got {result_tpex}"

    print(f"  ✓ Both parse functions handle invalid/None input gracefully")

    return True


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_parse_twse,
        test_parse_tpex,
        test_parse_twse_json_bytes,
        test_parse_tpex_json_string,
        test_parse_twse_non_trading_day,
        test_parse_invalid_json,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  ✗ Assertion failed: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
