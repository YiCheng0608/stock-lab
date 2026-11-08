"""Tables of one regime research backtest run (#546), read only.

Reads the database ``--db`` (the copy the ``backtest_research.py --regime``
run wrote) through a ``mode=ro`` connection with ``query_only`` on, and
writes to ``--out``:

- ``summary.md``: the tables of the #546 report;
- ``tables.json``: the same numbers, with the run id and request key;
- ``segments.csv``: every run of consecutive score dates with one filter state.

For each registered strategy of the run (the baseline) and each of its regime
strategies (``app.strategies.regime``), over the whole range and per calendar
quarter of the signal date:

- rows (one per instrument and session), ``data_incomplete`` rows and
  actionable signals (status not ``observation``／``data_incomplete``／
  ``invalid_levels``: tracking moves a conditional signal on);
- the tracking status of the actionable signals (口徑 ``tracking_v2``: the
  run's ``tracking_version``);
- the T+5／T+20 comparable settlement returns, less the ones still
  ``not_triggered`` at T+N (as ``research_report.py``: a fill after T+N is no
  T+N return).

Then the baseline's actionable signals split by the filter's state on their
signal date (kept, filter failed, TAIEX data incomplete): what each filter
removes; a check that each regime strategy's actionable signals are the
baseline's on the dates its filter holds, with the same status and
settlements; and TAIEX over the run's score dates (first and last close,
largest drawdown, the quarter returns, each filter's days and segments),
from the same ``market_bars`` closes the filters read.

Refuses the production database as ``backtest_research.py`` does.  Never
writes the database.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (5, 20)
NOT_ACTIONABLE = ("observation", "data_incomplete", "invalid_levels")
# Tracking statuses the report names (``conditional``: not filled by the run's
# cutoff); any other one is counted under 「其他」.
STATUSES = (
    "target_2_hit",
    "target_1_hit",
    "invalidated",
    "active",
    "incomparable",
    "expired",
    "conditional",
)
STATES = ("passed", "rejected", "data_incomplete")
STATE_ZH = {"passed": "成立", "rejected": "不成立", "data_incomplete": "資料不足"}
ALL = "all"


def _research_module():
    spec = importlib.util.spec_from_file_location(
        "backtest_research", ROOT / "tools" / "research" / "backtest_research.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _regime_module():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    from app.strategies import regime

    return regime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="regime_report.py", description=__doc__)
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    return parser


def connect_read_only(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    return con


def quantile(values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""

    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        **{f"p{round(q * 100):02d}": quantile(values, q) for q in (0.1, 0.25, 0.5)},
        **{f"p{round(q * 100):02d}": quantile(values, q) for q in (0.75, 0.9)},
        "positive_share": sum(value > 0 for value in values) / len(values),
    }


def quarter(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def max_drawdown(points: Sequence[tuple[date, float]]) -> dict[str, Any] | None:
    """The largest fall from a close to a later one: peak, trough, return."""

    if not points:
        return None
    peak_day, peak = points[0]
    worst = {"peak": peak_day, "peak_close": peak, "trough": peak_day}
    worst |= {"trough_close": peak, "return": 0.0}
    for day, close in points:
        if close > peak:
            peak_day, peak = day, close
        change = close / peak - 1.0
        if change < worst["return"]:
            worst = {
                "peak": peak_day,
                "peak_close": peak,
                "trough": day,
                "trough_close": close,
                "return": change,
            }
    return worst


def segments(states: Mapping[date, str]) -> list[dict[str, Any]]:
    """Runs of consecutive dates (in ``states``' order) with one state."""

    result: list[dict[str, Any]] = []
    for day in sorted(states):
        state = states[day]
        if result and result[-1]["state"] == state:
            result[-1]["end"] = day
            result[-1]["sessions"] += 1
        else:
            result.append({"state": state, "start": day, "end": day, "sessions": 1})
    return result


def usable_return(settlement: tuple | None) -> float | None:
    """A T+N return the report counts; None for none (module docstring)."""

    if settlement is None:
        return None
    comparable, value, status = settlement
    if not comparable or value is None or status == "not_triggered":
        return None
    return float(value)


def summarize(
    signals: Iterable[tuple[int, str]],
    settled: Mapping[int, Mapping[int, tuple]],
) -> dict[str, Any]:
    """Status counts and T+N return distributions of ``(signal id, status)``."""

    statuses: Counter = Counter()
    returns: dict[int, list[float]] = {horizon: [] for horizon in HORIZONS}
    excluded: Counter = Counter()
    count = 0
    for signal_id, status in signals:
        count += 1
        statuses[status] += 1
        for horizon in HORIZONS:
            settlement = settled.get(signal_id, {}).get(horizon)
            value = usable_return(settlement)
            if value is None:
                excluded[horizon] += 1
            else:
                returns[horizon].append(value)
    return {
        "actionable": count,
        "statuses": dict(statuses),
        "invalidated_share": statuses["invalidated"] / count if count else None,
        "returns": {
            f"t{horizon}": distribution(values) for horizon, values in returns.items()
        },
        "returns_excluded": {f"t{h}": excluded[h] for h in HORIZONS},
    }


def strategy_versions(con: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    result = {}
    for strategy_id, name, version, kind, config in con.execute(
        "select id, name, version, kind, config_json from strategy_versions"
    ):
        config = json.loads(config) if isinstance(config, str) else (config or {})
        regime = config.get("regime_filter") or {}
        result[strategy_id] = {
            "name": name,
            "version": version,
            "kind": kind,
            "base": regime.get("base_strategy") or name,
            "filter": regime.get("filter"),
        }
    return result


def scan(con: sqlite3.Connection, prefix: str, versions: Mapping[int, dict]) -> dict:
    """One pass over the run's signals, without ``rule_evidence_json``.

    ``counts[(name, scope)]`` is [rows, data_incomplete, actionable] for the
    scope ``all`` and each quarter; ``actionable[name]`` maps (instrument,
    signal date) to (signal id, status).
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
        for scope in (ALL, quarter(day)):
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


def settlements(con: sqlite3.Connection, prefix: str) -> dict[int, dict[int, tuple]]:
    """``signal id -> horizon -> (comparable, return, final status)``."""

    result: dict[int, dict[int, tuple]] = defaultdict(dict)
    for signal_id, horizon, comparable, value, status in con.execute(
        "select st.signal_id, st.horizon, st.comparable, st.return_or_risk, "
        "st.final_status from signal_settlements st "
        "cross join signals s on s.id = st.signal_id where s.signal_key like ?",
        (prefix,),
    ):
        result[signal_id][horizon] = (bool(comparable), value, status)
    return dict(result)


def taiex_closes(con: sqlite3.Connection) -> dict[date, float | None]:
    rows = con.execute(
        "select mb.trading_date, mb.close from market_bars mb "
        "join instruments i on i.id = mb.instrument_id "
        "where i.symbol = 'TAIEX' and i.instrument_type = 'index' "
        "and i.status = 'active'"
    ).fetchall()
    return {date.fromisoformat(day): close for day, close in rows}


def market(
    closes: Mapping[date, float | None],
    days: Sequence[date],
    states: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    points = [(day, closes[day]) for day in days if closes.get(day)]
    by_quarter: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for day, close in points:
        by_quarter[quarter(day)].append((day, close))
    quarters = {}
    previous = None
    for key in sorted(by_quarter):
        rows = by_quarter[key]
        base = previous if previous is not None else rows[0][1]
        quarters[key] = {
            "sessions": len(rows),
            "first_close": rows[0][1],
            "last_close": rows[-1][1],
            "return": rows[-1][1] / base - 1.0,
            "return_basis": "previous_quarter_last_close"
            if previous is not None
            else "first_close_in_range",
            "max_drawdown": max_drawdown(rows),
        }
        previous = rows[-1][1]
    filters = {}
    for code, by_day in states.items():
        counted = Counter(by_day.values())
        runs = segments(by_day)
        filters[code] = {
            "days": {state: counted.get(state, 0) for state in STATES},
            "passed_segments": [run for run in runs if run["state"] == "passed"],
            "segments": runs,
        }
    return {
        "sessions": len(days),
        "first": points[0] if points else None,
        "last": points[-1] if points else None,
        "return": points[-1][1] / points[0][1] - 1.0 if points else None,
        "max_drawdown": max_drawdown(points),
        "missing_sessions": [day for day in days if not closes.get(day)],
        "quarters": quarters,
        "filters": filters,
    }


def build(db: Path, run_id: int) -> dict[str, Any]:
    regime = _regime_module()
    con = connect_read_only(db)
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
    scanned = scan(con, prefix, versions)
    settled = settlements(con, prefix)
    closes = regime.TaiexCloses(taiex_closes(con))
    con.close()

    days = scanned["days"]
    names = metadata.get("research_registry") or sorted(
        {name for name, _scope in scanned["counts"]}
    )
    by_name = {item["name"]: item for item in versions.values()}
    codes = sorted(
        {by_name[name]["filter"] for name in names if by_name[name]["filter"]}
    )
    states = {
        code: {day: item.state for day, item in closes.states(code, days).items()}
        for code in codes
    }
    quarters = sorted({quarter(day) for day in days})

    def table(name: str, keys: Iterable[tuple[int, date]] | None = None) -> dict:
        signals = scanned["actionable"].get(name, {})
        chosen = signals.values() if keys is None else (signals[k] for k in keys)
        return summarize(chosen, settled)

    strategies: dict[str, Any] = {}
    for base in [name for name in names if by_name[name]["filter"] is None]:
        versions_of = [base] + [
            name for name in names if by_name[name]["base"] == base and name != base
        ]
        result: dict[str, Any] = {"versions": {}, "removed": {}, "consistency": {}}
        for name in versions_of:
            item = {"filter": by_name[name]["filter"], "scopes": {}}
            for scope in (ALL, *quarters):
                rows, incomplete, actionable = scanned["counts"].get(
                    (name, scope), [0, 0, 0]
                )
                keys = None
                if scope != ALL:
                    keys = [
                        key
                        for key in scanned["actionable"].get(name, {})
                        if quarter(key[1]) == scope
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
            code = by_name[name]["filter"]
            parts = {
                state: [key for key in baseline if states[code][key[1]] == state]
                for state in STATES
            }
            result["removed"][name] = {
                state: {
                    scope: table(
                        base,
                        [k for k in keys if scope == ALL or quarter(k[1]) == scope],
                    )
                    for scope in (ALL, *quarters)
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
                "regime_actionable": len(own),
                "only_in_baseline": len(kept - set(own)),
                "only_in_regime": len(set(own) - kept),
                "status_or_settlement_differs": len(mismatched),
            }
        strategies[base] = result

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
        "filters": {
            code: {
                "definition": regime.FILTERS[code].definition,
                "label_zh": regime.FILTERS[code].label_zh,
                "required_closes": regime.FILTERS[code].required_closes,
            }
            for code in codes
        },
        "market": market(dict(zip(closes.dates, closes.closes)), days, states),
        "quarters": quarters,
        "strategies": strategies,
    }


# --- markdown -------------------------------------------------------------


def pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def share(part: int, whole: int) -> str:
    return "—" if not whole else f"{part / whole * 100:.1f}%"


def _returns(cell: dict[str, Any]) -> str:
    if not cell.get("n"):
        return "n=0"
    return (
        f"n={cell['n']:,}｜中位 {pct(cell['p50'])}｜P25 {pct(cell['p25'])}"
        f"｜P75 {pct(cell['p75'])}｜>0 {cell['positive_share'] * 100:.1f}%"
    )


def _status_cells(item: dict[str, Any]) -> list[str]:
    count = item["actionable"]
    statuses = item["statuses"]
    cells = [
        f"{statuses.get(s, 0):,}（{share(statuses.get(s, 0), count)}）"
        for s in STATUSES
    ]
    other = sum(v for k, v in statuses.items() if k not in STATUSES)
    return [*cells, f"{other:,}"]


def _label(name: str, filters: Mapping[str, Any], filter_code: str | None) -> str:
    if filter_code is None:
        return f"`{name}`（baseline）"
    return f"`{name}`（{filter_code.upper()}：{filters[filter_code]['label_zh']}）"


def markdown(result: dict[str, Any], command: str) -> str:
    run = result["run"]
    filters = result["filters"]
    tag = f"run {run['id']}"
    lines = [
        "# 大盤狀態濾網研究（#546）",
        "",
        f"- run id：`{run['id']}`（{run['status']}）",
        f"- request key：`{run['request_key']}`",
        f"- 範圍：{run['start']}～{run['end']}，{run['score_session_count']} 個交易日；"
        f"追蹤口徑 `{run['tracking_version']}`",
        f"- 重現：`{command}`",
        "",
        "## TAIEX 市況（" + tag + "）",
        "",
    ]
    m = result["market"]
    if m["first"]:
        (d0, c0), (d1, c1) = m["first"], m["last"]
        dd = m["max_drawdown"]
        lines += [
            f"- 起訖收盤：{d0} {c0:,.2f} → {d1} {c1:,.2f}（{pct(m['return'])}）",
            f"- 最大回檔：{dd['peak']} {dd['peak_close']:,.2f} → {dd['trough']} "
            f"{dd['trough_close']:,.2f}（{pct(dd['return'])}）",
            f"- 缺 TAIEX 收盤的交易日：{len(m['missing_sessions'])}",
            "",
            "| 季 | 交易日 | 季末收盤 | 季報酬 | 季內最大回檔 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for key, item in m["quarters"].items():
            lines.append(
                f"| {key} | {item['sessions']} | {item['last_close']:,.2f} | "
                f"{pct(item['return'])} | {pct(item['max_drawdown']['return'])} |"
            )
    lines += [
        "",
        "| 濾網 | 定義 | 成立日 | 不成立日 | 資料不足日 | 成立區段數 | 最長成立區段 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for code, item in m["filters"].items():
        runs = item["passed_segments"]
        longest = max(runs, key=lambda run: run["sessions"], default=None)
        lines.append(
            f"| {code.upper()} | {filters[code]['label_zh']}（需 "
            f"{filters[code]['required_closes']} 根） | {item['days']['passed']} | "
            f"{item['days']['rejected']} | {item['days']['data_incomplete']} | "
            f"{len(runs)} | "
            + (
                f"{longest['start']}～{longest['end']}（{longest['sessions']} 日）"
                if longest
                else "—"
            )
            + " |"
        )
    for code, item in m["filters"].items():
        lines += [
            "",
            f"<details><summary>{code.upper()} 成立區段（{len(item['passed_segments'])} 段）"
            "</summary>",
            "",
            ", ".join(
                f"{run['start']}～{run['end']}（{run['sessions']}）"
                for run in item["passed_segments"]
            )
            or "無",
            "",
            "</details>",
        ]

    head = (
        "| 版本 | 列數 | data_incomplete | 可行動 | "
        + " | ".join(STATUSES)
        + " | 其他 | T+5 | T+20 |"
    )
    rule = "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in STATUSES)
    rule += " | ---: | --- | --- |"
    for base, data in result["strategies"].items():
        lines += ["", f"## {base}：全範圍（{tag}）", "", head, rule]
        for name, item in data["versions"].items():
            cell = item["scopes"][ALL]
            lines.append(
                f"| {_label(name, filters, item['filter'])} | {cell['rows']:,} | "
                f"{cell['data_incomplete']:,} | {cell['actionable']:,} | "
                + " | ".join(_status_cells(cell))
                + f" | {_returns(cell['returns']['t5'])} | "
                f"{_returns(cell['returns']['t20'])} |"
            )
        lines += [
            "",
            f"### {base}：逐季（{tag}）",
            "",
            "| 季 | 版本 | 可行動 | invalidated | T+5 中位（n） | T+20 中位（n） |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for scope in result["quarters"]:
            for name, item in data["versions"].items():
                cell = item["scopes"][scope]
                t5, t20 = cell["returns"]["t5"], cell["returns"]["t20"]
                lines.append(
                    f"| {scope} | {(item['filter'] or 'baseline').upper()} | "
                    f"{cell['actionable']:,} | "
                    f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                    f" | {pct(t5.get('p50'))}（{t5['n']:,}） | "
                    f"{pct(t20.get('p50'))}（{t20['n']:,}） |"
                )
        lines += [
            "",
            f"### {base}：濾網省掉了什麼（baseline 的可行動訊號依訊號日濾網狀態分組，{tag}）",
            "",
            "| 濾網 | 訊號日濾網 | 可行動 | invalidated | target_1_hit＋target_2_hit | T+5 | T+20 |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for name, parts in data["removed"].items():
            code = data["versions"][name]["filter"]
            for state in STATES:
                cell = parts[state][ALL]
                hits = cell["statuses"].get("target_1_hit", 0) + cell["statuses"].get(
                    "target_2_hit", 0
                )
                lines.append(
                    f"| {code.upper()} | {STATE_ZH[state]} | {cell['actionable']:,} | "
                    f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])}"
                    f" | {share(hits, cell['actionable'])} | "
                    f"{_returns(cell['returns']['t5'])} | {_returns(cell['returns']['t20'])} |"
                )
        lines += [
            "",
            f"### {base}：濾網為真時與 baseline 一致的核對（{tag}）",
            "",
            "| 版本 | baseline 在成立日的可行動 | 研究版本可行動 | 只在 baseline | 只在研究版本 | 狀態或結算不同 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, item in data["consistency"].items():
            lines.append(
                f"| `{name}` | {item['baseline_on_passed_dates']:,} | "
                f"{item['regime_actionable']:,} | {item['only_in_baseline']:,} | "
                f"{item['only_in_regime']:,} | {item['status_or_settlement_differs']:,} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = _research_module().production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = build(db, args.run_id)
    command = "python tools/research/regime_report.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    with (out / "segments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filter", "state", "start", "end", "sessions"])
        for code, item in result["market"]["filters"].items():
            writer.writerows(
                (code, run["state"], run["start"], run["end"], run["sessions"])
                for run in item["segments"]
            )
    print(
        json.dumps(
            {"out": str(out.resolve()), "run": result["run"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
