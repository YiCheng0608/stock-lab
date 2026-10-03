import pytest

from app.units import LOT_SIZE, share_quantity_dict, shares_from_position_quantity


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"shares": 1000}, 1000),
        ({"shares": 1500}, 1500),
        ({"shares": 999}, 999),
        ({"unit": "lot", "quantity": 1}, LOT_SIZE),
        ({"unit": "odd_lot", "quantity": 999}, 999),
        ({"quantity_lots": 2}, 2000),
        ({"odd_lot_shares": 999}, 999),
        ({"shares": "9007199254740993"}, 9007199254740993),
        ({"unit": "odd_lot", "quantity": "9223372036854775807"}, 9223372036854775807),
        ({"quantity_lots": "9223372036854775"}, 9223372036854775000),
        ({"odd_lot_shares": "1"}, 1),
    ],
)
def test_position_quantity_converts_to_total_shares(kwargs, expected):
    assert shares_from_position_quantity(**kwargs) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shares": 0},
        {"shares": -1},
        {"shares": 1.5},
        {"shares": True},
        {"shares": "01"},
        {"shares": "1\n"},
        {"shares": "9223372036854775808"},
        {"shares": 9007199254740992},
        {"quantity_lots": "9223372036854776"},
        {"unit": "lot", "quantity": 0},
        {"unit": "lot", "quantity": -1},
        {"unit": "lot", "quantity": 1.5},
        {"unit": "unknown", "quantity": 1},
        {"shares": 1000, "unit": "lot"},
        {"unit": "lot", "quantity": 1, "odd_lot_shares": 1},
        {},
    ],
)
def test_position_quantity_rejects_ambiguous_or_non_positive_values(kwargs):
    with pytest.raises(ValueError):
        shares_from_position_quantity(**kwargs)


def test_share_quantity_display_keeps_lots_and_remainder_explicit():
    assert share_quantity_dict(1000)["display"] == "1 張"
    assert share_quantity_dict(1500)["display"] == "1 張 500 股"
    assert share_quantity_dict(999)["display"] == "999 股（零股）"
