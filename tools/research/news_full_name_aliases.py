"""Build backend/data/news/full_name_aliases.json from stored company masters (#451).

A listed stock's two-character short name is often the start of another listed
company's full name (聯華 1229 and 聯華電子, the full name of 2303 聯電).  The
news rule reads such a full name as an alias of its own company, so 聯華電子 is
2303 and never 1229 聯華 (NEWS_SPEC §2 規則關聯).

Reads a stock.db copy read-only and the latest stored TWSE ``t187ap03_L`` and
TPEx ``mopsfin_t187ap03_O`` captures; no network.  ``--raw-root`` maps the
stored ``/data/raw`` prefix to another directory when the raw files live
elsewhere.  Run it again after a master change and commit the file.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

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
LISTED = ("active", "dormant")
_MARKER = re.compile(r"\*?(?:-(?:KY創|KY|DR|創))?\*?$")
_LEGAL = re.compile(r"(股份有限公司|有限公司)(\(.*\))?$")
_CJK = re.compile(r"[一-鿿]")


def _base(name: str) -> str:
    return _MARKER.sub("", name.strip()).strip()


def build(db: Path, raw_root: str | None) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    listed = {
        (exchange, symbol): _base(name)
        for exchange, symbol, name in conn.execute(
            "SELECT exchange, symbol, name FROM instruments "
            "WHERE instrument_type IN ('stock', 'ipo') AND status IN (?, ?)",
            LISTED,
        )
    }
    owners: dict[str, list[tuple[str, str]]] = {}
    for key, name in listed.items():
        owners.setdefault(name, []).append(key)
    two_char = {
        name
        for name, keys in owners.items()
        if len(name) == 2 and all(_CJK.match(c) for c in name) and len(keys) == 1
    }
    sources, aliases = [], []
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
        if raw_root:
            path = path.replace("/data/raw", raw_root, 1)
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
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
            if len(full) <= 2 or full == short:
                continue
            prefixes = sorted(
                name for name in two_char if full.startswith(name) and name != short
            )
            if prefixes:
                aliases.append(
                    {
                        "exchange": key[0],
                        "symbol": key[1],
                        "short_name": short,
                        "full_name": full,
                        "starts_with": [
                            f"{owners[name][0][0]}:{owners[name][0][1]} {name}"
                            for name in prefixes
                        ],
                    }
                )
    aliases.sort(key=lambda row: (row["exchange"], row["symbol"]))
    return {
        "schema_version": "news-full-name-aliases/v1",
        "rule": (
            "公司名稱（去掉「股份有限公司」）以另一檔上市中普通股的兩字簡稱開頭時，"
            "把全名當成自己公司的別名（NEWS_SPEC §2 規則關聯）"
        ),
        "generated_by": "tools/research/news_full_name_aliases.py",
        "sources": sources,
        "aliases": aliases,
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
    print(json.dumps({"aliases": len(data["aliases"]), "sources": data["sources"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
