import csv, sqlite3, statistics, math, sys
from collections import defaultdict
c = sqlite3.connect("file:/db/stock.db?mode=ro", uri=True)
kind = dict(c.execute("select id, instrument_type from instruments"))
rows = list(csv.DictReader(open("/in/trades.csv", encoding="utf-8")))
def seg(d): return "exploration" if d <= "2025-12-31" else "validation"
out = defaultdict(list)
for r in rows:
    if not r["E0_net"]:
        continue
    k = "stock_ipo" if kind.get(int(r["instrument_id"])) in ("stock", "ipo") else "etf"
    for s in (seg(r["signal_date"]), "all"):
        out[(r["strategy"], k, s)].append((r["signal_date"], float(r["E0_net"])))
print("strategy|types|segment|n|mean|median|win|days|daily_mean|t")
for key in sorted(out):
    v = out[key]; nets = [x for _, x in v]
    by = defaultdict(list)
    for d, x in v: by[d].append(x)
    daily = [statistics.fmean(x) for x in by.values()]
    sd = statistics.stdev(daily) if len(daily) > 1 else 0
    eff = len(daily) / 20
    t = statistics.fmean(daily) / (sd / math.sqrt(eff)) if sd > 0 and eff >= 2 else None
    print("|".join(map(str, [*key, len(nets), f"{statistics.fmean(nets):.4%}", f"{statistics.median(nets):.4%}",
        f"{sum(x > 0 for x in nets)/len(nets):.1%}", len(daily), f"{statistics.fmean(daily):.4%}", None if t is None else f"{t:.2f}"])))
