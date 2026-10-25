"""#277 design: action-center distribution on a read-only copy (no product code change)."""
import os, sys, json, time
from collections import Counter
sys.path.insert(0, sys.argv[1])  # worktree backend/
from app.db import SessionLocal
from app.decision import latest_official_as_of, prioritized_instrument_ids, build_action_summaries, position_holding_ids
from app.models import Instrument

db = SessionLocal()
run, as_of = latest_official_as_of(db)
print("as_of", as_of, "run", run.id if run else None)
t = time.time()
ids = prioritized_instrument_ids(db, as_of)
print("prioritized ids", len(ids), f"{time.time()-t:.1f}s")
t = time.time()
rows = build_action_summaries(db, as_of, instrument_ids=ids)
print("summaries", len(rows), f"{time.time()-t:.1f}s")
inst = {i.id: i for i in db.query(Instrument).filter(Instrument.id.in_(ids))}
out = []
for r in rows:
    i = inst[r["instrument"]["id"]]
    out.append({
        "id": i.id, "exchange": i.exchange, "symbol": i.symbol, "type": i.instrument_type,
        "etf_category": i.etf_category, "state": r["action_state"], "priority": r.get("priority"),
        "held": r.get("held"), "watch": r.get("watchlisted"), "events": len(r.get("event_ids") or []),
        "label": r.get("display_action"), "instruction": r.get("display_instruction"),
        "primary_reason": (r.get("primary_reason") or {}).get("label"),
        "reasons": r.get("display_reasons"),
    })
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
c = Counter((o["state"], o["type"]) for o in out)
for k, v in sorted(c.items()): print(k, v)
print("by state", Counter(o["state"] for o in out))
print("instruction", Counter(o["instruction"] for o in out).most_common(6))
print("primary_reason", Counter(o["primary_reason"] for o in out).most_common(6))
# first page order
print("first 25:", [(o["symbol"], o["state"]) for o in out[:25]])
