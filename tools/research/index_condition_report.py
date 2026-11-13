"""Tables of one index-condition research backtest run (#567), read only.

Reads the database ``--db`` (the copy the ``backtest_research.py
--index-condition`` run wrote) through a ``mode=ro`` connection with
``query_only`` on, and writes to ``--out``:

- ``summary.md``: the tables of the #567 report;
- ``tables.json``: the same numbers, with the run id and request key;
- ``segments.csv``: every run of consecutive score dates with one condition
  state (C2／C7 once per market).

The sample split is ``app.strategies.index_conditions``' ``EXPLORATION``／
``VALIDATION``, fixed before any result was read; every table is given for
both segments (and the whole range and each calendar quarter of the signal
date).  For each registered strategy of the run (the baseline) and each of
its index-condition strategies, as ``regime_report.py`` does for #546:

- rows, ``data_incomplete`` rows and actionable signals (status not
  ``observation``／``data_incomplete``／``invalid_levels``);
- the tracking status of the actionable signals (口徑: the run's
  ``tracking_version``);
- the T+5／T+20 comparable settlement returns, less the ones still
  ``not_triggered`` at T+N;
- the baseline's actionable signals split by the condition's state on their
  signal date for their own market (kept, condition failed, index data
  incomplete): what each condition removes, and how many of those were later
  ``invalidated``;
- a check that each condition version's actionable signals are the
  baseline's where its condition holds, with the same status and settlements;
- the segment judgement of ``judge_exploration``／``judge_validation``.

Then the market: each series over each segment (first and last close, largest
drawdown), TAIEX by quarter, each condition's days and runs, every TX roll
(the basis on the contract's last day and the next one's first), and which US
date each score date read.

Refuses the production database as ``backtest_research.py`` does.  Never
writes the database.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import importlib.util
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALL = "all"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


regime_report = _load("regime_report")
STATUSES = regime_report.STATUSES
STATES = regime_report.STATES
STATE_ZH = regime_report.STATE_ZH
NOT_ACTIONABLE = regime_report.NOT_ACTIONABLE
quarter = regime_report.quarter
summarize = regime_report.summarize
pct = regime_report.pct
share = regime_report.share
MARKETS = ("TWSE", "TPEx")
MARKET_ZH = {"TWSE": "上市", "TPEx": "上櫃"}


def _conditions_module():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    from app.strategies import index_conditions

    return index_conditions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index_condition_report.py", description=__doc__
    )
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    return parser


def strategy_versions(con: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    result = {}
    for strategy_id, name, version, kind, config in con.execute(
        "select id, name, version, kind, config_json from strategy_versions"
    ):
        config = json.loads(config) if isinstance(config, str) else (config or {})
        condition = config.get("index_condition") or {}
        result[strategy_id] = {
            "name": name,
            "version": version,
            "kind": kind,
            "base": condition.get("base_strategy") or name,
            "condition": condition.get("condition"),
        }
    return result


def scopes_of(day: date, segment_of) -> tuple[str, ...]:
    segment = segment_of(day)
    return (ALL, quarter(day)) + ((segment,) if segment else ())


def scan(
    con: sqlite3.Connection, prefix: str, versions: Mapping[int, dict], segment_of
):
    """One pass over the run's signals, without ``rule_evidence_json``.

    ``counts[(name, scope)]`` is [rows, data_incomplete, actionable];
    ``actionable[name]`` maps (instrument, signal date) to (signal id, status).
    """

    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    actionable: dict[str, dict[tuple[int, date], tuple[int, str]]] = defaultdict(dict)
    days: dict[str, date] = {}
    for signal_id, strategy_id, day, instrument_id, status in con.execute(
        "select id, strategy_version_id, signal_date, instrument_id, status "
        "from signals where signal_key like ? order by id",
        (prefix,),
    ):
        name = versions[strategy_id]["name"]
        day = days.setdefault(day, date.fromisoformat(day))
        is_actionable = status not in NOT_ACTIONABLE
        for scope in scopes_of(day, segment_of):
            item = counts[(name, scope)]
            item[0] += 1
            item[1] += status == "data_incomplete"
            item[2] += is_actionable
        if is_actionable:
            actionable[name][(instrument_id, day)] = (signal_id, status)
    return {
        "counts": dict(counts),
        "actionable": dict(actionable),
        "days": sorted(days.values()),
    }


def series_rows(con: sqlite3.Connection, series: Mapping[str, tuple[str, str, str]]):
    rows: dict[str, dict[date, tuple[float | None, str | None]]] = {}
    for key, (exchange, symbol, instrument_type) in series.items():
        found = con.execute(
            "select mb.trading_date, mb.close, mb.contract_month from market_bars mb "
            "join instruments i on i.id = mb.instrument_id "
            "where i.exchange = ? and i.symbol = ? and i.instrument_type = ?",
            (exchange, symbol, instrument_type),
        ).fetchall()
        if found:
            rows[key] = {
                date.fromisoformat(d): (close, month) for d, close, month in found
            }
    return rows


def exchanges(con: sqlite3.Connection, ids: Iterable[int]) -> dict[int, str]:
    wanted = set(ids)
    return {
        instrument_id: exchange
        for instrument_id, exchange in con.execute(
            "select id, exchange from instruments"
        )
        if instrument_id in wanted
    }


def _span(points: list[tuple[date, float]]) -> dict[str, Any] | None:
    if not points:
        return None
    return {
        "sessions": len(points),
        "first": points[0],
        "last": points[-1],
        "return": points[-1][1] / points[0][1] - 1.0,
        "max_drawdown": regime_report.max_drawdown(points),
    }


def build(db: Path, run_id: int) -> dict[str, Any]:
    ic = _conditions_module()
    from worker.futures_bars import near_month

    con = regime_report.connect_read_only(db)
    run = con.execute(
        "select id, status, request_key, metadata_json from ingestion_runs "
        "where id = ? and run_type = 'backtest'",
        (run_id,),
    ).fetchone()
    if not run:
        raise SystemExit(f"no backtest run {run_id} in {db}")
    metadata = json.loads(run[3]) if isinstance(run[3], str) else (run[3] or {})
    prefix = f"backtest-{run_id}-%"
    versions = strategy_versions(con)
    scanned = scan(con, prefix, versions, ic.segment_of)
    settled = regime_report.settlements(con, prefix)
    history = ic.IndexHistory(series_rows(con, ic.SERIES))
    markets_of = exchanges(
        con,
        {key[0] for signals in scanned["actionable"].values() for key in signals},
    )
    con.close()

    days = scanned["days"]
    names = metadata.get("research_registry") or sorted(
        {name for name, _scope in scanned["counts"]}
    )
    by_name = {item["name"]: item for item in versions.values()}
    codes = [
        code
        for code in ic.CONDITIONS
        if any(by_name[name]["condition"] == code for name in names)
    ]
    per_market = {code for code in codes if ic.CONDITIONS[code].per_market}
    states: dict[str, dict[str | None, dict[date, str]]] = {}
    for code in codes:
        markets = MARKETS if code in per_market else (None,)
        states[code] = {
            market: {
                day: item.state
                for day, item in history.states(code, days, market).items()
            }
            for market in markets
        }

    def state_of(code: str, key: tuple[int, date]) -> str:
        by_market = states[code]
        market = markets_of.get(key[0]) if code in per_market else None
        if market not in by_market:  # an exchange with no market index
            return "data_incomplete"
        return by_market[market][key[1]]

    quarters = sorted({quarter(day) for day in days})
    segment_codes = [item.code for item in ic.SEGMENTS]
    scopes = (ALL, *segment_codes, *quarters)

    def in_scope(day: date, scope: str) -> bool:
        return scope in scopes_of(day, ic.segment_of)

    def table(name: str, keys: Iterable[tuple[int, date]] | None = None) -> dict:
        signals = scanned["actionable"].get(name, {})
        chosen = signals.values() if keys is None else (signals[k] for k in keys)
        return summarize(chosen, settled)

    strategies: dict[str, Any] = {}
    for base in [name for name in names if by_name[name]["condition"] is None]:
        versions_of = [base] + [
            name for name in names if by_name[name]["base"] == base and name != base
        ]
        result: dict[str, Any] = {
            "versions": {},
            "removed": {},
            "consistency": {},
            "judgement": {},
        }
        for name in versions_of:
            item = {"condition": by_name[name]["condition"], "scopes": {}}
            for scope in scopes:
                rows, incomplete, actionable = scanned["counts"].get(
                    (name, scope), [0, 0, 0]
                )
                keys = None
                if scope != ALL:
                    keys = [
                        key
                        for key in scanned["actionable"].get(name, {})
                        if in_scope(key[1], scope)
                    ]
                summary = table(name, keys)
                assert summary["actionable"] == actionable
                item["scopes"][scope] = {
                    "rows": rows,
                    "data_incomplete": incomplete,
                    **summary,
                }
            result["versions"][name] = item
        baseline = scanned["actionable"].get(base, {})
        for name in versions_of[1:]:
            code = by_name[name]["condition"]
            parts = {state: [] for state in STATES}
            for key in baseline:
                parts[state_of(code, key)].append(key)
            result["removed"][name] = {
                state: {
                    scope: table(base, [k for k in keys if in_scope(k[1], scope)])
                    for scope in scopes
                }
                for state, keys in parts.items()
            }
            own = scanned["actionable"].get(name, {})
            kept = set(parts["passed"])
            mismatched = [
                key
                for key in kept & set(own)
                if baseline[key][1] != own[key][1]
                or settled.get(baseline[key][0]) != settled.get(own[key][0])
            ]
            result["consistency"][name] = {
                "baseline_on_passed_dates": len(kept),
                "condition_actionable": len(own),
                "only_in_baseline": len(kept - set(own)),
                "only_in_condition": len(set(own) - kept),
                "status_or_settlement_differs": len(mismatched),
            }
            judged = {}
            for segment in segment_codes:
                mine = result["versions"][name]["scopes"][segment]
                theirs = result["versions"][base]["scopes"][segment]
                comparison = ic.Comparison(
                    removed=result["removed"][name]["rejected"][segment]["actionable"],
                    t20_n=mine["returns"]["t20"]["n"],
                    t20_median=mine["returns"]["t20"].get("p50"),
                    baseline_t20_median=theirs["returns"]["t20"].get("p50"),
                    invalidated_share=mine["invalidated_share"],
                    baseline_invalidated_share=theirs["invalidated_share"],
                )
                verdict = (
                    ic.judge_exploration(comparison)
                    if segment == ic.EXPLORATION.code
                    else ic.judge_validation(comparison)
                )
                judged[segment] = {
                    **comparison.__dict__,
                    "judgeable": comparison.judgeable,
                    "verdict": verdict,
                }
            judged["proposable"] = (
                judged[ic.EXPLORATION.code]["verdict"] == "selected"
                and judged[ic.VALIDATION.code]["verdict"] == "not_reversed"
            )
            judged["validation_independent"] = ic.CONDITIONS[
                code
            ].validation_independent
            result["judgement"][name] = judged
        strategies[base] = result

    # ---- market ----
    points = {
        key: [
            (day, close)
            for day, close in zip(*history.series(key)[:2])
            if close is not None and close > 0
        ]
        for key in ic.SERIES
    }
    first_day, last_day = (days[0], days[-1]) if days else (None, None)
    spans: dict[str, dict[str, Any]] = {}
    for key, series in points.items():
        spans[key] = {
            "stored": {
                "rows": len(history.series(key)[0]),
                "first": history.series(key)[0][0] if history.series(key)[0] else None,
                "last": history.series(key)[0][-1] if history.series(key)[0] else None,
            }
        }
        for scope in (ALL, *segment_codes):
            chosen = [
                (day, close)
                for day, close in series
                if first_day
                and first_day <= day <= last_day
                and (scope == ALL or ic.segment_of(day) == scope)
            ]
            spans[key][scope] = _span(chosen)
    taiex = dict(points["TAIEX"])
    condition_days: dict[str, dict[str, Any]] = {}
    segment_rows = []
    for code in codes:
        for market, by_day in states[code].items():
            label = code if market is None else f"{code}:{market}"
            entry = {}
            for scope in (ALL, *segment_codes):
                chosen = {
                    day: state
                    for day, state in by_day.items()
                    if scope == ALL or ic.segment_of(day) == scope
                }
                counted = Counter(chosen.values())
                runs = regime_report.segments(chosen)
                entry[scope] = {
                    "days": {state: counted.get(state, 0) for state in STATES},
                    "passed_segments": [
                        run for run in runs if run["state"] == "passed"
                    ],
                }
            condition_days[label] = entry
            segment_rows += [
                (label, run["state"], run["start"], run["end"], run["sessions"])
                for run in regime_report.segments(by_day)
            ]
    rolls = [
        item
        for item in history.rolls()
        if first_day and first_day <= item["first_day"] <= last_day
    ]
    tx_dates, _tx_closes, tx_months = history.series("TX")
    off_month = [
        (day, month)
        for day, month in zip(tx_dates, tx_months)
        if first_day and first_day <= day <= last_day and month != near_month(day)
    ]
    us_alignment = {}
    for key in sorted(ic.US_SERIES):
        us_dates = history.series(key)[0]
        gaps: Counter = Counter()
        same_day = 0
        for day in days:
            at = bisect.bisect_left(us_dates, day)
            if at < len(us_dates) and us_dates[at] == day:
                same_day += 1
            gaps["none" if not at else (day - us_dates[at - 1]).days] += 1
        us_alignment[key] = {
            "gap_days": {str(k): v for k, v in sorted(gaps.items(), key=str)},
            "score_dates_with_a_same_date_us_row_not_read": same_day,
        }

    return {
        "run": {
            "id": run[0],
            "status": run[1],
            "request_key": run[2],
            "start": metadata.get("start_date"),
            "end": metadata.get("end_date"),
            "tracking_version": metadata.get("tracking_version"),
            "score_session_count": metadata.get("score_session_count"),
            "registry": names,
        },
        "split": {
            item.code: {
                "label_zh": item.label_zh,
                "start": item.start,
                "end": item.end or last_day,
                "score_sessions": sum(ic.segment_of(day) == item.code for day in days),
            }
            for item in ic.SEGMENTS
        },
        "selection_rule": {
            "text_zh": ic.SELECTION_RULE_ZH,
            "min_removed": ic.MIN_REMOVED,
            "min_t20": ic.MIN_T20,
        },
        "conditions": {
            code: {
                "definition": ic.CONDITIONS[code].definition,
                "label_zh": ic.CONDITIONS[code].label_zh,
                "reads": ic.CONDITIONS[code].reads,
                "validation_independent": ic.CONDITIONS[code].validation_independent,
                "note_zh": ic.CONDITIONS[code].note_zh,
                "per_market": code in per_market,
            }
            for code in codes
        },
        "market": {
            "series": spans,
            "taiex_quarters": regime_report.market(taiex, days, {})["quarters"],
            "condition_days": condition_days,
            "tx_rolls": rolls,
            "tx_rows_not_near_month": off_month,
            "us_alignment": us_alignment,
        },
        "segment_rows": segment_rows,
        "quarters": quarters,
        "strategies": strategies,
    }


# --- markdown -------------------------------------------------------------

VERDICT_ZH = {
    "selected": "選出",
    "not_selected": "未選出",
    "not_reversed": "沒有反轉",
    "reversed": "反轉",
    "insufficient": "無法判定",
}


def _label(name: str, conditions: Mapping[str, Any], code: str | None) -> str:
    if code is None:
        return f"`{name}`（baseline）"
    return f"`{name}`（{code.upper()}：{conditions[code]['label_zh']}）"


def _cond_label(label: str, conditions: Mapping[str, Any]) -> str:
    code, _, market = label.partition(":")
    text = f"{code.upper()}｜{conditions[code]['label_zh']}"
    return f"{text}（{MARKET_ZH[market]}）" if market else text


def _close(point) -> str:
    return "—" if not point else f"{point[0]} {point[1]:,.2f}"


def _pp(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f} pp"


def markdown(result: dict[str, Any], command: str) -> str:
    run = result["run"]
    conditions = result["conditions"]
    split = result["split"]
    tag = f"run {run['id']}"
    segs = list(split)
    lines = [
        "# 指數條件研究（#567）",
        "",
        f"- run id：`{run['id']}`（{run['status']}）",
        f"- request key：`{run['request_key']}`",
        f"- 範圍：{run['start']}～{run['end']}，{run['score_session_count']} 個交易日；"
        f"追蹤口徑 `{run['tracking_version']}`",
        f"- 重現：`{command}`",
        "- 事先切分（`app.strategies.index_conditions` 的 `EXPLORATION`／`VALIDATION`）："
        + "；".join(
            f"{item['label_zh']} {item['start']}～{item['end']}（{item['score_sessions']} 個交易日）"
            for item in split.values()
        ),
        f"- 判定規則（同模組 `judge_exploration`／`judge_validation`）：{result['selection_rule']['text_zh']}",
        "",
        f"## 指數市況（{tag}）",
        "",
        "| 序列 | 段 | 起 | 迄 | 報酬 | 最大回檔 | 已存列數（起～迄） |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for key, item in result["market"]["series"].items():
        stored = item["stored"]
        stored_text = (
            f"{stored['rows']}（{stored['first']}～{stored['last']}）"
            if stored["rows"]
            else "0"
        )
        for scope in ("all", *segs):
            span = item[scope]
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            if not span:
                lines.append(f"| {key} | {name} | — | — | — | — | {stored_text} |")
                continue
            dd = span["max_drawdown"]
            lines.append(
                f"| {key} | {name} | {_close(span['first'])} | {_close(span['last'])} | "
                f"{pct(span['return'])} | {dd['peak']}→{dd['trough']}（{pct(dd['return'])}） | "
                f"{stored_text} |"
            )
    lines += [
        "",
        "| 季 | 交易日 | TAIEX 季末收盤 | 季報酬 | 季內最大回檔 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, item in result["market"]["taiex_quarters"].items():
        lines.append(
            f"| {key} | {item['sessions']} | {item['last_close']:,.2f} | "
            f"{pct(item['return'])} | {pct(item['max_drawdown']['return'])} |"
        )
    lines += [
        "",
        f"### 各條件為真的天數（{tag}）",
        "",
        "| 條件 | 段 | 成立日 | 不成立日 | 資料不足日 | 成立區段數 | 最長成立區段 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for label, entry in result["market"]["condition_days"].items():
        for scope in ("all", *segs):
            item = entry[scope]
            runs = item["passed_segments"]
            longest = max(runs, key=lambda run: run["sessions"], default=None)
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            lines.append(
                f"| {_cond_label(label, conditions)} | {name} | {item['days']['passed']} | "
                f"{item['days']['rejected']} | {item['days']['data_incomplete']} | {len(runs)} | "
                + (
                    f"{longest['start']}～{longest['end']}（{longest['sessions']} 日）"
                    if longest
                    else "—"
                )
                + " |"
            )
    for label, entry in result["market"]["condition_days"].items():
        runs = entry["all"]["passed_segments"]
        lines += [
            "",
            f"<details><summary>{_cond_label(label, conditions)} 成立區段（{len(runs)} 段）</summary>",
            "",
            ", ".join(f"{r['start']}～{r['end']}（{r['sessions']}）" for r in runs)
            or "無",
            "",
            "</details>",
        ]
    rolls = result["market"]["tx_rolls"]
    jumps = [item["basis_jump"] for item in rolls if "basis_jump" in item]
    lines += [
        "",
        f"### 台指期換月（{tag}）",
        "",
        f"- 範圍內換月 {len(rolls)} 次；近月判定與 `worker.futures_bars.near_month` 不符的列："
        f"{len(result['market']['tx_rows_not_near_month'])}。",
        "- C3 價差用當日近月：換月日用新合約。C3 的 MA20 用已存近月收盤，不跨月調整；"
        "下表的「價差跳動」是新合約首日價差減舊合約末日價差，等於 MA20 窗口裡混到的合約差。",
    ]
    if jumps:
        lines.append(
            f"- 價差跳動：中位 {regime_report.quantile(jumps, 0.5):+,.1f} 點，"
            f"最小 {min(jumps):+,.1f}，最大 {max(jumps):+,.1f}。"
        )
    lines += [
        "",
        "<details><summary>每次換月</summary>",
        "",
        "| 舊合約末日 | 舊合約 | 舊價差 | 新合約首日 | 新合約 | 新價差 | 價差跳動 |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ]
    for item in rolls:
        lines.append(
            f"| {item['last_day']} | {item['last_month']} | {item.get('last_basis', 0):+,.1f} | "
            f"{item['first_day']} | {item['first_month']} | {item.get('first_basis', 0):+,.1f} | "
            f"{item.get('basis_jump', 0):+,.1f} |"
        )
    lines += ["", "</details>", "", f"### 美股日期對齊（{tag}）", ""]
    for key, item in result["market"]["us_alignment"].items():
        gaps = "、".join(
            f"{gap} 天 {count} 日" if gap != "none" else f"沒有前一列 {count} 日"
            for gap, count in item["gap_days"].items()
        )
        lines.append(
            f"- {key}：訊號日與所讀美股列相差 {gaps}；訊號日當天也有美股列（不讀）"
            f" {item['score_dates_with_a_same_date_us_row_not_read']} 日。"
        )

    head = (
        "| 版本 | 列數 | data_incomplete | 可行動 | "
        + " | ".join(STATUSES)
        + " | 其他 | T+5 | T+20 |"
    )
    rule = "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in STATUSES)
    rule += " | ---: | --- | --- |"
    for base, data in result["strategies"].items():
        for scope in (*segs, "all"):
            name = "全範圍" if scope == "all" else split[scope]["label_zh"]
            lines += ["", f"## {base}：{name}（{tag}）", "", head, rule]
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                lines.append(
                    f"| {_label(version, conditions, item['condition'])} | {cell['rows']:,} | "
                    f"{cell['data_incomplete']:,} | {cell['actionable']:,} | "
                    + " | ".join(regime_report._status_cells(cell))
                    + f" | {regime_report._returns(cell['returns']['t5'])} | "
                    f"{regime_report._returns(cell['returns']['t20'])} |"
                )
        lines += [
            "",
            f"### {base}：段別判定（{tag}）",
            "",
            "| 條件 | 段 | 濾掉的可行動 | 研究版 T+20 n | T+20 中位差 | invalidated 差 | 判定 |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for version, judged in data["judgement"].items():
            code = data["versions"][version]["condition"]
            for scope in segs:
                item = judged[scope]
                median_diff = (
                    None
                    if item["t20_median"] is None or item["baseline_t20_median"] is None
                    else item["t20_median"] - item["baseline_t20_median"]
                )
                inv_diff = (
                    None
                    if item["invalidated_share"] is None
                    or item["baseline_invalidated_share"] is None
                    else item["invalidated_share"] - item["baseline_invalidated_share"]
                )
                lines.append(
                    f"| {code.upper()} | {split[scope]['label_zh']} | {item['removed']:,} | "
                    f"{item['t20_n']:,} | {_pp(median_diff)} | {_pp(inv_diff)} | "
                    f"{VERDICT_ZH[item['verdict']]} |"
                )
        lines += [
            "",
            "| 條件 | 兩段都過 | 驗證段獨立 | 說明 |",
            "| --- | --- | --- | --- |",
        ]
        for version, judged in data["judgement"].items():
            code = data["versions"][version]["condition"]
            lines.append(
                f"| {code.upper()} | {'是' if judged['proposable'] else '否'} | "
                f"{'是' if judged['validation_independent'] else '否'} | "
                f"{conditions[code]['note_zh'] or '—'} |"
            )
        lines += [
            "",
            f"### {base}：逐季（{tag}）",
            "",
            "| 季 | 版本 | 可行動 | invalidated | T+5 中位（n） | T+20 中位（n） |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for scope in result["quarters"]:
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                t5, t20 = cell["returns"]["t5"], cell["returns"]["t20"]
                lines.append(
                    f"| {scope} | {(item['condition'] or 'baseline').upper()} | "
                    f"{cell['actionable']:,} | "
                    f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                    f" | {pct(t5.get('p50'))}（{t5['n']:,}） | "
                    f"{pct(t20.get('p50'))}（{t20['n']:,}） |"
                )
        lines += [
            "",
            f"### {base}：條件濾掉了什麼（baseline 的可行動訊號依訊號日、所屬市場的條件狀態分組，{tag}）",
            "",
            "| 條件 | 段 | 訊號日條件 | 可行動 | invalidated | target_1_hit＋target_2_hit | T+5 | T+20 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for version, parts in data["removed"].items():
            code = data["versions"][version]["condition"]
            for scope in segs:  # the whole range is in tables.json
                name = "全範圍" if scope == "all" else split[scope]["label_zh"]
                for state in STATES:
                    cell = parts[state][scope]
                    hits = cell["statuses"].get("target_1_hit", 0) + cell[
                        "statuses"
                    ].get("target_2_hit", 0)
                    lines.append(
                        f"| {code.upper()} | {name} | {STATE_ZH[state]} | {cell['actionable']:,} | "
                        f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                        f" | {share(hits, cell['actionable'])} | "
                        f"{regime_report._returns(cell['returns']['t5'])} | "
                        f"{regime_report._returns(cell['returns']['t20'])} |"
                    )
        lines += [
            "",
            f"### {base}：條件為真時與 baseline 一致的核對（{tag}）",
            "",
            "| 版本 | baseline 在成立日的可行動 | 研究版本可行動 | 只在 baseline | 只在研究版本 | 狀態或結算不同 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for version, item in data["consistency"].items():
            lines.append(
                f"| `{version}` | {item['baseline_on_passed_dates']:,} | "
                f"{item['condition_actionable']:,} | {item['only_in_baseline']:,} | "
                f"{item['only_in_condition']:,} | {item['status_or_settlement_differs']:,} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = _load("backtest_research").production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(db, args.run_id)
    command = "python tools/research/index_condition_report.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    with (out / "segments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["condition", "state", "start", "end", "sessions"])
        writer.writerows(result["segment_rows"])
    print(
        json.dumps(
            {"out": str(out.resolve()), "run": result["run"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
