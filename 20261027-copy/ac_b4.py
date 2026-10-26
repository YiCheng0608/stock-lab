"""#279 AC-B3/AC-B4 measurements on the production DB copy (read by the given code tree).

    python ac_b4.py summaries <YYYY-MM-DD> <out.json>   # every listed instrument's summary
    python ac_b4.py compare <a.json> <b.json>            # field-by-field equality
    python ac_b4.py tiers <YYYY-MM-DD> [...]             # action_tier_v1 counts per tier

The caller sets STOCK_DB_PATH to the copy and PYTHONPATH to a backend tree.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
import time
from datetime import date

from sqlalchemy import func, select

from app import decision
from app.db import SessionLocal
from app.models import StrategyLevel, Signal

UNKNOWN = "研究條件需要人工核對"


def without_times(value):
    if isinstance(value, dict):
        return {
            key: without_times(item)
            for key, item in value.items()
            if key not in {"generated_at", "response_generated_at"}
        }
    if isinstance(value, list):
        return [without_times(item) for item in value]
    return value


def summaries(day: str, out: str) -> None:
    as_of = date.fromisoformat(day)
    started = time.time()
    with SessionLocal() as db:
        levels = db.scalar(
            select(func.count(StrategyLevel.id))
            .join(Signal, Signal.id == StrategyLevel.signal_id)
            .where(Signal.signal_date == as_of)
        )
        ids = decision.prioritized_instrument_ids(db, as_of)
        items = decision.build_action_summaries(db, as_of, instrument_ids=ids)
    payload = {str(item["instrument"]["id"]): without_times(item) for item in items}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    states = collections.Counter(item["action_state"] for item in items)
    reasons = collections.Counter(
        item["primary_reason"]["label"]
        for item in items
        if item["action_state"] == "no_condition"
    )
    shape = collections.Counter(
        "差 N 項" if "差 " in label and " 項：" in label else label
        for label in reasons.elements()
    )
    print(
        json.dumps(
            {
                "as_of": day,
                "strategy_levels_rows_of_the_day": levels,
                "summaries": len(items),
                "action_state": dict(states),
                "no_condition_primary_reason_unknown": reasons.get(UNKNOWN, 0),
                "no_condition_primary_reason_kinds": dict(shape.most_common(6)),
                "no_condition_examples": [label for label, _ in reasons.most_common(5)],
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "seconds": round(time.time() - started, 1),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def compare(a: str, b: str) -> None:
    with open(a, encoding="utf-8") as handle:
        left = json.load(handle)
    with open(b, encoding="utf-8") as handle:
        right = json.load(handle)
    differ = [key for key in left if left[key] != right.get(key)]
    print(
        json.dumps(
            {
                "left": len(left),
                "right": len(right),
                "same_ids": sorted(left) == sorted(right),
                "differing_summaries": len(differ),
                "examples": differ[:5],
            }
        )
    )


def tiers(days: list[str]) -> None:
    for day in days:
        as_of = date.fromisoformat(day)
        with SessionLocal() as db:
            rows = decision.action_tier_rows(db, as_of)
        counts = collections.Counter((row.tier, row.is_etf) for row in rows)
        near = collections.Counter(
            (row.nearness["strategy"], row.nearness["unmet_count"], row.is_etf)
            for row in rows
            if row.tier == 3
        )
        missing = sum(row.tier == 4 and row.nearness is None for row in rows)
        print(
            json.dumps(
                {
                    "as_of": day,
                    "tiers": {
                        tier: {"stock": counts[(tier, False)], "etf": counts[(tier, True)]}
                        for tier in range(6)
                    },
                    "tier3_by_strategy_unmet_etf": {
                        f"{s}/{u}/{'etf' if e else 'stock'}": n
                        for (s, u, e), n in sorted(near.items())
                    },
                    "tier4_without_strategy_levels": missing,
                    "tier3_first10": [
                        f"{row.symbol} {row.nearness['strategy']} unmet={row.unmet_conditions} gap={row.price_gap}"
                        for row in rows
                        if row.tier == 3
                    ][:10],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    {"summaries": summaries, "compare": compare}.get(command, None)(*args) if command != "tiers" else tiers(args)
