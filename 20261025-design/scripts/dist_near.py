import sqlite3, json, sys
from collections import Counter, defaultdict
db, day = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
print("candidates by signal status", c.execute("""select s.status, s.signal_date, count(*) from daily_candidates d join signals s on s.id=d.signal_id where d.trading_date=? group by 1,2""", (day,)).fetchall())
CAT = {"close_not_above_prior_20_day_high": "price", "volume_ratio_below_1_20": "volume", "ma20_not_above_ma60": "trend", "close_below_ma60": "trend",
       "close_outside_ma20_support_zone": "zone", "pullback_volume_ratio_outside_range": "volume", "group_relative_strength_not_positive": "group",
       "institutional_flow_materially_adverse": "inst", "margin_financing_increase_abnormal": "margin"}
rows = c.execute("""select s.instrument_id, v.name, s.status, s.data_quality, s.rule_evidence_json, i.instrument_type, b.close
 from signals s join strategy_versions v on v.id=s.strategy_version_id join instruments i on i.id=s.instrument_id
 left join market_bars b on b.instrument_id=s.instrument_id and b.trading_date=s.signal_date
 where s.signal_date=? and i.status='active' and v.name in ('breakout_v1','pullback_v1')""", (day,)).fetchall()
per = defaultdict(list); typ = {}; cond = set()
for iid, name, st, dq, ev, t, close in rows:
    typ[iid] = t
    if st == "conditional": cond.add(iid)
    if st != "observation" or dq != "complete": continue
    ev = json.loads(ev); k = "breakout" if name == "breakout_v1" else "pullback"
    u = {CAT.get(r, r) for r in (ev.get(k) or {}).get("reasons") or []}
    inp = ev.get("inputs") or {}
    g = None
    if name == "breakout_v1" and close and inp.get("prior_20_highs"): g = max(inp["prior_20_highs"]) / close - 1
    if name == "pullback_v1" and close and inp.get("ma20"):
        lo, hi = .97 * inp["ma20"], 1.02 * inp["ma20"]; g = 0 if lo <= close <= hi else (close / hi - 1 if close > hi else close / lo - 1)
    per[iid].append((name, u, g))
def count(pred):
    s = {i for i, lst in per.items() if i not in cond and any(pred(*x) for x in lst)}
    return Counter(typ[i] for i in s)
opts = {
 "O1 only price/volume/zone unmet (no gap limit)": lambda n,u,g: u and u <= {"price","volume","zone"},
 "O2 O1 + bo<=10% / pb|gap|<=5%": lambda n,u,g: u and u <= {"price","volume","zone"} and g is not None and (g <= .10 if n=="breakout_v1" else abs(g) <= .05),
 "O3 O1 + bo<=5% / pb|gap|<=3%": lambda n,u,g: u and u <= {"price","volume","zone"} and g is not None and (g <= .05 if n=="breakout_v1" else abs(g) <= .03),
 "O4 O1 + bo<=3% / pb|gap|<=2%": lambda n,u,g: u and u <= {"price","volume","zone"} and g is not None and (g <= .03 if n=="breakout_v1" else abs(g) <= .02),
 "O5 exactly one unmet (any)": lambda n,u,g: len(u) == 1,
 "O6 exactly one unmet and it is price/volume/zone": lambda n,u,g: len(u) == 1 and u <= {"price","volume","zone"},
}
for k, f in opts.items(): print(day, k, dict(count(f)))
