"""#867 AC-1: how the fundamentals gap of delisted stocks reaches X3, X4, X7,
S1~S3 and H1 (historical).  Read-only; no simulation, no return is computed.

Uses the tools' own loaders and feature functions (master 6acdb631), so a
"missing" here is exactly the tools' None.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402
import feature_evidence as fe  # noqa: E402
import portfolio_research as pr  # noqa: E402
import trade_research as tr  # noqa: E402

DB = Path("/research/stock.db")
OUT = Path("/out")
LOAD = date(2011, 6, 1)  # warm-up for the 20-day volume / ATR / flows only
END = date(2024, 9, 27)

started = time.monotonic()


def log(text: str) -> None:
    with (OUT / "measure.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{time.monotonic() - started:7.0f}s {text}\n")


log("load start")
ctx = er.load_context(DB, LOAD, END, OUT / "raw")
panel = ctx.market.panel
sessions = panel.sessions
log(f"loaded {len(sessions)} sessions {sessions[0]}..{sessions[-1]}")

con = lib.connect_read_only(DB)
status = dict(con.execute("select id, status from instruments"))
con.close()


def cat(instrument_id: int) -> str:
    s = status.get(instrument_id)
    return s if s in ("active", "delisted", "transferred") else "other"


def yoy_reason(item, at) -> str:
    """Why revenue_yoy is what it is (same order as feature_evidence)."""
    day = item.dates[at]
    rows = fe._revenues_known(item, day)
    if not item.revenues:
        return "no_rows_ever"
    if not rows:
        return "none_known_yet"
    if (day - rows[-1][0]).days > lib.REVENUE_STALE_DAYS:
        return "stale"
    if fe._yoy(rows[-1][1], rows[-1][2]) is None:
        return "no_prior"
    return "ok"


def val(name, item, at):
    return er.value_of(ctx, name, item, at)


def window_days(name: str, segment: str) -> list[int]:
    spec = er.HYPOTHESES[name]
    w = er.segment_window(sessions, segment, spec)
    first, last = w
    if spec["rule"] == "monthly":
        return [a for a in er.event_days(sessions) if first - 1 <= a <= last - 1]
    return list(range(first - 1, last))


def new_year():
    return {
        "days": 0,
        "member_days": defaultdict(int),
        "missing": defaultdict(lambda: defaultdict(int)),
        "reason": defaultdict(lambda: defaultdict(int)),
        "passed": defaultdict(int),
        "known": defaultdict(int),
        "instruments": defaultdict(set),
        "instruments_missing_all": defaultdict(dict),
        "would_rank": defaultdict(int),
        "picked": defaultdict(int),
    }


def finish(years):
    out = {}
    for y, r in sorted(years.items()):
        out[y] = {
            "days": r["days"],
            "member_days": dict(r["member_days"]),
            "missing": {k: dict(v) for k, v in r["missing"].items()},
            "yoy_reason": {k: dict(v) for k, v in r["reason"].items()},
            "known_all_filters": dict(r["known"]),
            "passed_all_filters": dict(r["passed"]),
            "instruments": {k: len(v) for k, v in r["instruments"].items()},
            "instruments_missing_every_day": {
                k: sum(1 for flag in v.values() if flag)
                for k, v in r["instruments_missing_all"].items()
            },
            "picks_by_status": dict(r["picked"]),
            "missing_would_rank_in_top": dict(r["would_rank"]),
        }
    return out


def measure_filter(name: str, segment: str, top: int, key_fn, filters, rank_keys):
    """filters: list of (feature name, test); key for the would-rank count."""
    years = defaultdict(new_year)
    for at in window_days(name, segment):
        day = sessions[at]
        ctx.cache.clear()
        members = lib.universe(panel, day, er.MIN_LOTS)
        r = years[str(day.year)]
        r["days"] += 1
        passers, missers = [], []
        for item, i in members:
            c = cat(item.instrument_id)
            r["member_days"][c] += 1
            r["instruments"][c].add(item.instrument_id)
            values = {f: val(f, item, i) for f, _t in filters}
            missing_any = False
            for f, _t in filters:
                if values[f] is None:
                    r["missing"][f][c] += 1
                    missing_any = True
            r["reason"][c][yoy_reason(item, i)] += 1
            prev = r["instruments_missing_all"][c].get(item.instrument_id, True)
            r["instruments_missing_all"][c][item.instrument_id] = prev and missing_any
            if missing_any:
                r["missing"]["any"][c] += 1
                missers.append((item, i, c))
                continue
            r["known"][c] += 1
            if all(t(values[f]) for f, t in filters):
                r["passed"][c] += 1
                passers.append((item, i, c))
        # picks among the passers, then: would a missing member rank in the top
        # if it had passed?  (upper bound of the picks the gap can move)
        keyed = []
        for item, i, c in passers:
            keyed.append((key_fn(item, i, day), c, False))
        for item, i, c in missers:
            if c == "active":
                continue
            keyed.append((key_fn(item, i, day), c, True))
        keyed.sort(key=lambda row: row[0])
        kept = 0
        for k, c, is_missing in keyed:
            if kept >= top:
                break
            if is_missing:
                r["would_rank"][c] += 1
            else:
                r["picked"][c] += 1
                kept += 1
    return finish(years)


def key_from(names):
    def key(item, i, day):
        values = {}
        for n in names:
            v = val(n, item, i) if n in er.FEATURES else tr.SCORE_FUNCTIONS[n](item, i)
            values[n] = None if v is None or v != v else float(v)
        return pr.ranking_key(values, tuple(names), pr.tie_break(day, item.instrument_id))

    return key


gt0 = lambda v: v > 0.0  # noqa: E731
eq1 = lambda v: v == 1.0  # noqa: E731

result = {"db": str(DB), "load": [str(LOAD), str(END)], "hypotheses": {}}
plans = {
    "X3": ([("revenue_yoy", gt0)], ("institutional_flow_20",), 10),
    "X4": (
        [("revenue_yoy", gt0), ("eps_growth_yield", gt0)],
        ("eps_yield_raw",),
        20,
    ),
    "X7": (
        [("revenue_previous_month", eq1), ("revenue_high_12", eq1)],
        ("revenue_yoy",),
        20,
    ),
}
for name, (filters, keys, top) in plans.items():
    for segment in (er.EXPLORATION, er.VALIDATION):
        log(f"{name} {segment}")
        result["hypotheses"].setdefault(name, {})[segment] = {
            "window": [
                str(sessions[window_days(name, segment)[0]]),
                str(sessions[window_days(name, segment)[-1]]),
            ],
            "years": measure_filter(name, segment, top, key_from(keys), filters, keys),
        }

# S1~S3: revenue_yoy > 0 (and ATR14 > 0), by trust_buy_days then flow; the
# signal dates are X3's (same anchor 2014-12-01 + 20th session).  Occupancy
# and the S1 market filter are not applied here (they only remove days/names).
for segment in (er.EXPLORATION, er.VALIDATION):
    log(f"S {segment}")
    result["hypotheses"].setdefault("S", {})[segment] = {
        "window": [
            str(sessions[window_days("X3", segment)[0]]),
            str(sessions[window_days("X3", segment)[-1]]),
        ],
        "years": measure_filter(
            "X3",
            segment,
            10,
            key_from(tr.SCORE_KEYS),
            [("revenue_yoy", gt0)],
            tr.SCORE_KEYS,
        ),
    }

# H1 historical: revenue_high_12 is only the second key.  Count the members it
# reaches: missing revenue_high_12 and tied on trust_buy_days_5 with the 5th.
log("H1")
spec = pr.HYPOTHESES["H1"]
keys = tuple(spec["keys"])
h1_start = pr.historical_start(panel, END, keys)
first = sessions.index(h1_start)
years = defaultdict(
    lambda: {
        "days": 0,
        "member_days": defaultdict(int),
        "missing_high12": defaultdict(int),
        "tied_at_cut_missing_high12": defaultdict(int),
        "days_cut_tie_has_missing_nonactive": 0,
        "days_high12_decides_cut": 0,
    }
)
for at in range(first, len(sessions)):
    day = sessions[at]
    members = lib.universe(panel, day, lib.DEFAULT_MIN_LOTS)
    r = years[str(day.year)]
    r["days"] += 1
    rows = []
    for item, i in members:
        c = cat(item.instrument_id)
        t = pr.FEATURE_FUNCTIONS[keys[0]](item, i)
        h = fe.revenue_high_12(item, i)
        r["member_days"][c] += 1
        if h is None:
            r["missing_high12"][c] += 1
        rows.append((t, h, c))
    known = sorted((t for t, _h, _c in rows if t is not None), reverse=True)
    if len(known) < spec["top"]:
        continue
    cut = known[spec["top"] - 1]
    above = sum(1 for t in known if t > cut)
    tied = [(h, c) for t, h, c in rows if t == cut]
    if above + len(tied) > spec["top"]:
        r["days_high12_decides_cut"] += 1
        flag = False
        for h, c in tied:
            if h is None:
                r["tied_at_cut_missing_high12"][c] += 1
                flag = flag or c != "active"
        r["days_cut_tie_has_missing_nonactive"] += flag
result["hypotheses"]["H1"] = {
    "historical_start": str(h1_start),
    "until": str(END),
    "years": {
        y: {k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in r.items()}
        for y, r in sorted(years.items())
    },
}
(OUT / "bias.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
)
log("done")
