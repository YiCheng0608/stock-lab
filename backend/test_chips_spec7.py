#!/usr/bin/env python3
"""Test spec-7: Chips adapter parsing (parse_twse_institutional, parse_tpex_institutional,
parse_twse_margin, parse_tpex_margin, parse_twse_lending, parse_tpex_lending) for TWSE-listed
and TPEx-OTC markets.

Tests that each of the 6 parse functions correctly:
1. Parse fixed sample responses for their respective markets and chip categories
2. Output normalized chip rows with correct field names, types, and values
3. Set market field correctly ("listed" for TWSE, "otc" for TPEx)
4. Extract numeric values and convert units correctly (lot sizes to shares)
"""

import sys
import json
import datetime as dt
from pathlib import Path

# Add app module to path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

from app.adapters.chips import (
    parse_twse_institutional,
    parse_tpex_institutional,
    parse_twse_margin,
    parse_tpex_margin,
    parse_twse_lending,
    parse_tpex_lending,
)


def test_parse_twse_institutional():
    """Test TWSE (上市) institutional net buy-sell parsing with realistic fixture."""
    print("TEST 1: parse_twse_institutional with TWSE-listed market fixture...")

    # Realistic TWSE T86 (三大法人買賣超) response fixture
    # Records need at least 12 elements: [symbol, ..., foreign_net(4), ..., investment_trust_net(10), dealer_net(11), ...]
    twse_fixture = {
        "date": "20240115",  # 2024-01-15
        "data": [
            # [symbol, col1, col2, col3, foreign_net(4), col5, col6, col7, col8, col9, investment_trust_net(10), dealer_net(11)]
            ["2330", "台積電", "123", "456", "50,000", "1,000", "2,000", "3,000", "4,000", "5,000", "20,000", "15,000"],
            ["3008", "聯發科", "789", "012", "30,000", "500", "1,000", "1,500", "2,000", "2,500", "10,000", "8,000"],
            ["2450", "聯電", "345", "678", "-", "-", "-", "-", "-", "-", "-", "-"],  # All dashes, should be skipped
        ]
    }

    result = parse_twse_institutional(twse_fixture)

    # Verify we got 2 rows (third row with dashes should be skipped)
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (台積電)
    row1 = result[0]
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["foreign_net"], int), f"Expected foreign_net to be int, got {type(row1['foreign_net'])}"
    assert row1["foreign_net"] == 50000, f"Expected foreign_net 50000, got {row1['foreign_net']}"
    assert row1["investment_trust_net"] == 20000, f"Expected investment_trust_net 20000, got {row1['investment_trust_net']}"
    assert row1["dealer_net"] == 15000, f"Expected dealer_net 15000, got {row1['dealer_net']}"
    print(f"  ✓ Row 1 (2330) has correct fields, types, and values")

    # Check second row (聯發科)
    row2 = result[1]
    assert row2["symbol"] == "3008", f"Expected symbol 3008, got {row2['symbol']}"
    assert row2["market"] == "listed", f"Expected market 'listed', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["foreign_net"] == 30000, f"Expected foreign_net 30000, got {row2['foreign_net']}"
    assert row2["investment_trust_net"] == 10000, f"Expected investment_trust_net 10000, got {row2['investment_trust_net']}"
    assert row2["dealer_net"] == 8000, f"Expected dealer_net 8000, got {row2['dealer_net']}"
    print(f"  ✓ Row 2 (3008) has correct fields, types, and values")

    return True


def test_parse_tpex_institutional():
    """Test TPEx (上櫃) institutional net buy-sell parsing with realistic fixture."""
    print("\nTEST 2: parse_tpex_institutional with TPEx-OTC market fixture...")

    # Realistic TPEx institutional daily trade response fixture
    # Records need at least 23 elements: [symbol, ..., foreign_net(4), ..., investment_trust_net(13), ..., dealer_net(22)]
    tpex_fixture = {
        "date": "20240115",
        "tables": [
            {
                "date": "20240115",
                "title": "三大法人買賣明細",
                "data": [
                    ["4956", "光磊", "111", "222", "25,000", "333", "444", "555", "666", "777", "888", "999", "aaa", "12,000", "bbb", "ccc", "ddd", "eee", "fff", "ggg", "hhh", "iii", "8,000"],
                    ["5264", "宜鼎", "333", "444", "15,000", "555", "666", "777", "888", "999", "aaa", "bbb", "ccc", "7,000", "ddd", "eee", "fff", "ggg", "hhh", "iii", "jjj", "kkk", "5,000"],
                    ["5555", "測試股", "555", "666", "-", "777", "888", "999", "aaa", "bbb", "ccc", "ddd", "eee", "-", "fff", "ggg", "hhh", "iii", "jjj", "kkk", "lll", "mmm", "-"],  # Missing key values
                ]
            }
        ]
    }

    result = parse_tpex_institutional(tpex_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (光磊)
    row1 = result[0]
    assert row1["symbol"] == "4956", f"Expected symbol 4956, got {row1['symbol']}"
    assert row1["market"] == "otc", f"Expected market 'otc', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["foreign_net"], int), f"Expected foreign_net to be int, got {type(row1['foreign_net'])}"
    assert row1["foreign_net"] == 25000, f"Expected foreign_net 25000, got {row1['foreign_net']}"
    assert row1["investment_trust_net"] == 12000, f"Expected investment_trust_net 12000, got {row1['investment_trust_net']}"
    assert row1["dealer_net"] == 8000, f"Expected dealer_net 8000, got {row1['dealer_net']}"
    print(f"  ✓ Row 1 (4956) has correct fields, types, and values")

    # Check second row (宜鼎)
    row2 = result[1]
    assert row2["symbol"] == "5264", f"Expected symbol 5264, got {row2['symbol']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["foreign_net"] == 15000, f"Expected foreign_net 15000, got {row2['foreign_net']}"
    assert row2["investment_trust_net"] == 7000, f"Expected investment_trust_net 7000, got {row2['investment_trust_net']}"
    assert row2["dealer_net"] == 5000, f"Expected dealer_net 5000, got {row2['dealer_net']}"
    print(f"  ✓ Row 2 (5264) has correct fields, types, and values")

    return True


def test_parse_twse_margin():
    """Test TWSE (上市) margin trading balance parsing with lot-to-shares conversion."""
    print("\nTEST 3: parse_twse_margin with TWSE-listed market fixture (lot → shares)...")

    # Realistic TWSE MI_MARGN (融資融券彙總) response fixture
    # Records need at least 13 elements: [symbol, ..., margin_balance(6, in lots), ..., short_balance(12, in lots)]
    twse_fixture = {
        "date": "20240115",
        "tables": [
            {
                "title": "融資融券彙總",
                "date": "20240115",
                "data": [
                    ["2330", "台積電", "123", "456", "789", "012", "100", "345", "678", "901", "234", "567", "50"],  # margin 100 lots → 100,000 shares; short 50 lots → 50,000 shares
                    ["3008", "聯發科", "789", "012", "345", "678", "75", "901", "234", "567", "890", "123", "30"],  # margin 75 lots; short 30 lots
                    ["2450", "聯電", "345", "678", "901", "234", "-", "567", "890", "123", "456", "789", "-"],  # Dashes, should be skipped
                ]
            }
        ]
    }

    result = parse_twse_margin(twse_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (台積電)
    row1 = result[0]
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["margin_balance"], int), f"Expected margin_balance to be int, got {type(row1['margin_balance'])}"
    assert row1["margin_balance"] == 100000, f"Expected margin_balance 100000 (100 lots * 1000), got {row1['margin_balance']}"
    assert row1["short_balance"] == 50000, f"Expected short_balance 50000 (50 lots * 1000), got {row1['short_balance']}"
    print(f"  ✓ Row 1 (2330) has correct fields, types, and values (lots correctly converted to shares)")

    # Check second row (聯發科)
    row2 = result[1]
    assert row2["symbol"] == "3008", f"Expected symbol 3008, got {row2['symbol']}"
    assert row2["market"] == "listed", f"Expected market 'listed', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["margin_balance"] == 75000, f"Expected margin_balance 75000 (75 lots * 1000), got {row2['margin_balance']}"
    assert row2["short_balance"] == 30000, f"Expected short_balance 30000 (30 lots * 1000), got {row2['short_balance']}"
    print(f"  ✓ Row 2 (3008) has correct fields, types, and values")

    return True


def test_parse_tpex_margin():
    """Test TPEx (上櫃) margin trading balance parsing with lot-to-shares conversion."""
    print("\nTEST 4: parse_tpex_margin with TPEx-OTC market fixture (lot → shares)...")

    # Realistic TPEx margin/balance response fixture
    # Records need at least 15 elements: [symbol, ..., margin_balance(6, in lots), ..., short_balance(14, in lots)]
    tpex_fixture = {
        "date": "20240115",
        "tables": [
            {
                "date": "20240115",
                "data": [
                    ["4956", "光磊", "111", "222", "333", "444", "80", "555", "666", "777", "888", "999", "aaa", "bbb", "40"],  # margin 80 lots; short 40 lots
                    ["5264", "宜鼎", "555", "666", "777", "888", "60", "999", "aaa", "bbb", "ccc", "ddd", "eee", "fff", "25"],  # margin 60 lots; short 25 lots
                    ["5555", "測試股", "999", "aaa", "bbb", "ccc", "-", "ddd", "eee", "fff", "ggg", "hhh", "iii", "jjj", "-"],  # Dashes
                ]
            }
        ]
    }

    result = parse_tpex_margin(tpex_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (光磊)
    row1 = result[0]
    assert row1["symbol"] == "4956", f"Expected symbol 4956, got {row1['symbol']}"
    assert row1["market"] == "otc", f"Expected market 'otc', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["margin_balance"], int), f"Expected margin_balance to be int, got {type(row1['margin_balance'])}"
    assert row1["margin_balance"] == 80000, f"Expected margin_balance 80000 (80 lots * 1000), got {row1['margin_balance']}"
    assert row1["short_balance"] == 40000, f"Expected short_balance 40000 (40 lots * 1000), got {row1['short_balance']}"
    print(f"  ✓ Row 1 (4956) has correct fields, types, and values (lots correctly converted to shares)")

    # Check second row (宜鼎)
    row2 = result[1]
    assert row2["symbol"] == "5264", f"Expected symbol 5264, got {row2['symbol']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["margin_balance"] == 60000, f"Expected margin_balance 60000 (60 lots * 1000), got {row2['margin_balance']}"
    assert row2["short_balance"] == 25000, f"Expected short_balance 25000 (25 lots * 1000), got {row2['short_balance']}"
    print(f"  ✓ Row 2 (5264) has correct fields, types, and values")

    return True


def test_parse_twse_lending():
    """Test TWSE (上市) securities lending balance parsing (already in shares, no conversion)."""
    print("\nTEST 5: parse_twse_lending with TWSE-listed market fixture (shares, no conversion)...")

    # Realistic TWSE TWT93U (信用額度總量管制餘額) response fixture
    # Records need at least 13 elements: [symbol, ..., securities_lending_balance(12, already in shares)]
    twse_fixture = {
        "date": "20240115",
        "data": [
            ["2330", "台積電", "123", "456", "789", "012", "345", "678", "901", "234", "567", "890", "1,000,000"],  # lending 1,000,000 shares (already shares, not lots)
            ["3008", "聯發科", "789", "012", "345", "678", "901", "234", "567", "890", "123", "456", "500,000"],  # lending 500,000 shares
            ["2450", "聯電", "345", "678", "901", "234", "567", "890", "123", "456", "789", "012", "-"],  # Dash, should be skipped
        ]
    }

    result = parse_twse_lending(twse_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (台積電)
    row1 = result[0]
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["securities_lending_balance"], int), f"Expected securities_lending_balance to be int, got {type(row1['securities_lending_balance'])}"
    assert row1["securities_lending_balance"] == 1000000, f"Expected securities_lending_balance 1000000, got {row1['securities_lending_balance']}"
    print(f"  ✓ Row 1 (2330) has correct fields, types, and values (no lot conversion)")

    # Check second row (聯發科)
    row2 = result[1]
    assert row2["symbol"] == "3008", f"Expected symbol 3008, got {row2['symbol']}"
    assert row2["market"] == "listed", f"Expected market 'listed', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["securities_lending_balance"] == 500000, f"Expected securities_lending_balance 500000, got {row2['securities_lending_balance']}"
    print(f"  ✓ Row 2 (3008) has correct fields, types, and values")

    return True


def test_parse_tpex_lending():
    """Test TPEx (上櫃) securities lending balance parsing (already in shares, no conversion)."""
    print("\nTEST 6: parse_tpex_lending with TPEx-OTC market fixture (shares, no conversion)...")

    # Realistic TPEx margin/sbl (securities lending balance) response fixture
    # Records need at least 13 elements: [symbol, ..., securities_lending_balance(12, already in shares)]
    tpex_fixture = {
        "date": "20240115",
        "tables": [
            {
                "date": "20240115",
                "data": [
                    ["4956", "光磊", "111", "222", "333", "444", "555", "666", "777", "888", "999", "aaa", "600,000"],  # lending 600,000 shares (already shares)
                    ["5264", "宜鼎", "555", "666", "777", "888", "999", "aaa", "bbb", "ccc", "ddd", "eee", "300,000"],  # lending 300,000 shares
                    ["5555", "測試股", "999", "aaa", "bbb", "ccc", "ddd", "eee", "fff", "ggg", "hhh", "iii", "-"],  # Dash
                ]
            }
        ]
    }

    result = parse_tpex_lending(tpex_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (光磊)
    row1 = result[0]
    assert row1["symbol"] == "4956", f"Expected symbol 4956, got {row1['symbol']}"
    assert row1["market"] == "otc", f"Expected market 'otc', got {row1['market']}"
    assert row1["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row1['date']}"
    assert isinstance(row1["securities_lending_balance"], int), f"Expected securities_lending_balance to be int, got {type(row1['securities_lending_balance'])}"
    assert row1["securities_lending_balance"] == 600000, f"Expected securities_lending_balance 600000, got {row1['securities_lending_balance']}"
    print(f"  ✓ Row 1 (4956) has correct fields, types, and values (no lot conversion)")

    # Check second row (宜鼎)
    row2 = result[1]
    assert row2["symbol"] == "5264", f"Expected symbol 5264, got {row2['symbol']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["date"] == dt.date(2024, 1, 15), f"Expected date 2024-01-15, got {row2['date']}"
    assert row2["securities_lending_balance"] == 300000, f"Expected securities_lending_balance 300000, got {row2['securities_lending_balance']}"
    print(f"  ✓ Row 2 (5264) has correct fields, types, and values")

    return True


def test_all_parse_functions_invalid_input():
    """Test all 6 parse functions handle invalid input gracefully."""
    print("\nTEST 7: All parse functions handle invalid/None input gracefully...")

    # None input
    assert parse_twse_institutional(None) == [], "parse_twse_institutional should return [] for None"
    assert parse_tpex_institutional(None) == [], "parse_tpex_institutional should return [] for None"
    assert parse_twse_margin(None) == [], "parse_twse_margin should return [] for None"
    assert parse_tpex_margin(None) == [], "parse_tpex_margin should return [] for None"
    assert parse_twse_lending(None) == [], "parse_twse_lending should return [] for None"
    assert parse_tpex_lending(None) == [], "parse_tpex_lending should return [] for None"

    # Non-dict input
    assert parse_twse_institutional("not a dict") == [], "parse_twse_institutional should return [] for string"
    assert parse_tpex_institutional("not a dict") == [], "parse_tpex_institutional should return [] for string"
    assert parse_twse_margin("not a dict") == [], "parse_twse_margin should return [] for string"
    assert parse_tpex_margin("not a dict") == [], "parse_tpex_margin should return [] for string"
    assert parse_twse_lending("not a dict") == [], "parse_twse_lending should return [] for string"
    assert parse_tpex_lending("not a dict") == [], "parse_tpex_lending should return [] for string"

    # Empty dict input
    assert parse_twse_institutional({}) == [], "parse_twse_institutional should return [] for empty dict"
    assert parse_tpex_institutional({}) == [], "parse_tpex_institutional should return [] for empty dict"
    assert parse_twse_margin({}) == [], "parse_twse_margin should return [] for empty dict"
    assert parse_tpex_margin({}) == [], "parse_tpex_margin should return [] for empty dict"
    assert parse_twse_lending({}) == [], "parse_twse_lending should return [] for empty dict"
    assert parse_tpex_lending({}) == [], "parse_tpex_lending should return [] for empty dict"

    print(f"  ✓ All 6 parse functions handle invalid/None input gracefully")

    return True


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_parse_twse_institutional,
        test_parse_tpex_institutional,
        test_parse_twse_margin,
        test_parse_tpex_margin,
        test_parse_twse_lending,
        test_parse_tpex_lending,
        test_all_parse_functions_invalid_input,
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
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
