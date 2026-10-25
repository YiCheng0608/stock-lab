"""#277 mock data from the read-only copy (10/22). Output JSON for the static wireframe."""
import sqlite3, json, sys
from collections import defaultdict
db, out = sys.argv[1], sys.argv[2]
DAY = "2026-10-22"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); c.row_factory = sqlite3.Row
CAT = {"close_not_above_prior_20_day_high": "price", "volume_ratio_below_1_20": "volume", "ma20_not_above_ma60": "trend", "close_below_ma60": "trend",
       "close_outside_ma20_support_zone": "zone", "pullback_volume_ratio_outside_range": "volume", "group_relative_strength_not_positive": "group",
       "institutional_flow_materially_adverse": "inst", "margin_financing_increase_abnormal": "margin"}
prev = {r["instrument_id"]: r["close"] for r in c.execute("select instrument_id, close from market_bars where trading_date='2026-10-21'")}
bars = {r["instrument_id"]: dict(r) for r in c.execute("select instrument_id, close, volume, turnover, turnover_status from market_bars where trading_date=?", (DAY,))}
inst = {r["id"]: dict(r) for r in c.execute("select id, exchange, symbol, name, instrument_type, etf_category from instruments where status='active'")}
# best group rank per instrument (latest scores on DAY)
grank = {}
gname = {}
for r in c.execute("""select g.id, coalesce(g.display_name_zh, g.name) name, s.rank, s.details_json from group_daily_scores s join theme_groups g on g.id=s.group_id where s.trading_date=? and s.rank is not null""", (DAY,)):
    d = json.loads(r["details_json"]); gname[r["id"]] = (r["name"], d.get("board"), r["rank"])
mem = defaultdict(list)
for r in c.execute("select group_id, instrument_id from group_memberships where valid_from<=? and (valid_to is null or valid_to>=?)", (DAY, DAY)):
    if r["group_id"] in gname: mem[r["instrument_id"]].append(r["group_id"])
def best_group(iid):
    gs = sorted(mem.get(iid, []), key=lambda g: gname[g][2])
    return gname[gs[0]] if gs else None
cands = {r["instrument_id"]: dict(r) for r in c.execute("select instrument_id, rank, strategy, total_score, signal_id from daily_candidates where trading_date=?", (DAY,))}
sig = defaultdict(dict)
for r in c.execute("""select s.*, v.name vname from signals s join strategy_versions v on v.id=s.strategy_version_id where s.signal_date=? and v.name in ('breakout_v1','pullback_v1')""", (DAY,)):
    sig[r["instrument_id"]][r["vname"]] = dict(r)
def lv(s):
    return {k: s[k] for k in ("breakout_price", "reference_entry", "pullback_low", "pullback_high", "invalid_price", "target_1", "target_2")}
def chg(iid):
    b, p = bars.get(iid), prev.get(iid)
    return (b["close"] / p - 1) if b and p else None
rows = {"candidates": [], "other_conditional": [], "near": [], "observe_sample": []}
for iid, d in sig.items():
    if iid not in inst: continue
    i = inst[iid]; b = bars.get(iid) or {}
    base = {"symbol": i["symbol"], "name": i["name"], "exchange": i["exchange"], "type": i["instrument_type"], "close": b.get("close"), "chg": chg(iid), "group": best_group(iid)}
    cond = {k: v for k, v in d.items() if v["status"] == "conditional"}
    if cond:
        k = sorted(cond)[0]
        if iid in cands:
            rows["candidates"].append(base | {"rank": cands[iid]["rank"], "score": cands[iid]["total_score"], "strategy": cands[iid]["strategy"], "levels": lv(sig[iid][cands[iid]["strategy"]])})
        else:
            rows["other_conditional"].append(base | {"strategy": k, "levels": lv(cond[k])})
        continue
    best = None
    for k, s in d.items():
        if s["status"] != "observation" or s["data_quality"] != "complete": continue
        ev = json.loads(s["rule_evidence_json"]); key = "breakout" if k == "breakout_v1" else "pullback"
        u = sorted({CAT.get(x, x) for x in (ev.get(key) or {}).get("reasons") or []})
        inp = ev.get("inputs") or {}; close = b.get("close"); g = None; vr = None
        if close and k == "breakout_v1" and inp.get("prior_20_highs"): g = max(inp["prior_20_highs"]) / close - 1
        if close and k == "pullback_v1" and inp.get("ma20"):
            lo, hi = .97 * inp["ma20"], 1.02 * inp["ma20"]; g = 0 if lo <= close <= hi else (close / hi - 1 if close > hi else close / lo - 1)
        vols = inp.get("prior_20_volumes") or []
        if vols and b.get("volume") is not None and sum(vols): vr = b["volume"] / (sum(vols) / len(vols))
        cand = {"strategy": k, "unmet": u, "gap": g, "vr": vr, "n": len(u)}
        near = bool(u) and set(u) <= {"price", "volume", "zone"} and g is not None and (g <= .03 if k == "breakout_v1" else abs(g) <= .02)
        cand["near"] = near
        sk = (not near, len(u), abs(g) if g is not None else 9)
        if best is None or sk < best[0]: best = (sk, cand)
    if best:
        o = base | best[1]
        (rows["near"] if best[1]["near"] else rows["observe_sample"]).append(o)
rows["candidates"].sort(key=lambda x: x["rank"])
rows["other_conditional"].sort(key=lambda x: (x["type"] == "etf", x["group"][2] if x["group"] else 999, x["symbol"]))
rows["near"].sort(key=lambda x: (x["type"] == "etf", abs(x["gap"]), x["n"], x["symbol"]))
rows["observe_sample"].sort(key=lambda x: (x["type"] == "etf", x["n"], abs(x["gap"]) if x["gap"] is not None else 9, x["symbol"]))
print({k: len(v) for k, v in rows.items()})
print("near stocks", sum(r["type"] != "etf" for r in rows["near"]), "other cond stocks", sum(r["type"] != "etf" for r in rows["other_conditional"]))
# theme members for the steel group
gid = 'official-industry-b597d5609a60578d'
srow = c.execute("select details_json, rank from group_daily_scores where group_id=? and trading_date=?", (gid, DAY)).fetchone()
mr = {m["instrument_id"]: m for m in json.loads(srow["details_json"]).get("member_returns", [])}
members = []
for r in c.execute("select instrument_id, role from group_memberships where group_id=? and valid_from<=? and (valid_to is null or valid_to>=?)", (gid, DAY, DAY)):
    iid = r["instrument_id"]; i = inst.get(iid)
    if not i: continue
    b = bars.get(iid) or {}
    st = None
    if iid in cands: st = f"候選 #{cands[iid]['rank']}"
    elif any(v["status"] == "conditional" for v in sig.get(iid, {}).values()): st = "條件成立"
    members.append({"symbol": i["symbol"], "name": i["name"], "exchange": i["exchange"], "role": r["role"], "close": b.get("close"), "chg": chg(iid),
                    "turnover": b.get("turnover") if b.get("turnover_status") == "available" else None,
                    "x1": (mr.get(iid) or {}).get("excess_return_1d"), "x5": (mr.get(iid) or {}).get("excess_return_5d"), "x20": (mr.get(iid) or {}).get("excess_return_20d"), "status": st})
members.sort(key=lambda m: -(m["turnover"] or -1))
rows["theme"] = {"id": gid, "name": '鋼鐵', "rank": srow["rank"], "members": members}
near_ids = {(r["symbol"]) for r in rows["near"]}
print("steel members", len(members), [m["status"] for m in members if m["status"]])
json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
