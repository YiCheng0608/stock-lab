"""#867 decision 7033054556: list-only control for H1 (historical).

Second benchmark: the day's population less the `status = 'delisted'`
members whose `revenue_high_12` is missing that day -- only on days where at
least one member has `revenue_high_12` known (2012-05..2014-01 nobody has it,
so there the second benchmark is the tool's population).  Same engine
(`portfolio_research.simulate`), same picks, same window.  The tool's H1 is
recomputed first and must equal the published tables.json.  Read-only.

usage: python -B control_h1.py <published tables.json> <out dir>
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import evidence_lib as lib  # noqa: E402
import portfolio_research as pr  # noqa: E402

published, out = Path(sys.argv[1]), Path(sys.argv[2])
DB = Path("/research/stock.db")
SUB_FROM = date(2014, 2, 1)
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()


def log(text: str) -> None:
    with (out / "control.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{time.monotonic() - started:7.0f}s {text}\n")


spec = pr.HYPOTHESES["H1"]
log("load")
market = pr.load_market(DB, pr.HISTORICAL_FROM, out / "raw", fundamentals=True)
panel = market.panel
sessions = panel.sessions
last = [d for d in sessions if d <= spec["historical_until"]][-1]
start = pr.historical_start(panel, last, tuple(spec["keys"]))
log(f"study {start}..{last}")
tool = pr.study_hypothesis(market, spec, start, last, spec["min_days"], pr.HISTORICAL)
report = json.loads(published.read_text(encoding="utf-8"))
same = (
    tool["verdict"] == report["verdict"]
    and tool["excess"]["judged"] == report["excess"]["judged"]
    and tool["start"] == report["start"]
    and tool["days"] == report["days"]
)
log(f"recomputed equals published: {same}")
if not same:
    (out / "control.json").write_text(
        json.dumps({"recomputed_equals_published": False}, indent=1), encoding="utf-8"
    )
    raise SystemExit("recomputed H1 differs from the published tables.json")

con = lib.connect_read_only(DB)
status = dict(con.execute("select id, status from instruments"))
con.close()

high12 = pr.FEATURE_FUNCTIONS["revenue_high_12"]
position = {day: index for index, day in enumerate(sessions)}
signal_days = [day for day in sessions if start <= day < last]
population2: dict[int, list[int]] = {}
removed_member_days = 0
removed_days = 0
applied_days = 0
for day in signal_days:
    members = lib.universe(panel, day, lib.DEFAULT_MIN_LOTS)
    values = {item.instrument_id: high12(item, at) for item, at in members}
    apply = any(v is not None for v in values.values())
    applied_days += apply
    keep = []
    dropped = 0
    for item, _at in members:
        if (
            apply
            and status.get(item.instrument_id) == "delisted"
            and values[item.instrument_id] is None
        ):
            dropped += 1
            continue
        keep.append(item.instrument_id)
    population2[position[day] + 1] = keep
    removed_member_days += dropped
    removed_days += dropped > 0
log("simulate")
first = position[signal_days[0]] + 1
last_s = position[last]
base = pr.simulate(population2, market.quote, first, last_s, spec["hold"], None)
hold, key = spec["hold"], pr.top_key(spec["top"])
mine = pr.daily_returns(tool["_simulations"][(hold, key)].equity)
pop = pr.daily_returns(tool["_simulations"][(hold, pr.POPULATION)].equity)
ctl = pr.daily_returns(base.equity)
dates = tool["_dates"]


def block(rows):
    return {
        "first_session": dates[rows[0]].isoformat(),
        "last_session": dates[rows[-1]].isoformat(),
        "tool_population": pr.excess_metrics([mine[i] - pop[i] for i in rows]),
        "control": pr.excess_metrics([mine[i] - ctl[i] for i in rows]),
    }


every = list(range(len(dates)))
sub = [i for i, d in enumerate(dates) if d >= SUB_FROM]
previous = [1.0] + base.equity[:-1]
turnover = [b / p if p > 0 else 0.0 for b, p in zip(base.bought, previous)]
result = {
    "hypothesis": "H1",
    "window": "historical",
    "decision": "https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7033054556",
    "list_only": True,
    "recomputed_equals_published": same,
    "removed": {
        "rule": "status = 'delisted' and revenue_high_12 missing, on days with at least one member known",
        "signal_days": len(signal_days),
        "signal_days_applied": applied_days,
        "signal_days_with_removal": removed_days,
        "member_days": removed_member_days,
    },
    "judged_window": block(every),
    "from_2014_02_list_only": block(sub),
    "control_curve": pr.curve_metrics(ctl, base.invested, turnover),
    "tool_population_curve": tool["curves"]["judged"][pr.POPULATION],
}
(out / "control.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
)
log("done")
