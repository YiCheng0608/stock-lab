"""Does a feature known at T's close say anything about the next 5／20 sessions?

Read only (``mode=ro`` + ``query_only``); refuses the production database as
``backtest_research.py`` does.  Reads a ``tools/ops/copy_db.py`` copy and writes
``summary.md`` and ``tables.json`` to ``--out``.  No research backtest run is
needed: it reads bars, chips and monthly revenues directly, so the whole range
takes minutes.

Every session T, among the tradable instruments (``evidence_lib.universe``:
stock／ipo, a bar that is not suspended, 20-session mean volume of at least
``--min-lots`` lots, the candidate pool's floor), for each feature in
``FEATURES`` and each horizon:

- **IC**: the rank correlation between the feature and the forward return
  (``evidence_lib.forward_return``), over the instruments that have both;
- **quintiles**: the mean excess return (the forward return less the mean of
  the day's universe) of each fifth of the feature's ranks, and the spread of
  the top fifth over the bottom one.

A day counts only with ``--min-names`` instruments.  ``CONDITIONS`` are the
yes／no parts of the live rules (breakout, pullback, the institutional and
margin confirmations; the group confirmation needs the scored boards and is
not here): per day the mean excess return of the instruments that meet one.

The days are then averaged per segment and per quarter.  ``judge`` is the rule
a report may quote and is fixed here, before any result was read:

- **selected in exploration**: at least ``MIN_DAYS`` days, ``|mean IC|`` at
  least ``MIN_IC``, and ``|t|`` at least ``MIN_T`` with the days counted as
  ``days / horizon`` (``evidence_lib.t_stat``);
- **confirmed in validation**: at least ``MIN_DAYS`` days, the mean IC and the
  quintile spread both of the exploration's sign, and ``|t|`` at least
  ``MIN_T`` there too.  The same sign with a smaller ``|t|`` is "same
  direction, not significant" (``weak``): worth watching, not a basis.

Anything else is "no evidence", "reversed" (the validation IC has the other
sign) or "cannot tell" (too few days).  A condition is judged the same way on
its daily mean excess return instead of the IC.  ``len(FEATURES)`` features
times two horizons are compared at once: a few pass by chance, which the
report says.

Every feature uses rows dated T or earlier.  A monthly revenue counts from
its ``announcement_date``, a quarterly statement from its own (the filing
deadline for a backfilled quarter).  Chips of T are taken as known at T's close, the
live rules' assumption (docs/spec/README.md).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from bisect import bisect_right
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_lib as lib  # noqa: E402

MIN_DAYS = 60
MIN_IC = 0.02
MIN_T = 2.0
QUINTILES = 5
RAW_DIR_NAME = ".raw-unused"
DEFAULT_START = lib.SEGMENTS[0][2]


# --- features -------------------------------------------------------------


def _total(values) -> float | None:
    """Sum of a window; None when a value is missing (NaN)."""

    total = sum(values)
    return None if total != total else total


def _mean_volume(item: lib.Series, at: int) -> float | None:
    """Mean volume of the 20 bars before T (the live rules' base)."""

    if at < 20:
        return None
    mean = sum(item.volume[at - 20 : at]) / 20.0
    return mean if mean > 0 else None


def _momentum(sessions: int) -> Callable[[lib.Series, int], float | None]:
    def feature(item: lib.Series, at: int) -> float | None:
        if at < sessions:
            return None
        then, now = item.close[at - sessions], item.close[at]
        return now / then - 1.0 if then > 0 and now > 0 else None

    return feature


def _high_gap(sessions: int) -> Callable[[lib.Series, int], float | None]:
    def feature(item: lib.Series, at: int) -> float | None:
        if at + 1 < sessions:
            return None
        top = _peak(item.high[at + 1 - sessions : at + 1])
        now = item.close[at]
        return now / top - 1.0 if top and now > 0 else None

    return feature


def _peak(values) -> float | None:
    top = max(values, default=lib.NAN)
    if top != top or any(value != value for value in values):
        return None
    return top if top > 0 else None


def volume_ratio(item: lib.Series, at: int) -> float | None:
    base = _mean_volume(item, at)
    return item.volume[at] / base if base else None


def _flow(names: tuple[str, ...], sessions: int):
    def feature(item: lib.Series, at: int) -> float | None:
        base = _mean_volume(item, at)
        if base is None or at + 1 < sessions:
            return None
        total = 0.0
        for name in names:
            part = _total(item.chips[name][at + 1 - sessions : at + 1])
            if part is None:
                return None
            total += part
        return total / base

    return feature


INSTITUTIONS = ("foreign_buy", "trust_buy", "dealer_buy")
institutional_flow_5 = _flow(INSTITUTIONS, 5)


def trust_buy_days(item: lib.Series, at: int) -> float | None:
    if at < 4:
        return None
    window = item.chips["trust_buy"][at - 4 : at + 1]
    if any(value != value for value in window):
        return None
    return float(sum(1 for value in window if value > 0))


def _change(name: str, sessions: int):
    def feature(item: lib.Series, at: int) -> float | None:
        if at < sessions:
            return None
        then, now = item.chips[name][at - sessions], item.chips[name][at]
        if then != then or now != now or then <= 0:
            return None
        return (now - then) / then

    return feature


margin_change_5 = _change("margin_balance", 5)


def borrowed_sell_surge(item: lib.Series, at: int) -> float | None:
    """Borrowed shares sold in 5 sessions over the 20-session pace."""

    if at < 19:
        return None
    month = _total(item.chips["borrowed_sell"][at - 19 : at + 1])
    week = _total(item.chips["borrowed_sell"][at - 4 : at + 1])
    if month is None or week is None or month <= 0:
        return None
    return (week / 5.0) / (month / 20.0)


def day_trade_ratio(item: lib.Series, at: int) -> float | None:
    value = item.chips["day_trade_ratio"][at]
    return None if value != value else value


def _revenues_known(
    item: lib.Series, day: date
) -> list[tuple[date, float, float | None]]:
    """(month, revenue, prior year) announced by ``day``, by month, latest last."""

    known = bisect_right(item.revenues, day, key=lambda row: row[0])
    months: dict[date, tuple[float, float | None]] = {}
    for _announced, month, revenue, prior in item.revenues[:known]:
        if revenue is not None:
            months[month] = (revenue, prior)
    return [(month, *months[month]) for month in sorted(months)]


def _latest_revenue(item: lib.Series, at: int):
    day = item.dates[at]
    rows = _revenues_known(item, day)
    if not rows or (day - rows[-1][0]).days > lib.REVENUE_STALE_DAYS:
        return None
    return rows


def _yoy(revenue: float, prior: float | None) -> float | None:
    return revenue / prior - 1.0 if prior and prior > 0 else None


def revenue_yoy(item: lib.Series, at: int) -> float | None:
    rows = _latest_revenue(item, at)
    return _yoy(rows[-1][1], rows[-1][2]) if rows else None


def revenue_yoy_change(item: lib.Series, at: int) -> float | None:
    """The latest month's year-on-year growth less the month before's."""

    rows = _latest_revenue(item, at)
    if not rows or len(rows) < 2:
        return None
    now, before = _yoy(rows[-1][1], rows[-1][2]), _yoy(rows[-2][1], rows[-2][2])
    return None if now is None or before is None else now - before


def revenue_high_12(item: lib.Series, at: int) -> float | None:
    """1 when the latest month is the highest of the last 12 known, else 0."""

    rows = _latest_revenue(item, at)
    if not rows or len(rows) < 12:
        return None
    last = [revenue for _month, revenue, _prior in rows[-12:]]
    return 1.0 if last[-1] >= max(last) else 0.0


def _quarter_eps(item: lib.Series, at: int) -> tuple[float, float | None] | None:
    """(the latest quarter's own EPS, the same quarter's a year before) known at T.

    Statements carry the year's cumulative EPS, so a quarter's own is the
    difference from the quarter before in the same year (the first quarter's
    is the cumulative figure).  None when the latest known quarter is stale or
    the quarter before it is not known.
    """

    day = item.dates[at]
    known = bisect_right(item.quarters, day, key=lambda row: row[0])
    cumulative = {end: eps for _announced, end, eps in item.quarters[:known]}
    if not cumulative:
        return None
    latest = max(cumulative)
    if (day - latest).days > lib.QUARTER_STALE_DAYS:
        return None

    def own(end: date) -> float | None:
        if end not in cumulative:
            return None
        if end.month == 3:
            return cumulative[end]
        before = date(end.year, end.month - 3, 31 if end.month == 6 else 30)
        return cumulative[end] - cumulative[before] if before in cumulative else None

    now = own(latest)
    if now is None:
        return None
    return now, own(date(latest.year - 1, latest.month, latest.day))


def eps_yield(item: lib.Series, at: int) -> float | None:
    """The latest quarter's EPS, annualised, over T's close."""

    eps, close = _quarter_eps(item, at), item.close[at]
    return eps[0] * 4.0 / close if eps and close > 0 else None


def eps_growth_yield(item: lib.Series, at: int) -> float | None:
    """The quarter's EPS less the same quarter's a year before, over T's close.

    Over the price, not over last year's EPS: a ratio of EPS breaks down
    when last year's was near zero or negative.
    """

    eps, close = _quarter_eps(item, at), item.close[at]
    if not eps or eps[1] is None or not close > 0:
        return None
    return (eps[0] - eps[1]) / close


# (key, label, group, function).  Adding one adds a comparison: say so in the report.
FEATURES: tuple[
    tuple[str, str, str, Callable[[lib.Series, int], float | None]], ...
] = (
    ("momentum_20", "20 日報酬", "價量", _momentum(20)),
    ("momentum_60", "60 日報酬", "價量", _momentum(60)),
    ("momentum_120", "120 日報酬", "價量", _momentum(120)),
    ("high_gap_60", "收盤距 60 日最高價", "價量", _high_gap(60)),
    ("high_gap_240", "收盤距 240 日最高價", "價量", _high_gap(240)),
    ("volume_ratio", "量比（當日量 ÷ 前 20 日均量）", "價量", volume_ratio),
    (
        "institutional_flow_5",
        "三大法人 5 日淨買超 ÷ 20 日均量",
        "籌碼",
        institutional_flow_5,
    ),
    (
        "institutional_flow_20",
        "三大法人 20 日淨買超 ÷ 20 日均量",
        "籌碼",
        _flow(INSTITUTIONS, 20),
    ),
    (
        "foreign_flow_5",
        "外資 5 日淨買超 ÷ 20 日均量",
        "籌碼",
        _flow(("foreign_buy",), 5),
    ),
    ("trust_flow_5", "投信 5 日淨買超 ÷ 20 日均量", "籌碼", _flow(("trust_buy",), 5)),
    ("trust_buy_days_5", "投信近 5 日買超天數", "籌碼", trust_buy_days),
    ("margin_change_5", "融資餘額 5 日變化率", "籌碼", margin_change_5),
    ("short_change_5", "融券餘額 5 日變化率", "籌碼", _change("short_balance", 5)),
    ("borrowed_sell_surge", "借券賣出 5 日相對 20 日速度", "籌碼", borrowed_sell_surge),
    ("day_trade_ratio", "當沖比", "籌碼", day_trade_ratio),
    ("revenue_yoy", "最新月營收年增率", "營收", revenue_yoy),
    ("revenue_yoy_change", "月營收年增率較前月變化", "營收", revenue_yoy_change),
    ("revenue_high_12", "月營收創近 12 個月新高", "營收", revenue_high_12),
    ("eps_yield", "最新一季 EPS 年化 ÷ 股價", "財報", eps_yield),
    ("eps_growth_yield", "單季 EPS 年增額 ÷ 股價", "財報", eps_growth_yield),
)


# --- the live rules' yes／no parts -----------------------------------------


def _mean_close(item: lib.Series, at: int, sessions: int) -> float | None:
    if at + 1 < sessions:
        return None
    total = _total(item.close[at + 1 - sessions : at + 1])
    return None if total is None else total / sessions


def breakout_price(item: lib.Series, at: int) -> bool | None:
    if at < 20:
        return None
    top = _peak(item.high[at - 20 : at])
    return None if top is None else item.close[at] > top


def breakout_volume(item: lib.Series, at: int) -> bool | None:
    ratio = volume_ratio(item, at)
    return None if ratio is None else ratio >= 1.20


def pullback_setup(item: lib.Series, at: int) -> bool | None:
    ma20, ma60 = _mean_close(item, at, 20), _mean_close(item, at, 60)
    ratio = volume_ratio(item, at)
    if ma20 is None or ma60 is None or ratio is None:
        return None
    close = item.close[at]
    return bool(
        ma20 > ma60
        and close >= ma60
        and 0.97 <= close / ma20 <= 1.02
        and 0.60 <= ratio <= 1.20
    )


def institutional_ok(item: lib.Series, at: int) -> bool | None:
    flow = institutional_flow_5(item, at)
    return None if flow is None else flow >= -0.003


def margin_ok(item: lib.Series, at: int) -> bool | None:
    change = margin_change_5(item, at)
    return None if change is None else change <= 0.05


def _every(*parts) -> Callable[[lib.Series, int], bool | None]:
    def condition(item: lib.Series, at: int) -> bool | None:
        met = True
        for part in parts:
            value = part(item, at)
            if value is None:
                return None
            met = met and value
        return met

    return condition


breakout_rule = _every(breakout_price, breakout_volume)
CONDITIONS: tuple[tuple[str, str, Callable[[lib.Series, int], bool | None]], ...] = (
    ("breakout_price", "收盤站上前 20 日最高價", breakout_price),
    ("breakout_volume", "量比 ≥ 1.20", breakout_volume),
    ("breakout_rule", "突破（價＋量）", breakout_rule),
    ("pullback_setup", "回踩（趨勢、支撐區、量縮）", pullback_setup),
    ("institutional_ok", "法人 5 日淨買超 ≥ −0.3% 均量", institutional_ok),
    ("margin_ok", "融資 5 日增幅 ≤ 5%", margin_ok),
    (
        "breakout_confirmed",
        "突破＋法人＋融資（不含族群）",
        _every(breakout_rule, institutional_ok, margin_ok),
    ),
    (
        "pullback_confirmed",
        "回踩＋法人＋融資（不含族群）",
        _every(pullback_setup, institutional_ok, margin_ok),
    ),
)


# --- one day ---------------------------------------------------------------


def quintile_means(values: list[float], excess: list[float]) -> list[float | None]:
    """Mean excess return of each fifth of ``values``' ranks (ties share a fifth)."""

    ranks = lib.average_ranks(values)
    buckets: list[list[float]] = [[] for _ in range(QUINTILES)]
    for rank, value in zip(ranks, excess):
        at = min(int((rank - 0.5) / len(values) * QUINTILES), QUINTILES - 1)
        buckets[at].append(value)
    return [statistics.fmean(bucket) if bucket else None for bucket in buckets]


def day_values(members: list[tuple[lib.Series, int]]) -> dict[str, list[Any]]:
    """Each feature's and condition's value per member (None when not known)."""

    values = {
        key: [function(item, at) for item, at in members]
        for key, _label, _group, function in FEATURES
    }
    for key, _label, function in CONDITIONS:
        values[key] = [function(item, at) for item, at in members]
    return values


def day_rows(
    members: list[tuple[lib.Series, int]],
    values: dict[str, list[Any]],
    horizon: int,
    min_names: int,
) -> dict[str, Any] | None:
    """The day's IC and quintiles per feature and mean excess per condition."""

    returns = [lib.forward_return(item, at, horizon) for item, at in members]
    known = [value for value in returns if value is not None]
    if len(known) < min_names:
        return None
    base = statistics.fmean(known)
    features: dict[str, Any] = {}
    for key, _label, _group, _function in FEATURES:
        pairs = [
            (value, forward - base)
            for value, forward in zip(values[key], returns)
            if value is not None and forward is not None
        ]
        if len(pairs) < min_names:
            continue
        xs, excess = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        ic = lib.spearman(xs, excess)
        if ic is None:
            continue
        features[key] = {"ic": ic, "n": len(xs), "q": quintile_means(xs, excess)}
    conditions: dict[str, Any] = {}
    for key, _label, _function in CONDITIONS:
        met = [
            forward - base
            for flag, forward in zip(values[key], returns)
            if flag and forward is not None
        ]
        if met:
            conditions[key] = {
                "n": len(met),
                "mean": statistics.fmean(met),
                "beat": sum(1 for value in met if value > 0),
            }
    return {"names": len(known), "features": features, "conditions": conditions}


# --- averaging and the rule -------------------------------------------------


def _mean(values) -> float | None:
    values = [value for value in values if value is not None]
    return statistics.fmean(values) if values else None


def feature_table(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    """Averages of one feature's daily rows (``ic``, ``n``, ``q``)."""

    if not rows:
        return {"days": 0}
    ics = [row["ic"] for row in rows]
    quintiles = [_mean(row["q"][k] for row in rows) for k in range(QUINTILES)]
    spreads = [
        row["q"][-1] - row["q"][0]
        for row in rows
        if row["q"][-1] is not None and row["q"][0] is not None
    ]
    return {
        "days": len(rows),
        "names": statistics.fmean(row["n"] for row in rows),
        "ic": statistics.fmean(ics),
        "ic_positive": sum(1 for value in ics if value > 0) / len(ics),
        "t": lib.t_stat(ics, horizon),
        "t_naive": lib.t_stat(ics),
        "quintiles": quintiles,
        "spread": statistics.fmean(spreads) if spreads else None,
    }


def condition_table(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    if not rows:
        return {"days": 0}
    means = [row["mean"] for row in rows]
    total = sum(row["n"] for row in rows)
    return {
        "days": len(rows),
        "n": total,
        "mean": statistics.fmean(means),
        "pooled": sum(row["mean"] * row["n"] for row in rows) / total,
        "beat": sum(row["beat"] for row in rows) / total,
        "t": lib.t_stat(means, horizon),
        "t_naive": lib.t_stat(means),
    }


def judge(exploration: dict[str, Any], validation: dict[str, Any], key: str) -> str:
    """``evidence``／``weak``／``not_selected``／``reversed``／``cannot_tell``.

    ``key`` is the averaged value the rule reads: ``ic`` for a feature,
    ``mean`` for a condition.
    """

    if exploration.get("days", 0) < MIN_DAYS:
        return "cannot_tell"
    value, t = exploration[key], exploration.get("t")
    floor = MIN_IC if key == "ic" else 0.0
    if t is None or abs(t) < MIN_T or abs(value) < floor or value == 0:
        return "not_selected"
    if validation.get("days", 0) < MIN_DAYS:
        return "cannot_tell"
    sign = 1 if value > 0 else -1
    if validation[key] * sign < 0:
        return "reversed"
    if key == "ic":
        spreads = (exploration.get("spread"), validation.get("spread"))
        if any(spread is None or spread * sign <= 0 for spread in spreads):
            return "not_selected"
    if validation[key] == 0:
        return "not_selected"
    confirmed = validation.get("t")
    return "evidence" if confirmed is not None and abs(confirmed) >= MIN_T else "weak"


VERDICTS = {
    "evidence": "有證據",
    "weak": "方向一致但不顯著",
    "not_selected": "沒有證據",
    "reversed": "驗證段反轉",
    "cannot_tell": "無法判定",
}


def build(
    db: Path,
    start: date,
    end: date | None,
    min_lots: float,
    min_names: int,
    raw_dir: Path,
    progress: Callable[[str], None] = lambda _text: None,
) -> dict[str, Any]:
    panel = lib.load_panel(db, start, raw_dir)
    days = [day for day in panel.sessions if end is None or day <= end]
    progress(f"panel: {len(panel.series)} instruments, {len(days)} sessions")
    daily: dict[int, list[tuple[date, dict[str, Any]]]] = {h: [] for h in lib.HORIZONS}
    for count, day in enumerate(days, 1):
        members = lib.universe(panel, day, min_lots)
        values = day_values(members)
        for horizon in lib.HORIZONS:
            row = day_rows(members, values, horizon, min_names)
            if row is not None:
                daily[horizon].append((day, row))
        if count % 50 == 0:
            progress(f"{count}/{len(days)} sessions")
    result: dict[str, Any] = {
        "range": [
            days[0].isoformat() if days else None,
            days[-1].isoformat() if days else None,
        ],
        "sessions": len(days),
        "min_lots": min_lots,
        "min_names": min_names,
        "rule": {"min_days": MIN_DAYS, "min_ic": MIN_IC, "min_t": MIN_T},
        "comparisons": len(FEATURES) * len(lib.HORIZONS),
        "segments": [
            {"key": key, "label": label, "first": first, "last": last}
            for key, label, first, last in lib.SEGMENTS
        ],
        "horizons": {},
    }
    for horizon in lib.HORIZONS:
        rows = daily[horizon]
        groups = lib.by_segment([day for day, _row in rows])
        tables: dict[str, Any] = {
            "days": {key: len(positions) for key, positions in groups.items()},
            "names": _mean(row["names"] for _day, row in rows),
            "features": {},
            "conditions": {},
        }
        for kind, keys, table, value in (
            ("features", [feature[0] for feature in FEATURES], feature_table, "ic"),
            (
                "conditions",
                [condition[0] for condition in CONDITIONS],
                condition_table,
                "mean",
            ),
        ):
            for key in keys:
                per_group = {
                    group: table(
                        [
                            rows[at][1][kind][key]
                            for at in positions
                            if key in rows[at][1][kind]
                        ],
                        horizon,
                    )
                    for group, positions in groups.items()
                }
                for segment, *_ in lib.SEGMENTS:
                    per_group.setdefault(segment, {"days": 0})
                per_group["verdict"] = judge(
                    per_group["exploration"], per_group["validation"], value
                )
                tables[kind][key] = per_group
        result["horizons"][str(horizon)] = tables
    return result


# --- the report --------------------------------------------------------------


def _feature_line(label: str, table: dict[str, Any]) -> str:
    cells = []
    for segment, *_ in lib.SEGMENTS:
        part = table[segment]
        if not part.get("days"):
            cells += ["0", "—", "—", "—"]
            continue
        cells += [
            str(part["days"]),
            lib.num(part["ic"]),
            lib.num(part["t"], 2),
            lib.pct(part["spread"]),
        ]
    return f"| {label} | {' | '.join(cells)} | {VERDICTS[table['verdict']]} |"


def _condition_line(label: str, table: dict[str, Any]) -> str:
    cells = []
    for segment, *_ in lib.SEGMENTS:
        part = table[segment]
        if not part.get("days"):
            cells += ["0", "—", "—", "—"]
            continue
        cells += [
            f"{part['n']:,}",
            lib.pct(part["mean"]),
            lib.pct(part["beat"], 1),
            lib.num(part["t"], 2),
        ]
    return f"| {label} | {' | '.join(cells)} | {VERDICTS[table['verdict']]} |"


def markdown(result: dict[str, Any], command: str) -> str:
    lines = [
        "# 特徵證據（feature_evidence）",
        "",
        f"- 範圍：{result['range'][0]}～{result['range'][1]}，{result['sessions']} 個交易日",
        f"- 每日母體：股票與 IPO、當日有成交、20 日均量 ≥ {result['min_lots']:g} 張；"
        f"少於 {result['min_names']} 檔的日子不計",
        "- 報酬：T+1 開盤買（含 5 bps 滑價）、T+N 收盤計價；超額報酬＝減去當日母體平均，與成本無關",
        f"- 判定規則（寫死在程式）：探索段至少 {MIN_DAYS} 日、|IC| ≥ {MIN_IC}、"
        f"|t| ≥ {MIN_T}（天數以「日數 ÷ N」計）才算選出；"
        f"驗證段 IC 與五分位差同號且 |t| ≥ {MIN_T} 才算有證據，同號但不到的記「方向一致但不顯著」",
        f"- 同時比較了 {result['comparisons']} 組（特徵 × 期間）：其中幾組碰巧通過並不意外",
        f"- 重現：`{command}`",
        "",
    ]
    labels = {key: (label, group) for key, label, group, _function in FEATURES}
    for horizon, tables in result["horizons"].items():
        lines += [
            f"## T+{horizon}：特徵",
            "",
            "IC 是每日排序相關的平均；五分位差是特徵最高一組減最低一組的平均超額報酬。",
            "",
            "| 特徵 | 探索段日數 | IC | t | 五分位差 | 驗證段日數 | IC | t | 五分位差 | 判定 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for key, table in tables["features"].items():
            label, group = labels[key]
            lines.append(_feature_line(f"{group}｜{label}", table))
        lines += [
            "",
            f"## T+{horizon}：現行規則的各個條件",
            "",
            "符合條件的股票，相對當日母體平均的超額報酬；「贏過平均」是筆數比例。",
            "",
            "| 條件 | 探索段筆數 | 平均超額 | 贏過平均 | t | 驗證段筆數 | 平均超額 | 贏過平均 | t | 判定 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        names = {key: label for key, label, _function in CONDITIONS}
        for key, table in tables["conditions"].items():
            lines.append(_condition_line(names[key], table))
        lines.append("")
    lines += [
        "## 樣本限制",
        "",
        "- 只有一段歷史；驗證段只有一段，涵蓋的市況有限。",
        "- t 值把重疊的 N 日報酬以「日數 ÷ N」計，是保守的下限，不是精確檢定。",
        "- 超額報酬是對當日母體的等權平均，不含部位大小、漲跌停買不到與成交量限制。",
        "- 當日籌碼視為收盤後已知，與現行規則相同（docs/spec/README.md）。",
        "- 逐季數字在 `tables.json`；單季樣本小，不單獨作結論。",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feature_evidence.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a tools/ops/copy_db.py copy")
    parser.add_argument("--out", required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--min-lots", type=float, default=lib.DEFAULT_MIN_LOTS)
    parser.add_argument("--min-names", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = lib.production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(
        db,
        args.start,
        args.end,
        args.min_lots,
        args.min_names,
        out / RAW_DIR_NAME,
        lambda text: print(text, file=sys.stderr, flush=True),
    )
    command = "python tools/research/feature_evidence.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    print(json.dumps({"out": str(out.resolve()), "sessions": result["sessions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
