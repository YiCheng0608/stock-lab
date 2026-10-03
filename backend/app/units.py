"""Explicit Taiwan-share quantity conversions used by portfolio products.

The database keeps the historical ``shares`` column so existing official and
user data remain forward compatible.  This module is deliberately pure: it
does not know about instruments or prices and therefore can be tested without
opening the production database.
"""

from __future__ import annotations

import math
from typing import Any


LOT_SIZE = 1000


def volume_exact_text(value: Any) -> str | None:
    """Encode only a stored nonnegative int64 volume, without float conversion."""
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        return None
    return str(value)


def _strict_positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def shares_from_position_quantity(
    *,
    shares: Any = None,
    unit: str | None = None,
    quantity: Any = None,
    quantity_lots: Any = None,
    odd_lot_shares: Any = None,
) -> int:
    """Normalize one explicit quantity representation to total shares.

    ``shares`` is the legacy input and remains accepted as a strict positive
    integer.  New clients may send ``unit`` + ``quantity`` or one of the
    explicit ``quantity_lots`` / ``odd_lot_shares`` fields.  Mixing
    representations is rejected so a typo cannot silently double a position.
    """

    explicit = [
        shares is not None,
        quantity is not None,
        quantity_lots is not None,
        odd_lot_shares is not None,
    ]
    if sum(explicit) != 1:
        raise ValueError("provide exactly one position quantity representation")

    if shares is not None:
        if unit is not None:
            raise ValueError("unit cannot be used with legacy shares")
        return _strict_positive_integer(shares, "shares")

    if quantity is not None:
        if unit not in {"lot", "odd_lot"}:
            raise ValueError("unit must be lot or odd_lot when quantity is provided")
        normalized = _strict_positive_integer(quantity, "quantity")
        return normalized * LOT_SIZE if unit == "lot" else normalized

    if unit is not None:
        raise ValueError("unit can only be used with quantity")
    if quantity_lots is not None:
        return _strict_positive_integer(quantity_lots, "quantity_lots") * LOT_SIZE
    return _strict_positive_integer(odd_lot_shares, "odd_lot_shares")


def split_shares(shares: Any) -> tuple[int, int]:
    """Return ``(whole_lots, remainder_shares)`` for a stored share count."""

    if isinstance(shares, bool):
        raise ValueError("shares must be finite")
    try:
        number = float(shares)
    except (TypeError, ValueError):
        raise ValueError("shares must be finite") from None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError("shares must be a non-negative integer")
    total = int(number)
    return total // LOT_SIZE, total % LOT_SIZE


def share_quantity_dict(shares: Any) -> dict[str, Any]:
    """Return a stable API/display representation without relabelling shares."""

    lots, remainder = split_shares(shares)
    if lots and remainder:
        unit = "mixed"
    elif lots:
        unit = "lot"
    else:
        unit = "odd_lot"
    if lots and remainder:
        display = f"{lots:,} 張 {remainder:,} 股"
    elif lots:
        display = f"{lots:,} 張"
    else:
        display = f"{remainder:,} 股（零股）"
    return {
        "total_shares": lots * LOT_SIZE + remainder,
        "quantity_lots": lots,
        "odd_lot_shares": remainder,
        "unit": unit,
        "display": display,
    }
