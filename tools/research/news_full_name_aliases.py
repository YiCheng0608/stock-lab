"""Build backend/data/news/full_name_aliases.json from stored company masters (#451, #461).

A listed stock's two-character short name is often the start of another listed
company's full name (聯華 1229 and 聯華電子, the full name of 2303 聯電).  The
news rule reads such a full name as an alias of its own company, so 聯華電子 is
2303 and never 1229 聯華 (NEWS_SPEC §2 規則關聯).  The press often drops the
industry words at the end of the full name (群光電能 for 群光電能科技, 6412 群電;
中鋼碳素 for 中鋼碳素化學, 1723 中碳), so each full name also yields the names
left after taking INDUSTRY_SUFFIXES off its end one at a time, while three or
more characters remain (#461).

A name is left out when it is the stock's own short name, any stock's official
name (or its variants, ``worker.news_batch._name_aliases``), or the name of two
companies.  The two-character names are those the rule reads: listed
(``active``／``dormant``) common stocks whose name without listing markers, or
without a holding-company ending (``worker.news_batch._holding_alias``, as the
matcher reads it: 上緯投控 → 上緯; #475), no other listed stock shares.

Reads a stock.db copy read-only and the latest stored TWSE ``t187ap03_L`` and
TPEx ``mopsfin_t187ap03_O`` captures; no network.  A stored path is resolved by
``app.raw_paths.payload_file``, so it runs in a container with the data volume
mounted read-only at ``/data`` (docs/ops/LOCAL.md 讀 raw 的工具); ``--raw-root``
maps the stored ``/data/raw`` prefix to another directory instead.  Run it again
after a master change and commit the file.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.raw_paths import payload_file  # noqa: E402
from worker.news_batch import (  # noqa: E402
    LISTED_STATUSES,
    STOCK_TYPES,
    _holding_alias,
    _is_two_char_name,
    _name_aliases,
    _NAME_SUFFIX,
)

SCHEMA_VERSION = "news-full-name-aliases/v2"
ENDPOINTS = {
    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L": (
        "TWSE",
        "公司代號",
        "公司簡稱",
        "公司名稱",
        "出表日期",
    ),
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O": (
        "TPEx",
        "SecuritiesCompanyCode",
        "CompanyAbbreviation",
        "CompanyName",
        "Date",
    ),
}
# Industry words at the end of a full name that the press leaves out (#461).
# Taken off one at a time, longest first; the rest must keep three characters.
INDUSTRY_SUFFIXES = (
    "國際",
    "實業",
    "企業",
    "工業",
    "科技",
    "電子",
    "電機",
    "電能",
    "碳素",
    "化學",
    "化工",
    "光電",
    "精密",
    "材料",
    "生技",
    "生物科技",
    "工程",
    "建設",
    "開發",
    "食品",
    "紡織",
    "機械",
    "電腦",
    "資訊",
    "通訊",
    "半導體",
    "投資控股",
    "控股",
    "集團",
)
_LEGAL = re.compile(r"(股份有限公司|有限公司)(\(.*\))?$")


def _base(name: str) -> str:
    return _NAME_SUFFIX.sub("", name.strip()).strip()


def name_forms(full: str) -> list[tuple[str, list[str]]]:
    """FULL and each name left after taking an industry word off its end.

    Each form comes with the words taken off so far: 群光電能科技 gives
    (群光電能科技, []) and (群光電能, [科技]); 群光 is not a form (two characters).
    """

    forms = [(full, [])]
    current, taken = full, []
    suffixes = sorted(INDUSTRY_SUFFIXES, key=len, reverse=True)
    while True:
        for suffix in suffixes:
            if current.endswith(suffix) and len(current) - len(suffix) >= 3:
                current = current[: -len(suffix)]
                taken = [suffix, *taken]
                forms.append((current, taken))
                break
        else:
            return forms


def _resolve(path: str, raw_root: str | None) -> Path:
    if raw_root and path.startswith("/data/raw"):
        return Path(path.replace("/data/raw", raw_root, 1))
    return payload_file(path)


def build(db: Path, raw_root: str | None) -> dict:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=1")
    marks = ",".join("?" for _ in STOCK_TYPES)
    stock_rows = conn.execute(
        "SELECT exchange, symbol, name, status FROM instruments "
        f"WHERE instrument_type IN ({marks}) AND exchange IN ('TWSE', 'TPEx')",
        STOCK_TYPES,
    ).fetchall()
    official = {
        alias for _, _, name, _ in stock_rows for alias in _name_aliases(name or "")
    }
    # Each listed stock's names the matcher reads: the name without listing
    # markers and, as in RelationMatcher, the name without a holding-company
    # ending unless that is another stock's official name (上緯投控 → 上緯; #475).
    listed: dict[tuple[str, str], set[str]] = {}
    for exchange, symbol, name, status in stock_rows:
        if status not in LISTED_STATUSES:
            continue
        names = {_base(name)}
        holding = _holding_alias(name or "")
        if holding and holding not in official:
            names.add(holding)
        listed[(exchange, symbol)] = names
    owners: dict[str, list[tuple[str, str]]] = {}
    for key, names in listed.items():
        for name in names:
            owners.setdefault(name, []).append(key)
    two_char = {
        name
        for name, keys in owners.items()
        if _is_two_char_name(name) and len(keys) == 1
    }
    sources, found = [], []
    for endpoint, (
        exchange,
        code_key,
        short_key,
        full_key,
        date_key,
    ) in ENDPOINTS.items():
        raw_id, path, sha = conn.execute(
            "SELECT id, payload_path, sha256 FROM raw_payloads WHERE endpoint = ? "
            "ORDER BY collected_at DESC, id DESC LIMIT 1",
            (endpoint,),
        ).fetchone()
        rows = json.loads(_resolve(path, raw_root).read_text(encoding="utf-8"))
        sources.append(
            {
                "endpoint": endpoint,
                "raw_payload_id": raw_id,
                "sha256": sha,
                "report_date": rows[0].get(date_key) if rows else None,
            }
        )
        for row in rows:
            key = (exchange, str(row.get(code_key, "")).strip())
            if key not in listed:
                continue
            full = _LEGAL.sub("", str(row.get(full_key, "")).strip())
            short = _base(str(row.get(short_key, "")))
            prefixes = sorted(
                name
                for name in two_char
                if full.startswith(name) and name != short and name not in listed[key]
            )
            if not prefixes:
                continue
            for alias, stripped in name_forms(full):
                if len(alias) <= 2 or alias == short or alias in official:
                    continue
                found.append(
                    {
                        "exchange": key[0],
                        "symbol": key[1],
                        "short_name": short,
                        "full_name": full,
                        "alias": alias,
                        "stripped": stripped,
                        "starts_with": [
                            f"{owners[name][0][0]}:{owners[name][0][1]} {name}"
                            for name in prefixes
                        ],
                    }
                )
    by_alias: dict[str, set[tuple[str, str]]] = {}
    for row in found:
        by_alias.setdefault(row["alias"], set()).add((row["exchange"], row["symbol"]))
    aliases = [row for row in found if len(by_alias[row["alias"]]) == 1]
    shared = sorted(
        {
            row["alias"]: [f"{e}:{s}" for e, s in sorted(by_alias[row["alias"]])]
            for row in found
            if len(by_alias[row["alias"]]) > 1
        }.items()
    )
    aliases.sort(key=lambda row: (row["exchange"], row["symbol"], -len(row["alias"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "rule": (
            "公司名稱（去掉「股份有限公司」）以另一檔上市中普通股的兩字簡稱"
            "（含去掉投控／控股後成為兩字的簡稱）開頭時，"
            "把全名，以及從結尾逐一去掉產業尾詞（INDUSTRY_SUFFIXES）後仍有三字以上的名稱，"
            "當成自己公司的別名；與任一檔的簡稱相同或兩家公司共用的名稱不收"
            "（NEWS_SPEC §2 規則關聯）"
        ),
        "generated_by": "tools/research/news_full_name_aliases.py",
        "industry_suffixes": list(INDUSTRY_SUFFIXES),
        "sources": sources,
        "aliases": aliases,
        "left_out_shared": [{"alias": alias, "stocks": keys} for alias, keys in shared],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db", required=True, type=Path, help="stock.db copy (read only)"
    )
    parser.add_argument("--raw-root", help="directory that replaces /data/raw")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = build(args.db, args.raw_root)
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "aliases": len(data["aliases"]),
                "left_out_shared": len(data["left_out_shared"]),
                "sources": data["sources"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
