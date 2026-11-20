"""#865 AC-1: R1、R2 用到的三大法人、融資餘額、融資名單，在探索段依年、依交易所的覆蓋。

唯讀（mode=ro + query_only）。日線用 trade_research 同一條查詢
（research_report.benchmark_bars，含日線排除清單），讀 2012-12-01（起日錨點 2014-12-01
往前 730 天）～2019-12-31。分母是每天的共同口徑母體（stock／ipo、T 日有非停牌日線、
該標的在讀入範圍內往前 20 根日均量 ≥ 1,000 張，同 evidence_lib.universe）。
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, "/app/tools/research")
sys.path.insert(0, "/app/backend")
import research_report as report  # noqa: E402

DB = "/research/stock.db"
START = date(2012, 12, 1)
END = date(2019, 12, 31)
ANCHOR = date(2014, 12, 1)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.execute("pragma query_only=1")

meta = {
    iid: (exchange, symbol)
    for iid, exchange, symbol in con.execute("select id, exchange, symbol from instruments")
}

lists = {}
for exchange, day, members in con.execute(
    "select exchange, trading_date, members_json from margin_lists "
    "where trading_date >= ? and trading_date <= ?",
    (START.isoformat(), END.isoformat()),
):
    lists[(exchange, day)] = frozenset(json.loads(members))

sessions = set()
stats = defaultdict(lambda: defaultdict(int))
signal_stats = defaultdict(lambda: defaultdict(int))
member_days = []  # (iid, iso day) kept per instrument below

FIELDS = ("foreign_buy", "trust_buy", "dealer_buy", "margin_balance")
ALL_CHIPS = (
    "foreign_buy", "trust_buy", "dealer_buy", "margin_balance",
    "short_balance", "borrowed_sell", "day_trade_ratio",
)

per_instrument = []
for iid, bars in report.benchmark_bars(con, START, END):
    days = []
    for k, bar in enumerate(bars):
        sessions.add(bar.trading_date)
        if k + 1 < 20:
            continue
        b = bar
        suspended = b.suspended
        if suspended:
            continue
        lots = sum(x.volume for x in bars[k - 19 : k + 1]) / 20 / 1000
        if lots < 1000:
            continue
        days.append(b.trading_date)
    if days:
        per_instrument.append((iid, days))

all_sessions = sorted(sessions)
first_signal = [d for d in all_sessions if d >= ANCHOR][19]

session_years = defaultdict(int)
list_years = defaultdict(int)
for d in all_sessions:
    session_years[d.year] += 1
    for exchange in ("TWSE", "TPEx"):
        if (exchange, d.isoformat()) in lists:
            list_years[(exchange, d.year)] += 1

for iid, days in per_instrument:
    exchange, symbol = meta[iid]
    chips = {
        row[0]: row[1:]
        for row in con.execute(
            f"select trading_date, {', '.join(ALL_CHIPS)} from chip_snapshots "
            "where instrument_id = ? and trading_date >= ? and trading_date <= ?",
            (iid, START.isoformat(), END.isoformat()),
        )
    }
    for d in days:
        iso = d.isoformat()
        targets = [stats[(d.year, exchange)]]
        if d >= first_signal:
            targets.append(signal_stats[exchange])
        row = chips.get(iso)
        listed = lists.get((exchange, iso))
        for s in targets:
            s["member_days"] += 1
            if row is not None and any(v is not None for v in row):
                s["chip_row"] += 1
            if row is not None and all(v is not None for v in row[:3]):
                s["institutional_all3"] += 1
            for name, v in zip(FIELDS, row[:4] if row else (None,) * 4):
                if v is None:
                    s[f"{name}_null"] += 1
            if row is not None and row[3] == 0:
                s["margin_balance_zero"] += 1
            if listed is None:
                s["no_list_day"] += 1
            elif symbol in listed:
                s["in_list"] += 1

out = {
    "read": [START.isoformat(), END.isoformat()],
    "first_signal_day": first_signal.isoformat(),
    "sessions": dict(session_years),
    "list_sessions": {f"{e}:{y}": n for (e, y), n in list_years.items()},
    "by_year": {f"{y}:{e}": dict(v) for (y, e), v in sorted(stats.items())},
    "signal_period": {e: dict(v) for e, v in signal_stats.items()},
}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
