"""Tables of one aggressive-version research backtest run (#598), read only.

Reads the database ``--db`` (the copy the ``backtest_research.py
--aggressive`` run wrote) through a ``mode=ro`` connection with
``query_only`` on, and writes ``summary.md`` and ``tables.json`` to ``--out``.

The sample split is ``app.strategies.aggressive``' ``EXPLORATION``／
``VALIDATION`` (#567's), fixed before any result was read.  For each base
(``breakout_v3``, ``pullback_v4``) and each of its versions, for both
segments, the whole range and each calendar quarter of the signal date:

- rows, ``data_incomplete`` rows and actionable signals (status not
  ``observation``／``data_incomplete``／``invalid_levels``);
- the tracking status of the actionable signals (the run's
  ``tracking_version``) and the T+5／T+20 comparable settlement returns,
  less the ones still ``not_triggered`` at T+N (``regime_report.summarize``);
- the added signals (多出來的訊號): a version's actionable instrument-days
  its base did not judge actionable, with the same tables;
- a check that every actionable baseline signal is actionable in the
  version with the same status and settlements; any that is not is listed
  with the version's status and reasons (a relaxation should never drop one);
- the segment judgement of ``judge_exploration``／``judge_validation`` on the
  added signals, and, as #567 read its versions, the whole version against
  its baseline: both are reported when they disagree.

Refuses the production database as ``backtest_research.py`` does.  Never
writes the database.
"""

from __future__ import annotations

import argparse
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
NOT_ACTIONABLE = regime_report.NOT_ACTIONABLE
quarter = regime_report.quarter
summarize = regime_report.summarize
pct = regime_report.pct
share = regime_report.share
VERDICT_ZH = {
    "selected": "選出",
    "not_selected": "未選出",
    "not_reversed": "沒有反轉",
    "reversed": "反轉",
    "insufficient": "無法判定",
}


def _aggressive_module():
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    from app.strategies import aggressive

    return aggressive


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aggressive_report.py", description=__doc__)
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
        item = config.get("aggressive") or {}
        result[strategy_id] = {
            "name": name,
            "version": version,
            "kind": kind,
            "base": item.get("base_strategy") or name,
            "variant": item.get("variant"),
            "label_zh": item.get("label_zh"),
            "changes": item.get("changes"),
        }
    return result


def scopes_of(day: date, segment_of) -> tuple[str, ...]:
    segment = segment_of(day)
    return (ALL, quarter(day)) + ((segment,) if segment else ())


def scan(
    con: sqlite3.Connection, prefix: str, versions: Mapping[int, dict], segment_of
):
    """``index_condition_report.scan``: counts, actionable signals, score dates."""

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


def dropped_rows(
    con: sqlite3.Connection,
    prefix: str,
    strategy_id: int,
    kind: str,
    keys: Iterable[tuple[int, date]],
) -> list[dict[str, Any]]:
    """The version's rows of ``keys`` (baseline signals it did not keep), with their reasons."""

    rows = []
    for instrument_id, day in sorted(keys):
        found = con.execute(
            "select id, status, rule_evidence_json from signals "
            "where signal_key like ? and strategy_version_id = ? "
            "and instrument_id = ? and signal_date = ?",
            (prefix, strategy_id, instrument_id, day.isoformat()),
        ).fetchone()
        if found is None:
            rows.append(
                {"instrument_id": instrument_id, "signal_date": day, "row": None}
            )
            continue
        evidence = json.loads(found[2]) if isinstance(found[2], str) else {}
        own = (evidence or {}).get(kind) or {}
        rows.append(
            {
                "instrument_id": instrument_id,
                "signal_date": day,
                "signal_id": found[0],
                "status": found[1],
                "state": own.get("state"),
                "reasons": own.get("reasons"),
            }
        )
    return rows


def build(db: Path, run_id: int) -> dict[str, Any]:
    ag = _aggressive_module()
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
    scanned = scan(con, prefix, versions, ag.segment_of)
    settled = regime_report.settlements(con, prefix)
    taiex = regime_report.taiex_closes(con)

    days = scanned["days"]
    names = metadata.get("research_registry") or sorted(
        {name for name, _scope in scanned["counts"]}
    )
    by_name = {item["name"]: item for item in versions.values()}
    id_of = {item["name"]: key for key, item in versions.items()}
    quarters = sorted({quarter(day) for day in days})
    segment_codes = [item.code for item in ag.SEGMENTS]
    scopes = (ALL, *segment_codes, *quarters)

    def in_scope(day: date, scope: str) -> bool:
        return scope in scopes_of(day, ag.segment_of)

    def table(signals: Mapping[tuple[int, date], tuple[int, str]], scope: str):
        return summarize(
            (value for key, value in signals.items() if in_scope(key[1], scope)),
            settled,
        )

    strategies: dict[str, Any] = {}
    for base in [name for name in names if by_name[name]["variant"] is None]:
        versions_of = [base] + [
            name for name in names if by_name[name]["base"] == base and name != base
        ]
        baseline = scanned["actionable"].get(base, {})
        result: dict[str, Any] = {
            "versions": {},
            "added": {},
            "consistency": {},
            "judgement": {},
        }
        for name in versions_of:
            signals = scanned["actionable"].get(name, {})
            item = {
                "variant": by_name[name]["variant"],
                "label_zh": by_name[name]["label_zh"],
                "changes": by_name[name]["changes"],
                "scopes": {},
            }
            for scope in scopes:
                rows, incomplete, actionable = scanned["counts"].get(
                    (name, scope), [0, 0, 0]
                )
                summary = table(signals, scope)
                assert summary["actionable"] == actionable
                item["scopes"][scope] = {
                    "rows": rows,
                    "data_incomplete": incomplete,
                    **summary,
                }
            result["versions"][name] = item
        for name in versions_of[1:]:
            own = scanned["actionable"].get(name, {})
            added = {key: value for key, value in own.items() if key not in baseline}
            result["added"][name] = {scope: table(added, scope) for scope in scopes}
            missing = set(baseline) - set(own)
            differs = [
                key
                for key in set(baseline) & set(own)
                if baseline[key][1] != own[key][1]
                or settled.get(baseline[key][0]) != settled.get(own[key][0])
            ]
            result["consistency"][name] = {
                "baseline_actionable": len(baseline),
                "version_actionable": len(own),
                "added": len(added),
                "baseline_not_in_version": len(missing),
                "status_or_settlement_differs": len(differs),
                "dropped": dropped_rows(
                    con, prefix, id_of[name], by_name[name]["kind"], missing
                ),
                "differs": sorted(differs)[:50],
            }
            judged: dict[str, Any] = {}
            for segment in segment_codes:
                mine = result["added"][name][segment]
                whole = result["versions"][name]["scopes"][segment]
                theirs = result["versions"][base]["scopes"][segment]
                comparison = ag.Comparison(
                    added=mine["actionable"],
                    added_t20_n=mine["returns"]["t20"]["n"],
                    added_t20_median=mine["returns"]["t20"].get("p50"),
                    baseline_t20_median=theirs["returns"]["t20"].get("p50"),
                    added_invalidated_share=mine["invalidated_share"],
                    baseline_invalidated_share=theirs["invalidated_share"],
                )
                exploring = segment == ag.EXPLORATION.code
                verdict = (
                    ag.judge_exploration(comparison)
                    if exploring
                    else ag.judge_validation(comparison)
                )
                # #567's reading: the whole version against its baseline.
                version_cmp = ag.Comparison(
                    added=mine["actionable"],
                    added_t20_n=whole["returns"]["t20"]["n"],
                    added_t20_median=whole["returns"]["t20"].get("p50"),
                    baseline_t20_median=theirs["returns"]["t20"].get("p50"),
                    added_invalidated_share=whole["invalidated_share"],
                    baseline_invalidated_share=theirs["invalidated_share"],
                )
                version_verdict = (
                    ag.judge_exploration(version_cmp)
                    if exploring
                    else ag.judge_validation(version_cmp)
                )
                judged[segment] = {
                    **comparison.__dict__,
                    "version_t20_n": whole["returns"]["t20"]["n"],
                    "version_t20_median": whole["returns"]["t20"].get("p50"),
                    "version_invalidated_share": whole["invalidated_share"],
                    "judgeable": comparison.judgeable,
                    "verdict": verdict,
                    "version_verdict": version_verdict,
                }
            judged["proposable"] = (
                judged[ag.EXPLORATION.code]["verdict"] == "selected"
                and judged[ag.VALIDATION.code]["verdict"] == "not_reversed"
            )
            judged["version_proposable"] = (
                judged[ag.EXPLORATION.code]["version_verdict"] == "selected"
                and judged[ag.VALIDATION.code]["version_verdict"] == "not_reversed"
            )
            result["judgement"][name] = judged
        strategies[base] = result
    con.close()

    market = regime_report.market(taiex, days, {})
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
                "end": item.end or (days[-1] if days else None),
                "score_sessions": sum(ag.segment_of(day) == item.code for day in days),
            }
            for item in ag.SEGMENTS
        },
        "selection_rule": {
            "text_zh": ag.SELECTION_RULE_ZH,
            "min_added": ag.MIN_ADDED,
            "min_added_t20": ag.MIN_ADDED_T20,
        },
        "market": {
            "first": market["first"],
            "last": market["last"],
            "return": market["return"],
            "max_drawdown": market["max_drawdown"],
            "taiex_quarters": market["quarters"],
            "missing_sessions": market["missing_sessions"],
        },
        "quarters": quarters,
        "strategies": strategies,
    }


# --- markdown -------------------------------------------------------------


def _pp(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f} pp"


def _label(name: str, item: Mapping[str, Any]) -> str:
    if item["variant"] is None:
        return f"`{name}`（baseline）"
    return f"`{name}`（{item['label_zh']}）"


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def markdown(result: dict[str, Any], command: str) -> str:
    run = result["run"]
    split = result["split"]
    tag = f"run {run['id']}"
    segs = list(split)
    market = result["market"]
    lines = [
        "# 積極型研究（#598）",
        "",
        f"- run id：`{run['id']}`（{run['status']}）",
        f"- request key：`{run['request_key']}`",
        f"- 範圍：{run['start']}～{run['end']}，{run['score_session_count']} 個交易日；"
        f"追蹤口徑 `{run['tracking_version']}`",
        f"- 重現：`{command}`",
        "- 事先切分（`app.strategies.aggressive` 的 `EXPLORATION`／`VALIDATION`，同 #567）："
        + "；".join(
            f"{item['label_zh']} {item['start']}～{item['end']}（{item['score_sessions']} 個交易日）"
            for item in split.values()
        ),
        f"- 判定規則（同模組 `judge_exploration`／`judge_validation`）：{result['selection_rule']['text_zh']}",
        "",
        f"## TAIEX（{tag}）",
        "",
    ]
    if market["first"]:
        dd = market["max_drawdown"]
        lines.append(
            f"- {market['first'][0]} {market['first'][1]:,.2f} → {market['last'][0]} "
            f"{market['last'][1]:,.2f}（{pct(market['return'])}）；最大回檔 "
            f"{dd['peak']}→{dd['trough']}（{pct(dd['return'])}）"
        )
    lines += [
        "",
        "| 季 | 交易日 | TAIEX 季末收盤 | 季報酬 | 季內最大回檔 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, item in market["taiex_quarters"].items():
        lines.append(
            f"| {key} | {item['sessions']} | {item['last_close']:,.2f} | "
            f"{pct(item['return'])} | {pct(item['max_drawdown']['return'])} |"
        )

    head = (
        "| 版本 | 列數 | data_incomplete | 可行動 | "
        + " | ".join(STATUSES)
        + " | 其他 | T+5 | T+20 |"
    )
    rule = "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in STATUSES)
    rule += " | ---: | --- | --- |"
    added_head = (
        "| 版本 | 多出來的可行動 | " + " | ".join(STATUSES) + " | 其他 | T+5 | T+20 |"
    )
    added_rule = "| --- | ---: | " + " | ".join("---:" for _ in STATUSES)
    added_rule += " | ---: | --- | --- |"
    for base, data in result["strategies"].items():
        for scope in (*segs, ALL):
            name = "全範圍" if scope == ALL else split[scope]["label_zh"]
            lines += ["", f"## {base}：{name}（{tag}）", "", head, rule]
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                lines.append(
                    f"| {_label(version, item)} | {cell['rows']:,} | "
                    f"{cell['data_incomplete']:,} | {cell['actionable']:,} | "
                    + " | ".join(regime_report._status_cells(cell))
                    + f" | {regime_report._returns(cell['returns']['t5'])} | "
                    f"{regime_report._returns(cell['returns']['t20'])} |"
                )
            lines += [
                "",
                f"### {base}：{name}，多出來的訊號（{tag}）",
                "",
                added_head,
                added_rule,
            ]
            for version, parts in data["added"].items():
                cell = parts[scope]
                lines.append(
                    f"| `{version}` | {cell['actionable']:,} | "
                    + " | ".join(regime_report._status_cells(cell))
                    + f" | {regime_report._returns(cell['returns']['t5'])} | "
                    f"{regime_report._returns(cell['returns']['t20'])} |"
                )
        lines += [
            "",
            f"### {base}：段別判定（{tag}）",
            "",
            "左半是「多出來那組」對 baseline（判定規則），右半是整個版本對 baseline（#567 的看法）。",
            "",
            "| 版本 | 段 | 多出來 | 多出來 T+20 n | 多出來 − baseline：T+20 中位／invalidated | 判定 | "
            "整個版本 − baseline：T+20 中位／invalidated | 整個版本的判定 |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
        ]
        for version, judged in data["judgement"].items():
            for scope in segs:
                item = judged[scope]
                lines.append(
                    f"| `{version}` | {split[scope]['label_zh']} | {item['added']:,} | "
                    f"{item['added_t20_n']:,} | "
                    f"{_pp(_diff(item['added_t20_median'], item['baseline_t20_median']))}／"
                    f"{_pp(_diff(item['added_invalidated_share'], item['baseline_invalidated_share']))} | "
                    f"{VERDICT_ZH[item['verdict']]} | "
                    f"{_pp(_diff(item['version_t20_median'], item['baseline_t20_median']))}／"
                    f"{_pp(_diff(item['version_invalidated_share'], item['baseline_invalidated_share']))} | "
                    f"{VERDICT_ZH[item['version_verdict']]} |"
                )
        lines += [
            "",
            "| 版本 | 兩段都過（多出來那組） | 兩段都過（整個版本） |",
            "| --- | --- | --- |",
        ]
        for version, judged in data["judgement"].items():
            lines.append(
                f"| `{version}` | {'是' if judged['proposable'] else '否'} | "
                f"{'是' if judged['version_proposable'] else '否'} |"
            )
        lines += [
            "",
            f"### {base}：逐季（{tag}）",
            "",
            "| 季 | 版本 | 可行動 | 多出來 | invalidated | 多出來的 invalidated | T+5 中位（n） | T+20 中位（n） | 多出來的 T+20 中位（n） |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for scope in result["quarters"]:
            for version, item in data["versions"].items():
                cell = item["scopes"][scope]
                extra = data["added"].get(version, {}).get(scope)
                t5, t20 = cell["returns"]["t5"], cell["returns"]["t20"]
                if extra is None:
                    added_cells = "— | — | —"
                else:
                    et20 = extra["returns"]["t20"]
                    added_cells = (
                        f"{extra['actionable']:,} | "
                        f"{share(extra['statuses'].get('invalidated', 0), extra['actionable'])} | "
                        f"{pct(et20.get('p50'))}（{et20['n']:,}）"
                    )
                first, second, third = added_cells.split(" | ")
                lines.append(
                    f"| {scope} | {(item['variant'] or 'baseline').upper()} | "
                    f"{cell['actionable']:,} | {first} | "
                    f"{share(cell['statuses'].get('invalidated', 0), cell['actionable'])} | "
                    f"{second} | {pct(t5.get('p50'))}（{t5['n']:,}） | "
                    f"{pct(t20.get('p50'))}（{t20['n']:,}） | {third} |"
                )
        lines += [
            "",
            f"### {base}：baseline 的可行動訊號都留在放寬版的核對（{tag}）",
            "",
            "| 版本 | baseline 可行動 | 版本可行動 | 多出來 | baseline 有、版本沒有 | 狀態或結算不同 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for version, item in data["consistency"].items():
            lines.append(
                f"| `{version}` | {item['baseline_actionable']:,} | "
                f"{item['version_actionable']:,} | {item['added']:,} | "
                f"{item['baseline_not_in_version']:,} | "
                f"{item['status_or_settlement_differs']:,} |"
            )
        for version, item in data["consistency"].items():
            if not item["dropped"]:
                continue
            reasons = Counter(
                f"{row.get('status')}：{','.join(row.get('reasons') or []) or '—'}"
                for row in item["dropped"]
            )
            lines += ["", f"- `{version}` 不見的 baseline 訊號，依版本的狀態與理由："]
            lines += [f"  - {key}：{count}" for key, count in reasons.most_common()]
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
    command = "python tools/research/aggressive_report.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    print(
        json.dumps(
            {"out": str(out.resolve()), "run": result["run"]},
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
