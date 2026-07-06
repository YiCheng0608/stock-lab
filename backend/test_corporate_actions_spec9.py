#!/usr/bin/env python3
"""Test spec-9: Corporate actions adapter (security master, dividend events, capital changes).

Tests that parse_security_master, parse_dividend_events, and parse_capital_changes correctly:
1. Parse fixed sample responses for TWSE-listed (上市) and TPEx-OTC (上櫃) markets
2. Output normalized rows with correct field names, types, and values
3. Set market field correctly ("listed" for TWSE, "otc" for TPEx)
4. Assert market normalization for various codes (sii, 上市, otc, 上櫃, etc.)
5. Verify fallback behavior for unrecognized market codes
"""

import sys
import datetime as dt
from decimal import Decimal
from pathlib import Path

# Add app module to path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

from app.adapters.corporate_actions import (
    parse_security_master,
    parse_dividend_events,
    parse_capital_changes,
)


def test_parse_security_master():
    """Test security master parsing with TWSE and TPEx fixtures."""
    print("TEST 1: parse_security_master with TWSE and TPEx fixtures...")

    # Realistic MOPS security master HTML fixture (simplified table)
    security_master_fixture = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>已發行普通股數</th>
        </tr>
        <tr>
            <td>2330</td>
            <td>台積電</td>
            <td>sii</td>
            <td>2,600,000,000</td>
        </tr>
        <tr>
            <td>4959</td>
            <td>高端疫苗</td>
            <td>otc</td>
            <td>81,600,000</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_security_master(security_master_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (TWSE-listed 2330)
    row1 = result[0]
    assert row1["row_type"] == "security", f"Expected row_type 'security', got {row1['row_type']}"
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["name"] == "台積電", f"Expected name '台積電', got {row1['name']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert isinstance(row1["outstanding_shares"], int), f"Expected outstanding_shares to be int, got {type(row1['outstanding_shares'])}"
    assert row1["outstanding_shares"] == 2600000000, f"Expected outstanding_shares 2600000000, got {row1['outstanding_shares']}"
    assert row1["is_active"] is True, f"Expected is_active True, got {row1['is_active']}"
    print(f"  ✓ Row 1 (2330, TWSE-listed) has correct fields, types, and values")

    # Check second row (TPEx-OTC 4959)
    row2 = result[1]
    assert row2["row_type"] == "security", f"Expected row_type 'security', got {row2['row_type']}"
    assert row2["symbol"] == "4959", f"Expected symbol 4959, got {row2['symbol']}"
    assert row2["name"] == "高端疫苗", f"Expected name '高端疫苗', got {row2['name']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["outstanding_shares"] == 81600000, f"Expected outstanding_shares 81600000, got {row2['outstanding_shares']}"
    assert row2["is_active"] is True, f"Expected is_active True, got {row2['is_active']}"
    print(f"  ✓ Row 2 (4959, TPEx-OTC) has correct fields, types, and values")

    return True


def test_parse_security_master_with_market_variants():
    """Test market normalization: sii, 上市, otc, 上櫃 variants."""
    print("\nTEST 2: parse_security_master with market code variants...")

    # Test various market code representations
    fixture_variants = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>已發行普通股數</th>
        </tr>
        <tr>
            <td>1234</td>
            <td>測試上市1</td>
            <td>sii</td>
            <td>100000000</td>
        </tr>
        <tr>
            <td>1235</td>
            <td>測試上市2</td>
            <td>上市</td>
            <td>100000000</td>
        </tr>
        <tr>
            <td>5001</td>
            <td>測試上櫃1</td>
            <td>otc</td>
            <td>50000000</td>
        </tr>
        <tr>
            <td>5002</td>
            <td>測試上櫃2</td>
            <td>上櫃</td>
            <td>50000000</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_security_master(fixture_variants)

    # All 4 rows should be parsed successfully
    assert len(result) == 4, f"Expected 4 rows with market variants, got {len(result)}"
    print(f"  ✓ Got expected 4 rows (all market variants recognized)")

    # Verify sii normalizes to listed
    assert result[0]["market"] == "listed", f"Expected 'sii' to normalize to 'listed', got {result[0]['market']}"
    assert result[1]["market"] == "listed", f"Expected '上市' to normalize to 'listed', got {result[1]['market']}"
    print(f"  ✓ 'sii' and '上市' both normalize to 'listed'")

    # Verify otc variants normalize to otc
    assert result[2]["market"] == "otc", f"Expected 'otc' to normalize to 'otc', got {result[2]['market']}"
    assert result[3]["market"] == "otc", f"Expected '上櫃' to normalize to 'otc', got {result[3]['market']}"
    print(f"  ✓ 'otc' and '上櫃' both normalize to 'otc'")

    return True


def test_parse_security_master_unrecognized_market():
    """Test that unrecognized market codes result in skipped rows."""
    print("\nTEST 3: parse_security_master with unrecognized market code...")

    fixture_bad_market = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>已發行普通股數</th>
        </tr>
        <tr>
            <td>9999</td>
            <td>垃圾股</td>
            <td>UNKNOWN_MARKET</td>
            <td>100000000</td>
        </tr>
        <tr>
            <td>2330</td>
            <td>台積電</td>
            <td>sii</td>
            <td>2600000000</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_security_master(fixture_bad_market)

    # Only the TWSE row should be parsed; the unrecognized market row should be skipped
    assert len(result) == 1, f"Expected 1 row (second row with valid market), got {len(result)}"
    assert result[0]["symbol"] == "2330", f"Expected only 2330 to pass, got {result[0]['symbol']}"
    print(f"  ✓ Row with unrecognized market code was correctly skipped")

    return True


def test_parse_dividend_events():
    """Test dividend events parsing with cash and stock dividend fixtures."""
    print("\nTEST 4: parse_dividend_events with cash and stock dividend fixtures...")

    dividend_events_fixture = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>除息交易日</th>
            <th>現金股利合計</th>
            <th>除權交易日</th>
            <th>股票股利每股</th>
        </tr>
        <tr>
            <td>2330</td>
            <td>台積電</td>
            <td>sii</td>
            <td>2024/03/15</td>
            <td>1.00</td>
            <td>-</td>
            <td>-</td>
        </tr>
        <tr>
            <td>2454</td>
            <td>聯發科</td>
            <td>sii</td>
            <td>-</td>
            <td>-</td>
            <td>2024/04/10</td>
            <td>0.30</td>
        </tr>
        <tr>
            <td>4959</td>
            <td>高端疫苗</td>
            <td>otc</td>
            <td>2024/06/01</td>
            <td>2.00</td>
            <td>2024/06/01</td>
            <td>0.50</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_dividend_events(dividend_events_fixture)

    # We should get 4 rows: 2330 (cash only), 2454 (stock only), 4959 (cash and stock split into 2 rows)
    assert len(result) == 4, f"Expected 4 rows (1 cash-only, 1 stock-only, 1 both split into 2), got {len(result)}"
    print(f"  ✓ Got expected 4 rows")

    # Check 2330 row (cash dividend only, TWSE-listed)
    row_2330 = result[0]
    assert row_2330["row_type"] == "corporate_action", f"Expected row_type 'corporate_action', got {row_2330['row_type']}"
    assert row_2330["action_type"] == "ex_rights_dividend", f"Expected action_type 'ex_rights_dividend', got {row_2330['action_type']}"
    assert row_2330["symbol"] == "2330", f"Expected symbol 2330, got {row_2330['symbol']}"
    assert row_2330["name"] == "台積電", f"Expected name '台積電', got {row_2330['name']}"
    assert row_2330["market"] == "listed", f"Expected market 'listed', got {row_2330['market']}"
    assert row_2330["ex_rights_date"] == dt.date(2024, 3, 15), f"Expected ex_rights_date 2024-03-15, got {row_2330['ex_rights_date']}"
    assert isinstance(row_2330["cash_dividend_per_share"], Decimal), f"Expected cash_dividend_per_share to be Decimal, got {type(row_2330['cash_dividend_per_share'])}"
    assert row_2330["cash_dividend_per_share"] == Decimal("1.00"), f"Expected cash_dividend_per_share 1.00, got {row_2330['cash_dividend_per_share']}"
    assert row_2330["stock_dividend_per_share"] is None, f"Expected stock_dividend_per_share None, got {row_2330['stock_dividend_per_share']}"
    print(f"  ✓ Row 2330 (cash dividend only) has correct fields and values")

    # Check 2454 row (stock dividend only, TWSE-listed)
    row_2454 = result[1]
    assert row_2454["symbol"] == "2454", f"Expected symbol 2454, got {row_2454['symbol']}"
    assert row_2454["market"] == "listed", f"Expected market 'listed', got {row_2454['market']}"
    assert row_2454["ex_rights_date"] == dt.date(2024, 4, 10), f"Expected ex_rights_date 2024-04-10, got {row_2454['ex_rights_date']}"
    assert row_2454["cash_dividend_per_share"] is None, f"Expected cash_dividend_per_share None, got {row_2454['cash_dividend_per_share']}"
    assert isinstance(row_2454["stock_dividend_per_share"], Decimal), f"Expected stock_dividend_per_share to be Decimal, got {type(row_2454['stock_dividend_per_share'])}"
    assert row_2454["stock_dividend_per_share"] == Decimal("0.30"), f"Expected stock_dividend_per_share 0.30, got {row_2454['stock_dividend_per_share']}"
    print(f"  ✓ Row 2454 (stock dividend only) has correct fields and values")

    # Check 4959 rows (both cash and stock, should split into 2 rows, TPEx-OTC)
    # First should be cash on 2024-06-01
    row_4959_cash = result[2]
    assert row_4959_cash["symbol"] == "4959", f"Expected symbol 4959, got {row_4959_cash['symbol']}"
    assert row_4959_cash["market"] == "otc", f"Expected market 'otc', got {row_4959_cash['market']}"
    assert row_4959_cash["ex_rights_date"] == dt.date(2024, 6, 1), f"Expected ex_rights_date 2024-06-01, got {row_4959_cash['ex_rights_date']}"
    assert row_4959_cash["cash_dividend_per_share"] == Decimal("2.00"), f"Expected cash_dividend_per_share 2.00, got {row_4959_cash['cash_dividend_per_share']}"
    assert row_4959_cash["stock_dividend_per_share"] == Decimal("0.50"), f"Expected stock_dividend_per_share 0.50, got {row_4959_cash['stock_dividend_per_share']}"
    print(f"  ✓ Row 4959 (TPEx-OTC) has correct fields and values")

    return True


def test_parse_capital_changes():
    """Test capital changes parsing with TWSE and TPEx fixtures."""
    print("\nTEST 5: parse_capital_changes with TWSE and TPEx fixtures...")

    capital_changes_fixture = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>異動日期</th>
            <th>增減股數</th>
            <th>變動後股本</th>
        </tr>
        <tr>
            <td>2330</td>
            <td>台積電</td>
            <td>sii</td>
            <td>2024/01/15</td>
            <td>10,000,000</td>
            <td>26,000,000,000</td>
        </tr>
        <tr>
            <td>4959</td>
            <td>高端疫苗</td>
            <td>otc</td>
            <td>2024/02/20</td>
            <td>5,000,000</td>
            <td>81,600,000</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_capital_changes(capital_changes_fixture)

    # Verify we got 2 rows
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"
    print(f"  ✓ Got expected 2 rows")

    # Check first row (TWSE-listed 2330)
    row1 = result[0]
    assert row1["row_type"] == "corporate_action", f"Expected row_type 'corporate_action', got {row1['row_type']}"
    assert row1["action_type"] == "capital_change", f"Expected action_type 'capital_change', got {row1['action_type']}"
    assert row1["symbol"] == "2330", f"Expected symbol 2330, got {row1['symbol']}"
    assert row1["name"] == "台積電", f"Expected name '台積電', got {row1['name']}"
    assert row1["market"] == "listed", f"Expected market 'listed', got {row1['market']}"
    assert row1["ex_rights_date"] == dt.date(2024, 1, 15), f"Expected ex_rights_date 2024-01-15, got {row1['ex_rights_date']}"
    assert row1["capital_change_date"] == dt.date(2024, 1, 15), f"Expected capital_change_date 2024-01-15, got {row1['capital_change_date']}"
    assert isinstance(row1["capital_change_shares"], int), f"Expected capital_change_shares to be int, got {type(row1['capital_change_shares'])}"
    assert row1["capital_change_shares"] == 10000000, f"Expected capital_change_shares 10000000, got {row1['capital_change_shares']}"
    assert row1["capital_after_shares"] == 2600000000, f"Expected capital_after_shares 2600000000, got {row1['capital_after_shares']}"
    assert row1["cash_dividend_per_share"] is None, f"Expected cash_dividend_per_share None, got {row1['cash_dividend_per_share']}"
    assert row1["stock_dividend_per_share"] is None, f"Expected stock_dividend_per_share None, got {row1['stock_dividend_per_share']}"
    print(f"  ✓ Row 1 (2330, TWSE-listed) has correct fields, types, and values")

    # Check second row (TPEx-OTC 4959)
    row2 = result[1]
    assert row2["symbol"] == "4959", f"Expected symbol 4959, got {row2['symbol']}"
    assert row2["name"] == "高端疫苗", f"Expected name '高端疫苗', got {row2['name']}"
    assert row2["market"] == "otc", f"Expected market 'otc', got {row2['market']}"
    assert row2["ex_rights_date"] == dt.date(2024, 2, 20), f"Expected ex_rights_date 2024-02-20, got {row2['ex_rights_date']}"
    assert row2["capital_change_shares"] == 5000000, f"Expected capital_change_shares 5000000, got {row2['capital_change_shares']}"
    assert row2["capital_after_shares"] == 8160000, f"Expected capital_after_shares 8160000 (81600000/10), got {row2['capital_after_shares']}"
    print(f"  ✓ Row 2 (4959, TPEx-OTC) has correct fields, types, and values")

    return True


def test_parse_capital_changes_unrecognized_market():
    """Test that capital change rows with unrecognized markets are skipped."""
    print("\nTEST 6: parse_capital_changes with unrecognized market...")

    fixture_bad_market = """
    <html>
    <body>
    <table>
        <tr>
            <th>公司代號</th>
            <th>公司名稱</th>
            <th>市場別</th>
            <th>異動日期</th>
            <th>增減股數</th>
            <th>變動後股本</th>
        </tr>
        <tr>
            <td>9999</td>
            <td>垃圾股</td>
            <td>UNKNOWN_MARKET</td>
            <td>2024/01/15</td>
            <td>1000000</td>
            <td>10000000</td>
        </tr>
        <tr>
            <td>2330</td>
            <td>台積電</td>
            <td>sii</td>
            <td>2024/01/16</td>
            <td>500000</td>
            <td>26000000000</td>
        </tr>
    </table>
    </body>
    </html>
    """

    result = parse_capital_changes(fixture_bad_market)

    # Only the valid market row should be parsed
    assert len(result) == 1, f"Expected 1 row (only valid market), got {len(result)}"
    assert result[0]["symbol"] == "2330", f"Expected only 2330 to pass, got {result[0]['symbol']}"
    print(f"  ✓ Row with unrecognized market code was correctly skipped")

    return True


if __name__ == "__main__":
    print("=" * 70)
    print("Running spec-9 tests: Corporate Actions (security master, dividends, capital changes)")
    print("=" * 70)

    try:
        test_parse_security_master()
        test_parse_security_master_with_market_variants()
        test_parse_security_master_unrecognized_market()
        test_parse_dividend_events()
        test_parse_capital_changes()
        test_parse_capital_changes_unrecognized_market()

        print("\n" + "=" * 70)
        print("✓ All tests passed!")
        print("=" * 70)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
