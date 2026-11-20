"""The frozen forward entries of the forward-watch objects (#868).

docs/spec/evidence.md 前瞻監測與下架: every object (a hypothesis whose
validation was ``前瞻觀察``, or a strategy in the product) is followed from its
registration day on the data no one used to choose it, each month in the same
report as H1 (#699).  The first object is X4 (#867's validation, comment
7033243199).  Nothing here is a command-line option: ``WATCHES`` holds each
object's frozen entry, its definition is the one its own tool ran (imported,
not copied, and refused when that tool's ``definitions_sha256`` is not the
frozen one), and the golden test of its output fails on any change.

The engine, the costs and the excess are those of 前瞻驗證 H1's ``--window
forward``: signal dates T from the first session on or after ``since`` to the
session before the cutoff, T+1's open to the K-th session's close
(``portfolio_research.simulate``), the benchmark the same engine over the
day's whole population (``evidence_lib.universe``), TAIEX only listed.  The
bars before ``since`` are read for the features only (``WARMUP_CALENDAR_DAYS``,
as explore_research's later segments).  The verdict is
``portfolio_research.forward_judge`` on every session to the cutoff with
``min_days`` 60: before 60 sessions it is ``樣本不足`` and the numbers are no
verdict.  A forward-watch object is never delisted: even ``輸給基準`` is only
recorded.

A next object registers its entry in ``WATCHES`` (its source tool, code,
definition hash, since and kind), adds an engine to ``ENGINES`` if its tool's
rule is not one of them, and gets a golden test; the command and the report
stay the same.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as er  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 1
DESIGN = "868"
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
RAW_DIR_NAME = "raw"
MIN_DAYS = (
    60  # 前瞻監測與下架: judged from 60 sessions on (the same M as H1 historical)
)
WARMUP_CALENDAR_DAYS = er.WARMUP_CALENDAR_DAYS
WATCH = "前瞻觀察"
PRODUCT = "已進產品"
KIND_NOTES = {
    WATCH: "前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；"
    "之後的數字再好也不改成「通過」、不進產品",
    PRODUCT: "已進產品的策略：滿 60 日起每月判一次，判到「輸給基準」由統籌在 #1 提案下架；"
    "其餘判定只列出",
}

# The frozen entries (#868).  ``definitions_sha256`` is the source tool's at the
# reports that put the object here; ``since`` its registration day.
WATCHES: dict[str, dict[str, Any]] = {
    "X4": {
        "kind": WATCH,
        "source": "explore_research",
        "source_version": 2,
        "code": "X4",
        "definitions_sha256": (
            "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
        ),
        "since": date(2026, 11, 20),
        "min_days": MIN_DAYS,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7033243199"
        ),
    },
}
SOURCES = {"explore_research": er}


def definition(name: str) -> dict[str, Any]:
    """The object's definition as its source tool holds it."""

    entry = WATCHES[name]
    return SOURCES[entry["source"]].HYPOTHESES[entry["code"]]


def source_problems(name: str) -> list[str]:
    """Refuse when the source tool is no longer the one that judged the object."""

    entry = WATCHES[name]
    source = SOURCES[entry["source"]]
    problems = []
    if source.VERSION != entry["source_version"]:
        problems.append(
            f"{entry['source']} is version {source.VERSION}, "
            f"{name} was judged by version {entry['source_version']}"
        )
    if source.definitions_sha256() != entry["definitions_sha256"]:
        problems.append(
            f"{entry['source']}'s definitions_sha256 is not the one {name} was judged by"
        )
    return problems


# --- the engines ---------------------------------------------------------------


def explore_daily(
    db: Path, entry: dict[str, Any], since: date, cutoff: date | None, out: Path
) -> dict[str, Any]:
    """An explore_research ``daily`` hypothesis forward: its ``plan`` (the
    filters, subset and keys of the registration) on the signal dates from
    ``since``, ``simulate`` for it and the population."""

    spec = SOURCES[entry["source"]].HYPOTHESES[entry["code"]]
    if spec["rule"] != "daily":
        raise SystemExit(f"{entry['code']} is not a daily hypothesis")
    latest = pr.copy_facts(db)["latest"]
    end = cutoff or (date.fromisoformat(latest) if latest else since)
    ctx = er.load_context(
        db, since - timedelta(days=WARMUP_CALENDAR_DAYS), end, out / RAW_DIR_NAME
    )
    panel = ctx.market.panel
    sessions = panel.sessions
    position = {day: index for index, day in enumerate(sessions)}
    if cutoff is not None and cutoff not in position:
        raise SystemExit(f"cutoff {cutoff} is not a market session")
    last = position[cutoff] if cutoff is not None else len(sessions) - 1
    signals = [at for at in range(last) if sessions[at] >= since]
    run: dict[str, Any] = {
        "panel": panel,
        "cutoff": sessions[last].isoformat() if sessions else None,
        "signal_days": len(signals),
        "dates": [],
        "rows": [],
        "positions": [],
        "equity": ([], []),
        "returns": ([], []),
        "taiex": [],
        "invested": ([], []),
        "turnover": ([], []),
        "counts": {},
        "coverage": {},
    }
    if not signals:
        return run
    first = signals[0] + 1
    planned = er.plan(ctx, spec, first, last)
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    run.update(
        {
            "dates": sessions[first : last + 1],
            "rows": planned.rows,
            "positions": mine.positions,
            "equity": (mine.equity, population.equity),
            "returns": (
                pr.daily_returns(mine.equity),
                pr.daily_returns(population.equity),
            ),
            "taiex": er._taiex(panel, first, last),
            "invested": (mine.invested, population.invested),
            "turnover": (er._turnover(mine), er._turnover(population)),
            "counts": {
                entry["code"]: dict(mine.counts),
                POPULATION: dict(population.counts),
            },
            "coverage": planned.coverage,
            "win": er.win_rate(mine),
        }
    )
    return run


ENGINES: dict[str, Callable[..., dict[str, Any]]] = {"explore_research": explore_daily}


# --- the run ---------------------------------------------------------------------


def study(run: dict[str, Any], name: str, min_days: int) -> dict[str, Any]:
    mine, others = run["returns"]
    taiex = run["taiex"]
    excess = {
        TAIEX: pr.excess_metrics([a - b for a, b in zip(mine, taiex) if b is not None]),
        POPULATION: pr.excess_metrics([a - b for a, b in zip(mine, others)]),
    }
    curves = {
        TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
        name: pr.curve_metrics(mine, run["invested"][0], run["turnover"][0]),
        POPULATION: pr.curve_metrics(others, run["invested"][1], run["turnover"][1]),
    }
    return {
        "days": len(run["dates"]),
        "min_days": min_days,
        "verdict": pr.forward_judge(excess[POPULATION], min_days),
        "excess": excess,
        "absolute": {
            "days": len(mine),
            "mean": statistics.fmean(mine) if mine else None,
        },
        "curves": curves,
        "win": run.get("win"),
        "counts": run["counts"],
        "coverage": run["coverage"],
    }


def run_watch(
    db: Path,
    name: str,
    out: Path,
    cutoff: date | None = None,
    since: date | None = None,
    command: str = "",
) -> dict[str, Any]:
    """Run object ``name`` forward and write ``out``.

    ``since`` replaces the frozen start for the tests only; the command line
    has no way to set it.
    """

    started = time.monotonic()
    entry = WATCHES[name]
    start = since or entry["since"]
    out.mkdir(parents=True, exist_ok=True)
    run = ENGINES[entry["source"]](db, entry, start, cutoff, out)
    dates = run["dates"]
    spec = definition(name)
    result = {
        "version": VERSION,
        "design": DESIGN,
        "watch": name,
        "kind": entry["kind"],
        "note": KIND_NOTES[entry["kind"]],
        "entry": entry,
        "definition": spec,
        "command": command,
        "tool_commit": er.tool_commit(),
        "copy": pr.copy_facts(db),
        "rule": {
            "slippage_bps": pr.SLIPPAGE * 10_000,
            "fee": pr.FEE,
            "tax": pr.TAX,
            "min_t": pr.MIN_T,
        },
        "since": start.isoformat(),
        "cutoff": run["cutoff"],
        "first_signal": run["rows"][0]["signal_date"] if run["rows"] else None,
        "first_session": dates[0].isoformat() if dates else None,
        "last_session": dates[-1].isoformat() if dates else None,
        "signal_days": run["signal_days"],
        **study(run, name, entry["min_days"]),
    }
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    write_outputs(out, result, run)
    return {
        "out": str(out.resolve()),
        "watch": name,
        "days": result["days"],
        "min_days": result["min_days"],
        "verdict": result["verdict"],
        "elapsed_seconds": round(result["elapsed_seconds"], 1),
    }


# --- the report ------------------------------------------------------------------

VOLATILE_KEYS = ("command", "tool_commit", "elapsed_seconds", "peak_memory_gb")


def _pct(value: float | None, digits: int = 2) -> str:
    return lib.pct(value, digits)


def _t(value: float | None) -> str:
    return lib.num(value, 2)


def markdown(result: dict[str, Any]) -> str:
    name, entry, spec = result["watch"], result["entry"], result["definition"]
    days, threshold = result["days"], result["min_days"]
    e, a = result["excess"], result["absolute"]
    if result["verdict"] == "樣本不足":
        verdict = (
            f"**樣本不足（累積 {days}／{threshold} 日）**：數字不是判定，滿 {threshold} 日"
            "才判定"
        )
    else:
        verdict = f"**{result['verdict']}**（累積 {days} 日，`forward_judge`）"
    lines = [
        f"# {name} {entry['kind']}的前瞻紀錄（forward_watch 第 {result['version']} 版，"
        f"#{result['design']}）",
        "",
        # the TAIEX excess first, then the population's (前瞻監測與下架「每月」)
        f"- 對加權指數超額（只列出）：日均 {_pct(e[TAIEX]['mean'], 3)}，t {_t(e[TAIEX]['t'])}，"
        f"{e[TAIEX]['days']} 日",
        f"- 對母體超額：日均 {_pct(e[POPULATION]['mean'], 3)}，t {_t(e[POPULATION]['t'])}，"
        f"累積 {days} 日",
        f"- 判定：{verdict}；{result['note']}",
        f"- 定義：{entry['source']} 第 {entry['source_version']} 版的 {entry['code']}"
        f"（{spec['label']}；N＝{spec['top']}、K＝{spec['hold']}），定義雜湊 "
        f"`{entry['definitions_sha256']}`；登記 {entry['registered']}",
        f"- 窗口：前瞻起日 {result['since']}（之前的資料只當暖機），第一個訊號日 "
        f"{result['first_signal'] or '—'}；有淨值的交易日 {result['first_session'] or '—'}"
        f"～{result['last_session'] or '—'}，cutoff {result['cutoff'] or '—'}",
        f"- 副本：最新交易日 {result['copy']['latest']}，alembic `{result['copy']['alembic']}`，"
        f"檔案時間 {result['copy']['mtime']}",
        "- 進出與成本同「前瞻驗證 H1」：T+1 開盤買（+5 bps、手續費 0.1425%），成交那根算第 1 根、"
        f"第 {spec['hold']} 根收盤賣（−5 bps、手續費、證交稅 0.3%），{spec['hold']} 份子帳戶輪替；"
        "基準是同一引擎的每日全部母體",
        f"- 判定表（由上往下）：樣本不足（< {threshold} 日）→ 通過（超額日均 > 0 且 t ≥ 2）"
        "→ 輸給基準（< 0 且 t ≤ −2）→ 方向一致但不顯著（> 0）→ 沒有優勢",
        f"- 耗時 {result.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(result.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{result['command']}`",
        "",
        "## 數字（至今）",
        "",
        "| 量 | 日數 | 日均 | 年化 | t |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
        f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
        f"| 超額（對母體） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
        f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
        f"| 絕對報酬（扣成本，只列出） | {a['days']} | {_pct(a['mean'], 3)} "
        f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
        "",
        "## 資金曲線（只列出）",
        "",
        "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {TAIEX: "加權指數（價格指數）", name: name, POPULATION: "母體（基準）"}
    for key in (TAIEX, name, POPULATION):
        c = result["curves"][key]
        held = (
            "| — | — |"
            if key == TAIEX
            else f"| {_pct(c.get('invested'), 1)} | {lib.num(c.get('turnover'), 1)} |"
        )
        lines.append(
            f"| {labels[key]} | {c['days']} | {_pct(c.get('annual'))} "
            f"| {_pct(c.get('volatility'))} | {_pct(c.get('max_drawdown'))} " + held
        )
    counts = result["counts"].get(name, {})
    win = result.get("win") or {"rate": None, "won": 0, "bought": 0, "unsold": 0}
    lines += [
        "",
        f"勝率（買進的每一筆，期末未賣以最後收盤計）：{_pct(win['rate'], 1)}"
        f"（{win['won']:,}／{win['bought']:,}，期末未賣 {win['unsold']:,}）。",
        f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
        f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
        f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
        f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
        "",
    ]
    if result["coverage"]:
        coverage = er.coverage_lines(entry["code"], result["coverage"])
        lines += ["## 資料覆蓋", "", *coverage, ""]
    return "\n".join(lines)


def write_outputs(out: Path, result: dict[str, Any], run: dict[str, Any]) -> None:
    name = result["watch"]
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(markdown(result), encoding="utf-8")
    panel = run["panel"]
    mine, population = run["equity"]
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", name, POPULATION, "taiex_close"])
        for at, day in enumerate(run["dates"]):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{mine[at]:.8f}",
                    f"{population[at]:.8f}",
                    panel.index_close.get(day),
                ]
            )
    fields = [
        "signal_date",
        "rank",
        "exchange",
        "symbol",
        *er.used_features(result["definition"]),
        "tie",
    ]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(run["rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "account",
                "exchange",
                "symbol",
                "bought",
                "due",
                "sold",
                "how",
                "cost",
                "proceeds",
            ]
        )
        for p in run["positions"]:
            exchange, symbol, _ = panel.symbols.get(p.instrument_id, ("", "", ""))
            writer.writerow(
                [
                    p.account,
                    exchange,
                    symbol,
                    sessions[p.bought].isoformat(),
                    sessions[p.due].isoformat() if p.due < len(sessions) else "",
                    sessions[p.sold].isoformat() if p.sold is not None else "",
                    p.how,
                    f"{p.cost:.10f}",
                    "" if p.proceeds is None else f"{p.proceeds:.10f}",
                ]
            )


# --- the command -----------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forward_watch.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--watch", required=True, choices=list(WATCHES))
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=None,
        help="last session valued (default: the copy's latest session)",
    )
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    problems += source_problems(args.watch)
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    line = run_watch(
        db,
        args.watch,
        Path(args.out),
        cutoff=args.cutoff,
        command="python tools/research/forward_watch.py " + " ".join(argv),
    )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
