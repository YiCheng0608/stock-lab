import json, sys
from collections import Counter
acts = json.load(open(sys.argv[1], encoding="utf-8")); m = json.load(open(sys.argv[2], encoding="utf-8"))
near = {(r["exchange"], r["symbol"]) for r in m["near"]}
cand = {(r["exchange"], r["symbol"]) for r in m["candidates"]}
t = Counter(); watch = Counter()
for a in acts:
    k = (a["exchange"], a["symbol"]); etf = "ETF" if a["type"] == "etf" else "股票（含 IPO）"
    if a["held"] or a["state"] in ("reduce_exit", "hold_observe"): tier = "0 持倉風險"
    elif k in cand: tier = "1 今日候選"
    elif a["state"] in ("conditional_entry", "manual_review", "wait_breakout", "wait_pullback"): tier = "2 其他成立條件"
    elif a["state"] == "no_condition" and k in near: tier = "3 接近成立"
    elif a["state"] == "no_condition": tier = "4 其他觀察"
    else: tier = "5 資料待補"
    t[tier, etf] += 1
    if a["watch"] or a["events"]: watch[tier, "watch" if a["watch"] else "event"] += 1
for k in sorted(t): print(k, t[k])
print("total", sum(t.values()))
print("watch/event", sorted(watch.items()))
