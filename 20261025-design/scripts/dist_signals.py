"""#277 design: per-instrument unmet conditions and nearness from stored signals (read-only)."""
import sqlite3, json, sys
from collections import Counter, defaultdict
db, day, actions_json = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
CAT = {"close_not_above_prior_20_day_high": "price", "volume_ratio_below_1_20": "volume",
       "ma20_not_above_ma60": "trend", "close_below_ma60": "trend",
       "close_outside_ma20_support_zone": "zone", "pullback_volume_ratio_outside_range": "volume",
       "group_relative_strength_not_positive": "group", "institutional_flow_materially_adverse": "inst",
       "margin_financing_increase_abnormal": "margin"}
rows = c.execute("""select s.instrument_id, v.name, s.status, s.data_quality, s.rule_evidence_json, i.instrument_type, i.etf_category,
   b.close, b.volume, i.symbol, i.exchange
 from signals s join strategy_versions v on v.id=s.strategy_version_id join instruments i on i.id=s.instrument_id
 left join market_bars b on b.instrument_id=s.instrument_id and b.trading_date=s.signal_date
 where s.signal_date=? and i.status='active' and v.name in ('breakout_v1','pullback_v1')""", (day,)).fetchall()
cands = {r[0]: r[1] for r in c.execute("select instrument_id, rank from daily_candidates where trading_date=?", (day,))}
per = defaultdict(dict)
for iid, name, st, dq, ev, typ, cat, close, vol, sym, ex in rows:
    ev = json.loads(ev) if ev else {}
    key = "breakout" if name == "breakout_v1" else "pullback"
    reasons = (ev.get(key) or {}).get("reasons") or []
    unmet = sorted({CAT.get(r, "other:" + r) for r in reasons})
    inp = ev.get("inputs") or {}
    m = {"status": st, "dq": dq, "unmet": unmet, "type": typ, "cat": cat, "sym": sym, "ex": ex}
    highs, vols = inp.get("prior_20_highs") or [], inp.get("prior_20_volumes") or []
    if close and highs: m["bo_gap"] = max(highs) / close - 1
    if vol is not None and vols: m["vr"] = vol / (sum(vols) / len(vols)) if sum(vols) else None
    ma20 = inp.get("ma20")
    if close and ma20:
        lo, hi = 0.97 * ma20, 1.02 * ma20
        m["pb_gap"] = 0.0 if lo <= close <= hi else (close / hi - 1 if close > hi else close / lo - 1)
    per[iid][name] = m
print("instruments with signals", len(per))
state = Counter()
near = Counter(); unmet_n = Counter(); fixable = Counter(); combos = Counter()
gaps_bo, gaps_pb = [], []
near_list = []
for iid, d in per.items():
    sts = {k: v["status"] for k, v in d.items()}
    typ = next(iter(d.values()))["type"]
    if "conditional" in sts.values():
        state["conditional", typ, "candidate" if iid in cands else "not_candidate"] += 1; continue
    obs = {k: v for k, v in d.items() if v["status"] == "observation" and v["dq"] == "complete"}
    if not obs:
        state["no_complete_observation", typ] += 1; continue
    state["observation", typ] += 1
    best = min(len(v["unmet"]) for v in obs.values())
    unmet_n[best, typ] += 1
    for k, v in obs.items():
        combos[k, tuple(v["unmet"])] += 1
    # "near": some strategy whose only unmet are price/volume/zone (next-session reversible) with small gap
    for k, v in obs.items():
        u = set(v["unmet"])
        if u and u <= {"price", "volume", "zone"}:
            fixable[k, typ] += 1
            if k == "breakout_v1" and "bo_gap" in v: gaps_bo.append((v["bo_gap"], typ))
            if k == "pullback_v1" and "pb_gap" in v: gaps_pb.append((v["pb_gap"], typ))
print("state", sorted(state.items()))
print("min unmet count among complete observation strategies", sorted(unmet_n.items()))
print("only price/volume/zone unmet (per strategy)", sorted(fixable.items()))
def hist(vals, edges):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        out.append((f"{lo:+.0%}..{hi:+.0%}", sum(lo <= g < hi for g in vals)))
    return out
print("breakout gap to prior-20 high (fixable, stock only)", hist([g for g, t in gaps_bo if t != "etf"], [-1, 0.0001, 0.02, 0.05, 0.1, 10]))
print("pullback zone gap (fixable, stock only)", hist([g for g, t in gaps_pb if t != "etf"], [-10, -0.05, -0.02, -0.0001, 0.0001, 0.02, 0.05, 10]))
print("top combos", combos.most_common(12))
# near rule A: fixable & (breakout gap<=5%  or pullback |gap|<=3%), stocks
nearA = set(); nearB = set()
for iid, d in per.items():
    if "conditional" in {v["status"] for v in d.values()}: continue
    for k, v in d.items():
        if v["status"] != "observation" or v["dq"] != "complete": continue
        u = set(v["unmet"])
        if not (u and u <= {"price", "volume", "zone"}): continue
        g = v.get("bo_gap") if k == "breakout_v1" else v.get("pb_gap")
        if g is None: continue
        if (k == "breakout_v1" and g <= 0.05) or (k == "pullback_v1" and abs(g) <= 0.03):
            nearA.add((iid, v["type"]))
        if (k == "breakout_v1" and g <= 0.10) or (k == "pullback_v1" and abs(g) <= 0.05):
            nearB.add((iid, v["type"]))
print("near A (bo<=5%, pb<=3%) by type", Counter(t for _, t in nearA))
print("near B (bo<=10%, pb<=5%) by type", Counter(t for _, t in nearB))
print("candidates", len(cands))
