"""#260 AC-6: classify the group_daily_scores differences (catalyst events collected after
the day's production analyze, member_count, data_quality, rank-only).

usage: python explain_groups.py <pristine copy stock.db> <compare/diffs.jsonl>
"""
import json
import sqlite3
import sys

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
diffs = [json.loads(line) for line in open(sys.argv[2], encoding="utf-8")]
prod = {}
for d in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"):
    prod[d] = c.execute(
        "SELECT st.finished_at FROM schedule_run_steps st JOIN schedule_runs r ON r.id=st.schedule_run_id "
        "WHERE r.target_date=? AND r.status='success' AND st.step='analyze'", (d,)).fetchone()[0]
print("production analyze finished (UTC):", prod)
SRC = ("mops_material_information", "twse_tpex_official_announcement", "issuer_filing")
BASIC = {"catalyst", "details_json.raw_values.catalyst", "details_json.normalized_values.catalyst", "score", "rank",
         "details_json.member_count", "details_json.institutional_flow_coverage.member_count", "data_quality"}
tally = {}
for x in diffs:
    if x["table"] != "group_daily_scores" or x["kind"] != "different":
        continue
    g, d = x["key"]
    ch = x["changed"]
    kinds = set()
    if "catalyst" in ch:
        dates = [r[0] for r in c.execute(
            "SELECT b.trading_date FROM market_bars b JOIN instruments i ON i.id=b.instrument_id "
            "WHERE i.symbol='TAIEX' AND b.trading_date<=? ORDER BY b.trading_date DESC LIMIT 20", (d,))]
        mem = [r[0] for r in c.execute(
            "SELECT m.instrument_id FROM group_memberships m JOIN instruments i ON i.id=m.instrument_id "
            "WHERE m.group_id=? AND m.valid_from<=? AND (m.valid_to IS NULL OR m.valid_to>=?) AND i.status='active'", (g, d, d))]
        late = c.execute(
            f"SELECT count(*) FROM events WHERE instrument_id IN ({','.join('?' * len(mem))}) "
            f"AND event_date IN ({','.join('?' * len(dates))}) AND source IN (?,?,?) AND collected_at>?",
            (*mem, *dates, *SRC, prod[d])).fetchone()[0] if mem else 0
        kinds.add("catalyst_late_events" if late else "catalyst_NO_late_events")
    if "details_json.member_count" in ch:
        kinds.add("member_count")
    if "data_quality" in ch:
        kinds.add("data_quality:" + "->".join(ch["data_quality"]) + (":catalyst_was_null" if ch.get("catalyst", [1])[0] is None else ""))
    if set(ch) - BASIC:
        kinds.add("other:" + ",".join(sorted(set(ch) - BASIC)))
    if set(ch) == {"rank"}:
        kinds.add("rank_only")
    key = (d, tuple(sorted(kinds)))
    tally[key] = tally.get(key, 0) + 1
for k, v in sorted(tally.items()):
    print(k, v)
