"""#953 決定 7074143755: 2017 年 L2 母體 `institutional_flow_20` 缺值的拆解（一次性，不進 repo）。

只讀筆數，不讀報酬。母體與特徵用 round11_research 的同一套（explore_research.load_context、
evidence_lib.universe、explore_research.FEATURES["institutional_flow_20"]）；總數要等於
--coverage-only 的 2017 年那一格（10.5%，以 coverage.json 對帳）。

成因（每個缺值的檔次歸一類，依序判）：
  short       T 以前不足 20 根，或 20 根均量 ≤ 0（_mean_volume 缺）
  weekday_null 窗口裡有平日的 chip_snapshots 列、但三大法人三欄有 null
  no_row      窗口裡有平日沒有 chip_snapshots 列（其他）
  saturday    窗口裡只有週六補班日那幾根缺（#864）
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import evidence_lib as lib  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as fe  # noqa: E402
import round11_research as t  # noqa: E402

DB = Path("/research/stock.db")
OUT = Path("/out")
YEAR = 2017
WINDOW = 20
FIELDS = fe.INSTITUTIONS

started = time.monotonic()
ctx = ex.load_context(DB, t.LOAD_FROM, date(YEAR, 12, 31), OUT / "raw")
loaded = time.monotonic() - started
panel = ctx.market.panel
flow = ex.FEATURES["institutional_flow_20"]

con = lib.connect_read_only(DB)
rows: dict[tuple[int, str], bool] = {}  # (id, date) -> True when all three present
for instrument_id, day, complete in con.execute(
    "select instrument_id, trading_date, "
    "foreign_buy is not null and trust_buy is not null and dealer_buy is not null "
    "from chip_snapshots where trading_date between ? and ?",
    (f"{YEAR - 1}-11-01", f"{YEAR}-12-31"),
):
    key = (instrument_id, day)
    rows[key] = rows.get(key, False) or bool(complete)
by_day = defaultdict(lambda: Counter())  # (date, exchange) -> rows, null rows
for day, exchange, total, nulls in con.execute(
    "select c.trading_date, i.exchange, count(*), "
    "sum(c.foreign_buy is null or c.trust_buy is null or c.dealer_buy is null) "
    "from chip_snapshots c join instruments i on i.id = c.instrument_id "
    "where c.trading_date between ? and ? group by c.trading_date, i.exchange",
    (f"{YEAR}-01-01", f"{YEAR}-12-31"),
):
    by_day[(day, exchange)].update({"rows": total, "nulls": nulls or 0})
con.close()

sessions = [d for d in panel.sessions if d.year == YEAR]
saturdays = [d.isoformat() for d in sessions if d.weekday() == 5]
months = defaultdict(lambda: defaultdict(Counter))  # exchange -> month -> counts
causes = defaultdict(Counter)  # exchange -> cause -> count
null_bar_days = Counter()  # (date, exchange): population windows hit by a weekday null bar
for day in sessions:
    members = lib.universe(panel, day, t.MIN_LOTS)
    for item, at in members:
        exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
        m = months[exchange][f"{day.month:02d}"]
        m["members"] += 1
        if flow(ctx, item, at) is not None:
            continue
        m["missing"] += 1
        if at + 1 < WINDOW or fe._mean_volume(item, at) is None:
            cause = "short"
        else:
            kinds = set()
            for k in range(at + 1 - WINDOW, at + 1):
                if all(item.chips[name][k] == item.chips[name][k] for name in FIELDS):
                    continue
                bar_day = item.dates[k]
                present = rows.get((item.instrument_id, bar_day.isoformat()))
                if bar_day.weekday() == 5:
                    kinds.add("saturday")
                elif present is None:
                    kinds.add("no_row")
                else:
                    kinds.add("weekday_null")
                    null_bar_days[(bar_day.isoformat(), exchange)] += 1
            cause = next(
                (c for c in ("weekday_null", "no_row", "saturday") if c in kinds),
                "other",
            )
        causes[exchange][cause] += 1
        m[cause] += 1

top = sorted(
    (
        {"date": d, "exchange": e, **dict(c)}
        for (d, e), c in by_day.items()
        if date.fromisoformat(d).weekday() < 5 and c["nulls"]
    ),
    key=lambda r: (-r["nulls"], r["date"], r["exchange"]),
)[:10]
body = {
    "year": YEAR,
    "load_seconds": loaded,
    "elapsed_seconds": time.monotonic() - started,
    "sessions": len(sessions),
    "saturday_sessions": saturdays,
    "totals": {
        e: {
            "members": sum(c["members"] for c in ms_.values()),
            "missing": sum(c["missing"] for c in ms_.values()),
        }
        for e, ms_ in months.items()
    },
    "causes": {e: dict(c) for e, c in causes.items()},
    "months": {e: {mo: dict(c) for mo, c in sorted(v.items())} for e, v in months.items()},
    "weekday_null_days_top10": top,
    "population_windows_by_null_bar_day_top10": [
        {"date": d, "exchange": e, "windows": n}
        for (d, e), n in sorted(null_bar_days.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ],
}
(OUT / "l2_missing_2017.json").write_text(
    json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({k: body[k] for k in ("totals", "causes", "saturday_sessions")}, ensure_ascii=False))
