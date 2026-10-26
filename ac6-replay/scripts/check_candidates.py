"""#260 AC-6: check the replayed candidate_score_v2 runs against V1_SPEC, independently.

usage: python check_candidates.py <replay stock.db> <baseline.db>
The pool, technical inputs and group scores are rebuilt from signals, market_bars,
technical_features and group_daily_scores with the spec's formulas, not with
worker.candidates.  Prints one line per check and the v1 (baseline) comparison.
"""

import json
import math
import sqlite3
import sys

VERSION = sys.argv[3] if len(sys.argv) > 3 else "candidate_score_v2"
DATES = ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22")
WEIGHTS = {"technical": 0.35, "chips": 0.30, "news_sentiment": 0.15, "group": 0.20}
ENTRY = {"breakout_v1": "breakout", "pullback_v1": "pullback"}
TOL = 1e-9

replay = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
base = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
replay.row_factory = base.row_factory = sqlite3.Row
failures = 0


def check(day, name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"{day} {'OK  ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")


def mid_rank(value, peers, better):
    values = [v for v in peers if v is not None]
    if value is None or not values:
        return None
    if better == "lower":
        value, values = -value, [-v for v in values]
    if len(values) == 1:
        return 0.5
    less = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (less + (equal - 1) / 2) / (len(values) - 1)


def levels_ok(sig):
    entry = sig["breakout_price"] if sig["entry_type"] == "breakout" else sig["reference_entry"]
    inv, t1, t2 = sig["invalid_price"], sig["target_1"], sig["target_2"]
    if not all(isinstance(x, (int, float)) and x > 0 for x in (entry, inv, t1)):
        return False
    if not (inv < entry < t1) or (t2 is not None and t2 < t1):
        return False
    return (t1 - entry) / (entry - inv) >= 1.5 - 1e-9


for day in DATES:
    run = replay.execute(
        "SELECT * FROM candidate_runs WHERE trading_date=? AND score_version=?",
        (day, VERSION),
    ).fetchone()
    check(day, "v2 run exists, status success", run is not None and run["status"] == "success")
    if run is None:
        continue
    config = json.loads(run["config_json"])
    summary = json.loads(run["summary_json"])
    exclusions = json.loads(run["exclusions_json"])
    check(day, "config name candidate_score_v2", config.get("name") == VERSION)
    check(day, "config weights per spec", config.get("weights") == WEIGHTS, str(config.get("weights")))
    check(
        day,
        "news uses news_v2",
        summary.get("news", {}).get("llm_prompt_version") == "news_v2",
        json.dumps(summary.get("news"), ensure_ascii=False),
    )

    # Independent pool.
    signals = replay.execute(
        """SELECT s.*, sv.name AS strategy, sv.active AS strategy_active,
                  i.instrument_type, i.status AS instrument_status, i.exchange, i.symbol
           FROM signals s JOIN strategy_versions sv ON sv.id = s.strategy_version_id
           JOIN instruments i ON i.id = s.instrument_id
           WHERE s.signal_date=? AND s.signal_key LIKE 'analysis-%'
             AND sv.name IN ('breakout_v1','pullback_v1')""",
        (day,),
    ).fetchall()
    check(day, "evaluated_signals = signals of the day", run["evaluated_signals"] == len(signals), f"{run['evaluated_signals']} vs {len(signals)}")
    actionable = [s for s in signals if json.loads(s["rule_evidence_json"] or "{}").get("actionable") is True]
    check(day, "actionable_signals", summary.get("actionable_signals") == len(actionable), f"{summary.get('actionable_signals')} vs {len(actionable)}")
    pool, mine_excl = [], {}
    for s in actionable:
        reason = None
        if not s["strategy_active"]:
            reason = "inactive_strategy_formula"
        elif s["instrument_type"] not in ("stock", "ipo"):
            reason = f"instrument_type_excluded:{s['instrument_type']}"
        elif s["instrument_status"] != "active":
            reason = "instrument_inactive"
        elif s["entry_type"] != ENTRY[s["strategy"]] or not levels_ok(s):
            reason = "invalid_levels"
        else:
            bar = replay.execute(
                "SELECT * FROM market_bars WHERE instrument_id=? AND trading_date=?",
                (s["instrument_id"], day),
            ).fetchone()
            if bar is None or bar["is_suspended"]:
                reason = "signal_day_suspended_or_missing"
        if reason:
            mine_excl[reason] = mine_excl.get(reason, 0) + 1
        else:
            pool.append(s)
    check(day, "pool_count", run["pool_count"] == len(pool), f"{run['pool_count']} vs {len(pool)}")
    run_excl = {k: v for k, v in exclusions.items() if k in mine_excl or k not in ("below_list_cutoff", "insufficient_score_coverage", "duplicate_instrument_lower_score")}
    check(day, "pool exclusions", all(exclusions.get(k) == v for k, v in mine_excl.items()), f"run {exclusions} / mine {mine_excl}")

    # Technical inputs from bars and features (not from the signal evidence).
    tech = {}
    for s in pool:
        bars = replay.execute(
            "SELECT trading_date, close, volume FROM market_bars WHERE instrument_id=? AND trading_date<=? ORDER BY trading_date DESC LIMIT 21",
            (s["instrument_id"], day),
        ).fetchall()
        feat = json.loads(
            replay.execute(
                "SELECT features_json FROM technical_features WHERE instrument_id=? AND trading_date=?",
                (s["instrument_id"], day),
            ).fetchone()[0]
        )
        prior = [b["volume"] for b in bars[1:]]
        vr = bars[0]["volume"] / (sum(prior) / 20) if len(prior) == 20 and sum(prior) > 0 else None
        close = bars[0]["close"]
        if s["strategy"] == "breakout_v1":
            dist = close / feat["prior_high_20d"] - 1 if feat.get("prior_high_20d") else None
        else:
            dist = abs(close / feat["ma20"] - 1) if feat.get("ma20") else None
        tech[s["id"]] = (s["strategy"], vr, dist)

    rows = replay.execute(
        "SELECT dc.*, i.exchange, i.symbol, i.instrument_type, i.status AS istatus FROM daily_candidates dc JOIN instruments i ON i.id=dc.instrument_id WHERE candidate_run_id=? ORDER BY rank",
        (run["id"],),
    ).fetchall()
    check(day, "candidate_count = rows, ≤ 20", run["candidate_count"] == len(rows) <= 20, f"{len(rows)}")
    check(day, "ranks 1..n", [r["rank"] for r in rows] == list(range(1, len(rows) + 1)))
    check(day, "one row per instrument", len({r["instrument_id"] for r in rows}) == len(rows))
    pool_ids = {s["id"] for s in pool}
    check(day, "every candidate's signal is in the pool", all(r["signal_id"] in pool_ids for r in rows))
    by_id = {s["id"]: s for s in pool}
    check(day, "strategy matches the signal", all(by_id[r["signal_id"]]["strategy"] == r["strategy"] for r in rows if r["signal_id"] in by_id))
    keys, totals_ok, comp_ok, tech_ok, group_ok, reason_ok, cov_ok = [], True, True, True, True, True, True
    detail = []
    ranked_groups = {}
    for g in replay.execute("SELECT * FROM group_daily_scores WHERE trading_date=?", (day,)):
        ranked_groups[g["group_id"]] = g
    for r in rows:
        comps = json.loads(r["components_json"])
        scores = {k: comps[k]["score"] for k in WEIGHTS}
        used = {k: v for k, v in scores.items() if v is not None}
        cov = sum(WEIGHTS[k] for k in used)
        total = sum(WEIGHTS[k] * v for k, v in used.items()) / cov
        if abs(total - r["total_score"]) > 1e-6:
            totals_ok = False
            detail.append(f"total {r['symbol']} {total} vs {r['total_score']}")
        if abs(cov - r["weight_coverage"]) > 1e-9 or scores["technical"] is None or cov < 0.65 - 1e-12:
            cov_ok = False
        for name in WEIGHTS:
            items = comps[name].get("items") or {}
            have = [(i["weight"], i["percentile"]) for i in items.values() if i.get("weight") and i.get("percentile") is not None]
            expect = sum(w * p for w, p in have) / sum(w for w, _ in have) if have else None
            if name == "group":
                continue
            if (expect is None) != (scores[name] is None) or (expect is not None and abs(expect - scores[name]) > 1e-9):
                comp_ok = False
                detail.append(f"component {name} {r['symbol']} {expect} vs {scores[name]}")
        strategy = r["strategy"]
        peers = [t for t in tech.values() if t[0] == strategy]
        _, vr, dist = tech[r["signal_id"]]
        items = comps["technical"]["items"]
        p_vr = mid_rank(vr, [p[1] for p in peers], "higher" if strategy == "breakout_v1" else "lower")
        p_dist = mid_rank(dist, [p[2] for p in peers], "lower")
        for label, mine, stored in (("volume_ratio", p_vr, items["volume_ratio"]["percentile"]), ("distance", p_dist, items["distance"]["percentile"])):
            if (mine is None) != (stored is None) or (mine is not None and abs(mine - stored) > 1e-9):
                tech_ok = False
                detail.append(f"tech {label} {r['symbol']} mine {mine} vs {stored}")
        if abs((vr or 0) - (items["volume_ratio"]["value"] or 0)) > 1e-9 or abs((dist or 0) - (items["distance"]["value"] or 0)) > 1e-9:
            tech_ok = False
            detail.append(f"tech value {r['symbol']} vr {vr} vs {items['volume_ratio']['value']} dist {dist} vs {items['distance']['value']}")
        groups = json.loads(r["groups_json"])
        best = None
        for g in groups:
            if not g.get("qualified"):
                continue
            row = ranked_groups.get(g["group_id"])
            if row is None or row["rank"] != g["rank"]:
                group_ok = False
                detail.append(f"group row {r['symbol']} {g['group_id']}")
                continue
            p = 0.5 if g["board_size"] == 1 else 1 - (g["rank"] - 1) / (g["board_size"] - 1)
            best = p if best is None else max(best, p)
        if (best is None) != (scores["group"] is None) or (best is not None and abs(best - scores["group"]) > 1e-9):
            group_ok = False
            detail.append(f"group score {r['symbol']} {best} vs {scores['group']}")
        reasons = json.loads(r["reasons_json"])
        if len(reasons) > 4 or any(x["component"] == "news_sentiment" and x.get("inference") is not True for x in reasons):
            reason_ok = False
        if r["instrument_type"] not in ("stock", "ipo") or r["istatus"] != "active":
            reason_ok = False
        keys.append((-r["total_score"], -(scores["technical"] or 0), -(scores["chips"] if scores["chips"] is not None else -1), r["exchange"], r["symbol"]))
    check(day, "total = Σw·s/Σw over non-null components", totals_ok)
    check(day, "weight_coverage = Σw, technical non-null, ≥ 0.65", cov_ok)
    check(day, "component = weighted mean of item percentiles", comp_ok)
    check(day, "technical values and mid-rank percentiles (rebuilt from bars/features)", tech_ok)
    check(day, "group = max board percentile of qualified groups (vs group_daily_scores)", group_ok)
    check(day, "≤ 4 reasons, news reasons inference, active stock/ipo", reason_ok)
    check(day, "sort order total→technical→chips→exchange→symbol", keys == sorted(keys))
    # The 20th candidate scores at least as high as every pooled instrument left out
    # can only be checked with the stored rows; the run keeps the selected rows only.
    for line in detail[:10]:
        print("   ", line)

    # v1 baseline (stored on the day) vs the v2 replay.
    v1 = base.execute("SELECT * FROM candidate_runs WHERE trading_date=?", (day,)).fetchone()
    v1_rows = base.execute(
        "SELECT dc.instrument_id, i.symbol, dc.rank, dc.strategy FROM daily_candidates dc JOIN instruments i ON i.id=dc.instrument_id WHERE candidate_run_id=? ORDER BY rank",
        (v1["id"],),
    ).fetchall()
    a = [x["symbol"] for x in v1_rows]
    b = [r["symbol"] for r in rows]
    print(
        f"{day} v1→v2: evaluated {v1['evaluated_signals']}→{run['evaluated_signals']}, pool {v1['pool_count']}→{run['pool_count']}, "
        f"candidates {v1['candidate_count']}→{run['candidate_count']}, same set {len(set(a) & set(b))}/20, same rank {sum(1 for x, y in zip(a, b) if x == y)}"
    )
    print(f"    v1 exclusions {v1['exclusions_json']}  v2 exclusions {run['exclusions_json']}")
    print(f"    only v1 {sorted(set(a) - set(b))}  only v2 {sorted(set(b) - set(a))}")

print(f"failures {failures}")
sys.exit(1 if failures else 0)
