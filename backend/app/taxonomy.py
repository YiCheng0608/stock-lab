"""Exchange-aware official market taxonomy.

TWSE and TPEx publish numeric industry codes independently.  The numbers are
not a shared namespace (for example, TWSE 19 is a composite category while
TPEx does not define 19), so product relationships must be normalised with
the source exchange before a market-wide group id is generated.
"""

from __future__ import annotations

import hashlib
from typing import Mapping


# Official ordinary-industry codes: TWSE B.12.00 Appendix 3 plus the
# 2023-05-30 notice (effective 2023-07-03); TPEx V12.14 Appendix 3.
# Shared codes have the same canonical meaning. Market-exclusive codes must
# not leak across exchanges. TPEx 18/34 were removed on 2023-07-03; management
# stock 80 and TDR 91 are not ordinary industry relationships.
INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE: Mapping[str, Mapping[str, str]] = {
    "TWSE": {
        "01": "Cement",
        "02": "Food",
        "03": "Plastic",
        "04": "Textile",
        "05": "Electrical Machinery",
        "06": "Electrical Cable",
        "08": "Glass",
        "09": "Paper",
        "10": "Iron and Steel",
        "11": "Rubber",
        "12": "Automobile",
        "14": "Construction",
        "15": "Shipping",
        "16": "Tourism",
        "17": "Financial",
        "18": "Wholesale and Retail",
        "19": "Composite",
        "20": "Other",
        "21": "Chemical",
        "22": "Biotechnology",
        "23": "Oil, Gas and Electricity",
        "24": "Semiconductor",
        "25": "Computer and Peripherals",
        "26": "Optoelectronics",
        "27": "Communications",
        "28": "Electronic Parts",
        "29": "Electronic Distribution",
        "30": "Information Service",
        "31": "Other Electronics",
        "35": "Green Energy",
        "36": "Digital Cloud",
        "37": "Sports and Leisure",
        "38": "Household",
    },
    "TPEX": {
        "02": "Food",
        "03": "Plastic",
        "04": "Textile",
        "05": "Electrical Machinery",
        "06": "Electrical Cable",
        "08": "Glass",
        "10": "Iron and Steel",
        "11": "Rubber",
        "14": "Construction",
        "15": "Shipping",
        "16": "Tourism",
        "17": "Financial",
        "20": "Other",
        "21": "Chemical",
        "22": "Biotechnology",
        "23": "Oil, Gas and Electricity",
        "24": "Semiconductor",
        "25": "Computer and Peripherals",
        "26": "Optoelectronics",
        "27": "Communications",
        "28": "Electronic Parts",
        "29": "Electronic Distribution",
        "30": "Information Service",
        "31": "Other Electronics",
        "32": "Cultural Innovation",
        "33": "Agriculture Technology",
        "35": "Green Energy",
        "36": "Digital Cloud",
        "37": "Sports and Leisure",
        "38": "Household",
    },
}

INDUSTRY_DISPLAY_ZH: Mapping[str, str] = {
    "Cement": "水泥",
    "Food": "食品",
    "Plastic": "塑膠",
    "Textile": "紡織纖維",
    "Electrical Machinery": "電機機械",
    "Electrical Cable": "電線電纜",
    "Glass": "玻璃陶瓷",
    "Paper": "造紙",
    "Iron and Steel": "鋼鐵",
    "Rubber": "橡膠",
    "Automobile": "汽車",
    "Construction": "建材營造",
    "Shipping": "航運",
    "Tourism": "觀光餐旅",
    "Financial": "金融",
    "Wholesale and Retail": "貿易百貨",
    "Composite": "綜合",
    "Other": "其他",
    "Chemical": "化學",
    "Biotechnology": "生技醫療",
    "Oil, Gas and Electricity": "油電燃氣",
    "Semiconductor": "半導體",
    "Computer and Peripherals": "電腦及週邊",
    "Optoelectronics": "光電",
    "Communications": "通信網路",
    "Electronic Parts": "電子零組件",
    "Electronic Distribution": "電子通路",
    "Information Service": "資訊服務",
    "Other Electronics": "其他電子",
    "Cultural Innovation": "文化創意",
    "Agriculture Technology": "農業科技",
    "Green Energy": "綠能環保",
    "Digital Cloud": "數位雲端",
    "Sports and Leisure": "運動休閒",
    "Household": "居家生活",
}


_CANONICAL_ALIASES = {
    "semi": "Semiconductor",
    "semiconductor": "Semiconductor",
    "electronics": "Other Electronics",
    "finance": "Financial",
    "financial": "Financial",
}


def _exchange_key(exchange: str | None) -> str:
    return str(exchange or "").strip().upper()


def canonical_industry_label(exchange: str | None, value: str | None) -> str | None:
    """Translate one official exchange code into a canonical label.

    Unknown numeric codes intentionally return ``None``.  Passing an English
    canonical label is supported for already-normalised fixture/legacy rows,
    but arbitrary unknown text is not promoted to an official relationship.
    """

    if _exchange_key(exchange) not in INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE:
        return None
    raw = str(value or "").strip()
    if not raw or raw.upper() in {"ETF", "N/A", "-", "NONE"}:
        return None
    code = raw.zfill(2) if raw.isdigit() else None
    if code:
        return INDUSTRY_CODE_TO_CANONICAL_BY_EXCHANGE.get(_exchange_key(exchange), {}).get(code)
    lowered = raw.casefold()
    if raw in INDUSTRY_DISPLAY_ZH:
        return raw
    if lowered in {label.casefold() for label in INDUSTRY_DISPLAY_ZH}:
        return next(label for label in INDUSTRY_DISPLAY_ZH if label.casefold() == lowered)
    return _CANONICAL_ALIASES.get(lowered)


def canonical_group_id(group_type: str, label: str) -> str:
    """Return the market-wide id for a normalised group label."""

    digest = hashlib.sha1(f"{group_type}:{label.lower()}".encode("utf-8")).hexdigest()[:16]
    return f"official-{group_type}-{digest}"
