"""#867 decision 7032683717: list-only control for the explore_research
hypotheses that passed exploration.

A second benchmark: the day's population less the `delisted` members that,
on that day, miss a fundamental field the hypothesis filters on (the ones the
tool drops before picking).  Same engine (`portfolio_research.simulate`),
same picks, same segment.  The tool's own run is recomputed first and must
equal the published explore.json numbers.  Read-only; no ledger is written.

usage: python -B control_x.py <hypothesis> <published explore.json> <out dir>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402
import portfolio_research as pr  # noqa: E402

name, published, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
DB = Path("/research/stock.db")
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()


def log(text: str) -> None:
    with (out / "control.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{time.monotonic() - started:7.0f}s {text}\n")


segment = sys.argv[4] if len(sys.argv) > 4 else er.EXPLORATION
spec = er.HYPOTHESES[name]
fields = [f for f, _op, _v in spec["filters"]]
log(f"{name} {segment} fields={fields} load")
if segment == er.EXPLORATION:  # as run_exploration
    ctx = er.load_context(DB, er.LOAD_FROM, er.SEGMENTS[segment][1], out / "raw")
    min_t = er.MIN_T
else:  # as run_validation
    from datetime import timedelta

    first_day, end = er.SEGMENTS[segment]
    ctx = er.load_context(
        DB, first_day - timedelta(days=er.WARMUP_CALENDAR_DAYS), end, out / "raw"
    )
    min_t = er.validation_min_t(er.CUMULATIVE)
panel = ctx.market.panel
sessions = panel.sessions

# 1. the tool's own numbers, recomputed: must equal the published report
tool = er.run_one(ctx, DB, name, segment, min_t=min_t)
report = json.loads(published.read_text(encoding="utf-8"))["hypotheses"][name]
same = (
    tool["verdict"] == report["verdict"]
    and tool["excess"]["population"] == report["excess"]
    and tool["absolute"]["mean"] == report["absolute_mean"]
)
log(f"recomputed equals published: {same}")

con = lib.connect_read_only(DB)
status = dict(con.execute("select id, status from instruments"))
con.close()

first, last = er.segment_window(sessions, segment, spec)
planned = er.plan(ctx, spec, first, last)
removed_days = 0
removed_member_days = 0
population2 = {}
days = (
    [a for a in er.event_days(sessions) if first - 1 <= a <= last - 1]
    if spec["rule"] == "monthly"
    else list(range(first - 1, last))
)
for at in days:
    day = sessions[at]
    ctx.cache.clear()
    keep = []
    dropped = 0
    for item, i in lib.universe(panel, day, er.MIN_LOTS):
        if status.get(item.instrument_id) == "delisted" and any(
            er.value_of(ctx, f, item, i) is None for f in fields
        ):
            dropped += 1
            continue
        keep.append(item.instrument_id)
    population2[at + 1] = keep
    removed_member_days += dropped
    removed_days += dropped > 0
assert population2.keys() == planned.population.keys()
log("simulate")
quote = ctx.quote
if spec["rule"] == "monthly":
    mine = er.simulate_events(planned.picks, planned.dues, quote, first, last, spec["top"])
    base = er.simulate_events(population2, planned.dues, quote, first, last, None)
else:
    mine = pr.simulate(planned.picks, quote, first, last, spec["hold"], spec["top"])
    base = pr.simulate(population2, quote, first, last, spec["hold"], None)
returns = pr.daily_returns(mine.equity)
others = pr.daily_returns(base.equity)
control = pr.excess_metrics([a - b for a, b in zip(returns, others)])
result = {
    "hypothesis": name,
    "segment": segment,
    "decision": "https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032683717",
    "list_only": True,
    "published_explore_json": str(published),
    "recomputed_equals_published": same,
    "fields": fields,
    "removed": {
        "rule": "status = 'delisted' and any filter field missing on the day",
        "member_days": removed_member_days,
        "signal_days_with_removal": removed_days,
        "signal_days": len(days),
    },
    "tool": {
        "verdict": tool["verdict"],
        "excess_population": tool["excess"]["population"],
        "absolute_mean": tool["absolute"]["mean"],
        "population_curve": tool["curves"]["population"],
    },
    "control": {
        "excess": control,
        "benchmark_curve": pr.curve_metrics(others, base.invested, er._turnover(base)),
    },
}
(out / "control.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
)
log("done")
