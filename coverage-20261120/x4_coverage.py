"""#868 review 7035385605: X4's fundamentals on a read-only copy (read only).

For the latest sessions of the copy: the population (evidence_lib.universe),
how many members have each X4 feature, and how many pass both filters
(the ones that can enter the list).  Uses explore_research's own loader and
feature functions; nothing is written to the copy.
"""

import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, "/app/tools/research")
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402

db, out = Path(sys.argv[1]), Path(sys.argv[2])
spec = er.HYPOTHESES["X4"]
latest = date.fromisoformat(
    lib.connect_read_only(db).execute("select max(trading_date) from market_bars").fetchone()[0]
)
ctx = er.load_context(db, latest - timedelta(days=er.WARMUP_CALENDAR_DAYS), latest, out / "raw")
panel = ctx.market.panel
rows = []
for day in panel.sessions[-5:]:
    ctx.cache.clear()
    members = lib.universe(panel, day, er.MIN_LOTS)
    have = Counter()
    passing = 0
    quarters = Counter()
    for item, at in members:
        values = {n: er.value_of(ctx, n, item, at) for n in er.used_features(spec)}
        for n, v in values.items():
            have[n] += v is not None
        if all(er.passes(values[n], op, x) for n, op, x in spec["filters"]):
            passing += 1
        from bisect import bisect_right
        known = item.quarters[: bisect_right(item.quarters, day, key=lambda r: r[0])]
        if known:
            quarters[max(end for _a, end, _e in known).isoformat()] += 1
        eps = er.features._quarter_eps(item, at)
        have["quarter_eps_and_year_ago"] += bool(eps and eps[1] is not None)
    rows.append(
        {
            "day": day.isoformat(),
            "population": len(members),
            "have": dict(have),
            "both_filters_positive": passing,
            "latest_known_quarter_end": dict(quarters.most_common(4)),
        }
    )
print(json.dumps({"copy_latest": latest.isoformat(), "rows": rows}, ensure_ascii=False, indent=2))
