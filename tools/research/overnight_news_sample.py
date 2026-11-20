"""How many of the past lists had overnight news, and of which AI direction (#855 AC-4), read only.

The pre-open check (``worker.preopen``, #755) stores, for each trading day's
list, the news its ``daily`` had not seen.  It only started with #755; to see
how large the sample would have been, this rebuilds every past list's check
with the product's own rule (``app.preopen_news.check_rows``): the window from
the list's ``candidate_runs.computed_at`` to the 08:20 Taipei check of E, the
next trading day (``worker.notify.is_trading_day``, as preopen picks the list),
the stock page's relation, one story counted once per stock.  Nothing is
judged: it counts.

**Limit**: the AI direction is the done result of the current prompt read
now, not the one the 08:20 check saw; a rebuilt list has more items judged
(and maybe other directions) than it had at the time.  The stored
``preopen_news_checks`` are listed beside the rebuild for the days they exist.

Reads a stock.db copy through ``mode=ro`` and ``query_only``; refuses the
production database as ``backtest_research.py`` does.  A list whose check
instant is after the copy's newest ``news_items.collected_at`` is ``pending``
(its window is not complete in the copy) and is left out of the totals.

Writes ``summary.md``, ``tables.json`` and ``lists.csv`` to ``--out``.

The reference line (#855 decision 7018301183 §4, fixed before any result) is
``NEGATIVE_ROWS`` list rows with a 「可能負向」 (negative) overnight item, over
at least ``NEGATIVE_DATES`` list dates; the estimate extrapolates the rate of
the last ``RATE_WINDOW`` list dates.  A reference, not a judgement.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DIRECTIONS = ("positive", "negative", "mixed", "unknown")
DIRECTION_ZH = {
    "positive": "正向",
    "negative": "可能負向（negative）",
    "mixed": "混合",
    "unknown": "無法判斷",
    "unscored": "未判讀",
}
CHECK_TIME = time(8, 20)  # preopen's Taipei time (docs/ops/SCHEDULING.md)
TAIPEI_OFFSET = timedelta(hours=8)
NEGATIVE_ROWS = 100
NEGATIVE_DATES = 60
RATE_WINDOW = 60


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="overnight_news_sample.py", description=__doc__
    )
    parser.add_argument("--db", required=True, help="a tools/ops/copy_db.py copy")
    parser.add_argument("--out", required=True)
    return parser


def check_instant(day: date) -> datetime:
    """``day``'s 08:20 Taipei as the UTC-naive instant news rows store."""

    return datetime.combine(day, CHECK_TIME) - TAIPEI_OFFSET


def next_trading_day(db, day: date) -> date:
    """E: the first weekday after ``day`` the stored calendar does not mark closed."""

    from worker.notify import is_trading_day

    cursor = day + timedelta(days=1)
    for _ in range(31):
        if is_trading_day(db, cursor):
            return cursor
        cursor += timedelta(days=1)
    return cursor


def list_dates(db) -> list[date]:
    from sqlalchemy import select

    from app.domain import CANDIDATE_SCORE_READ_VERSIONS
    from app.models import CandidateRun

    return list(
        db.scalars(
            select(CandidateRun.trading_date)
            .where(CandidateRun.score_version.in_(CANDIDATE_SCORE_READ_VERSIONS))
            .distinct()
            .order_by(CandidateRun.trading_date)
        )
    )


def stored(db, day: date, run_id: int) -> dict[str, Any] | None:
    """The stored check of the list (``preopen_news_checks`` of that run), summed."""

    from sqlalchemy import select

    from app.models import PreopenNewsCheck

    rows = [
        row
        for row in db.scalars(
            select(PreopenNewsCheck).where(PreopenNewsCheck.list_date == day)
        )
        if row.candidate_run_id == run_id
    ]
    if not rows:
        return None
    return {
        "rows": len(rows),
        "rows_with_news": sum(row.news_count > 0 for row in rows),
        "rows_with_negative": sum(row.negative > 0 for row in rows),
        "news": sum(row.news_count for row in rows),
        "checked_at": rows[0].checked_at,
    }


def rebuild(db, newest: datetime | None) -> list[dict[str, Any]]:
    """One entry per list date: the rebuilt check, and the stored one beside it."""

    from app.candidate_runs import read_run
    from app.preopen_news import check_rows

    result = []
    for day in list_dates(db):
        run = read_run(db, day)
        if run is None:
            continue
        entry_day = next_trading_day(db, day)
        checked_at = check_instant(entry_day)
        item: dict[str, Any] = {
            "list_date": day,
            "run_id": run.id,
            "score_version": run.score_version,
            "computed_at": run.computed_at,
            "entry_day": entry_day,
            "checked_at": checked_at,
            "pending": newest is None or checked_at > newest,
        }
        rows = check_rows(db, run, checked_at)
        counts = {name: sum(getattr(row, name) for row in rows) for name in DIRECTIONS}
        item |= {
            "rows": len(rows),
            "rows_with_news": sum(row.news_count > 0 for row in rows),
            "rows_with_negative": sum(row.negative > 0 for row in rows),
            "news": sum(row.news_count for row in rows),
            "unscored": sum(row.unscored for row in rows),
            **counts,
            "stored": stored(db, day, run.id),
        }
        result.append(item)
    return result


def _trading_days_after(db, day: date, count: int) -> date:
    """The ``count``-th trading day after ``day`` over the stored calendar (an unknown day counts as trading)."""

    from worker.notify import is_trading_day

    cursor, counted = day, 0
    while counted < count:
        cursor += timedelta(days=1)
        if is_trading_day(db, cursor):
            counted += 1
    return cursor


def estimate(lists: list[dict[str, Any]], db) -> dict[str, Any]:
    """When the reference line would be reached at the last ``RATE_WINDOW`` dates' rate.

    ``earliest_list_date`` needs no rate: a list adds at most one date, so the
    dates line cannot be reached before ``NEGATIVE_DATES`` − dates more lists.
    """

    done = [item for item in lists if not item["pending"]]
    rows = sum(item["rows_with_negative"] for item in done)
    dates = sum(item["rows_with_negative"] > 0 for item in done)
    recent = done[-RATE_WINDOW:]
    result: dict[str, Any] = {
        "negative_rows": rows,
        "negative_dates": dates,
        "target_rows": NEGATIVE_ROWS,
        "target_dates": NEGATIVE_DATES,
        "rate_window": len(recent),
        "rate_window_first": recent[0]["list_date"] if recent else None,
        "rows_per_list": None,
        "dates_per_list": None,
        "lists_needed": None,
        "reached": rows >= NEGATIVE_ROWS and dates >= NEGATIVE_DATES,
        "estimated_list_date": None,
        "earliest_lists_needed": None,
        "earliest_list_date": None,
    }
    if not recent:
        return result
    if not result["reached"]:
        floor = max(NEGATIVE_DATES - dates, 1)
        result["earliest_lists_needed"] = floor
        result["earliest_list_date"] = _trading_days_after(
            db, done[-1]["list_date"], floor
        )
    row_rate = sum(item["rows_with_negative"] for item in recent) / len(recent)
    date_rate = sum(item["rows_with_negative"] > 0 for item in recent) / len(recent)
    result |= {"rows_per_list": row_rate, "dates_per_list": date_rate}
    if result["reached"]:
        return result
    if row_rate <= 0 or date_rate <= 0:
        return result
    needed = max(
        0.0 if rows >= NEGATIVE_ROWS else (NEGATIVE_ROWS - rows) / row_rate,
        0.0 if dates >= NEGATIVE_DATES else (NEGATIVE_DATES - dates) / date_rate,
    )
    lists_needed = int(-(-needed // 1))  # ceil
    result["lists_needed"] = lists_needed
    result["estimated_list_date"] = _trading_days_after(
        db, done[-1]["list_date"], lists_needed
    )
    return result


def unreadable_lists(db) -> list[date]:
    """List dates whose runs are all of a score version the page no longer reads."""

    from sqlalchemy import select

    from app.models import CandidateRun

    every = set(db.scalars(select(CandidateRun.trading_date).distinct()))
    return sorted(every - set(list_dates(db)))


def all_directions(db, start: datetime, end: datetime) -> dict[str, int]:
    """The AI direction of every active news item linked to a stock, collected in [start, end].

    Only listed for comparison (the overnight share against all news); not
    part of the reference line.
    """

    from sqlalchemy import select

    from app.models import NewsItem
    from app.preopen_news import _prompt, direction_of

    ids = [
        news_id
        for news_id, symbols in db.execute(
            select(NewsItem.id, NewsItem.symbols_json).where(
                NewsItem.status == "active",
                NewsItem.collected_at >= start,
                NewsItem.collected_at <= end,
            )
        )
        if symbols
    ]
    version, done_results = _prompt()
    counts = {name: 0 for name in (*DIRECTIONS, "unscored")}
    for at in range(0, len(ids), 5000):
        chunk = ids[at : at + 5000]
        results = done_results(db, chunk, version)
        for news_id in chunk:
            direction = direction_of(results.get(news_id))
            counts[direction or "unscored"] += 1
    return counts


def news_span(db) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.models import NewsItem

    first, last, count = db.execute(
        select(
            func.min(NewsItem.collected_at),
            func.max(NewsItem.collected_at),
            func.count(NewsItem.id),
        )
    ).one()
    return {"first_collected_at": first, "last_collected_at": last, "items": count}


def build(db) -> dict[str, Any]:
    span = news_span(db)
    lists = rebuild(db, span["last_collected_at"])
    done = [item for item in lists if not item["pending"]]
    with_news = [item for item in done if item["rows_with_news"]]
    totals = {
        "lists": len(done),
        "pending_lists": len(lists) - len(done),
        "first_list": done[0]["list_date"] if done else None,
        "last_list": done[-1]["list_date"] if done else None,
        "first_list_with_news": with_news[0]["list_date"] if with_news else None,
        "rows": sum(item["rows"] for item in done),
        "rows_with_news": sum(item["rows_with_news"] for item in done),
        "rows_with_negative": sum(item["rows_with_negative"] for item in done),
        "news": sum(item["news"] for item in done),
        "unscored": sum(item["unscored"] for item in done),
        **{name: sum(item[name] for item in done) for name in DIRECTIONS},
    }
    compared = [item for item in done if item["stored"]]
    return {
        "news": span,
        "unreadable_lists": unreadable_lists(db),
        "all_directions": (
            all_directions(db, done[0]["computed_at"], done[-1]["checked_at"])
            if done
            else None
        ),
        "totals": totals,
        "estimate": estimate(lists, db),
        "stored_compared": {
            "lists": len(compared),
            "same_rows_with_news": sum(
                item["stored"]["rows_with_news"] == item["rows_with_news"]
                for item in compared
            ),
            "same_news": sum(
                item["stored"]["news"] == item["news"] for item in compared
            ),
        },
        "lists": lists,
    }


def _pct(part: int, whole: int) -> str:
    return "—" if not whole else f"{part / whole * 100:.1f}%"


def _taipei(value: datetime | None) -> str:
    return "—" if value is None else (value + TAIPEI_OFFSET).strftime("%Y-%m-%d %H:%M")


def markdown(result: dict[str, Any], command: str) -> str:
    totals, guess, span = result["totals"], result["estimate"], result["news"]
    news = totals["news"]
    lines = [
        "# 隔夜新聞樣本（#855 AC-4，只量樣本、不判定）",
        "",
        "- **限制（先讀）**：AI 方向用的是**現在**讀到的判讀結果（目前 prompt 的 done 結果），"
        "不是當時 08:20 檢查看到的；重建的名單判讀得比當時多，方向也可能不同。"
        "#755 上線後實際存下的 `preopen_news_checks` 列在最後一節對照。",
        "- 重建規則：`app.preopen_news.check_rows`（時間窗＝名單 `computed_at` 之後收進、"
        "名單日 00:00 起發布、到 E 的台北 08:20；E＝名單日之後第一個交易日，`worker.notify.is_trading_day`）。",
        f"- 重現：`{command}`",
        f"- 新聞資料：{span['items']:,} 則，收進時間 {_taipei(span['first_collected_at'])}～"
        f"{_taipei(span['last_collected_at'])}（台北）。",
        "",
        "## 總表",
        "",
        "| 項目 | 數值 |",
        "| --- | ---: |",
        f"| 名單日數（窗口完整） | {totals['lists']:,} |",
        f"| 名單日範圍 | {totals['first_list']}～{totals['last_list']} |",
        f"| 第一個有隔夜新聞的名單日 | {totals['first_list_with_news'] or '—'} |",
        f"| 窗口還沒結束、不計的名單 | {totals['pending_lists']} |",
        f"| 名單列數 | {totals['rows']:,} |",
        f"| 有隔夜新聞的列 | {totals['rows_with_news']:,}（{_pct(totals['rows_with_news'], totals['rows'])}） |",
        f"| 有「可能負向」隔夜新聞的列 | {totals['rows_with_negative']:,}（{_pct(totals['rows_with_negative'], totals['rows'])}） |",
        f"| 隔夜新聞（則・列） | {news:,} |",
        "",
        "- 頁面讀不到的舊評分版本名單（`CANDIDATE_SCORE_READ_VERSIONS` 以外，不重建）："
        + ("、".join(map(str, result["unreadable_lists"])) or "無"),
        "",
        "## AI 方向分布（每則每檔算一次）",
        "",
        "| 方向 | 則數 | 比例 |",
        "| --- | ---: | ---: |",
    ]
    for name in (*DIRECTIONS, "unscored"):
        lines.append(
            f"| {DIRECTION_ZH[name]} | {totals[name]:,} | {_pct(totals[name], news)} |"
        )
    every = result.get("all_directions")
    if every:
        whole = sum(every.values())
        lines += [
            "",
            "## 同期全部新聞的 AI 方向（只列、不判定）",
            "",
            "第一份名單的 `computed_at` 到最後一份完整名單的檢查時點之間收進、有關聯個股的有效新聞，"
            "不分是否隔夜，給隔夜新聞的比例對照。",
            "",
            "| 方向 | 則數 | 比例 |",
            "| --- | ---: | ---: |",
        ]
        for name in (*DIRECTIONS, "unscored"):
            lines.append(
                f"| {DIRECTION_ZH[name]} | {every[name]:,} | {_pct(every[name], whole)} |"
            )
    lines += [
        "",
        "## 要累積到哪一天（參考線，不是判定）",
        "",
        f"- 參考線（#855 決定 7018301183 第 4 點，事先固定）：有「可能負向」隔夜新聞的名單列 ≥ {guess['target_rows']} 列，"
        f"分布在 ≥ {guess['target_dates']} 個名單日。",
        f"- 目前：{guess['negative_rows']} 列、{guess['negative_dates']} 個名單日。",
    ]
    if guess["reached"]:
        lines.append("- 已達參考線。")
    elif guess["estimated_list_date"]:
        lines.append(
            f"- 以最近 {guess['rate_window']} 個名單日（{guess['rate_window_first']} 起）的速率："
            f"每日 {guess['rows_per_list']:.2f} 列、{guess['dates_per_list'] * 100:.0f}% 的名單日有；"
            f"還要 {guess['lists_needed']} 個名單日，約到 **{guess['estimated_list_date']}** 的名單"
            "（休市日用目前存的行事曆，沒存的平日當交易日）。"
        )
    else:
        lines.append("- 最近的名單日沒有「可能負向」列，速率為 0，推估不出日期。")
    if not guess["reached"] and guess["earliest_list_date"]:
        lines.append(
            f"- 不靠速率的下限：一份名單最多加 1 個名單日，至少還要 {guess['earliest_lists_needed']} 個名單日，"
            f"最快也要到 **{guess['earliest_list_date']}** 的名單"
            "（每份都有「可能負向」列才會這麼快；休市日用目前存的行事曆，沒存的平日當交易日）。"
        )
    lines += [
        "",
        "## 每份名單",
        "",
        "| 名單日 | E | 列數 | 有新聞 | 可能負向 | 則數 | 正向 | 負向 | 混合 | 無法判斷 | 未判讀 | 實際檢查（有新聞／則數） |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in result["lists"]:
        real = item["stored"]
        real_text = "—" if real is None else f"{real['rows_with_news']}／{real['news']}"
        mark = "（窗口未完，不計）" if item["pending"] else ""
        lines.append(
            f"| {item['list_date']}{mark} | {item['entry_day']} | {item['rows']} | "
            f"{item['rows_with_news']} | {item['rows_with_negative']} | {item['news']} | "
            f"{item['positive']} | {item['negative']} | {item['mixed']} | {item['unknown']} | "
            f"{item['unscored']} | {real_text} |"
        )
    compared = result["stored_compared"]
    lines += [
        "",
        "## 和實際存下的檢查對照（#755 上線後）",
        "",
        f"- 有實際檢查的名單 {compared['lists']} 份：有新聞的列數相同 {compared['same_rows_with_news']} 份、"
        f"則數相同 {compared['same_news']} 份。不同的原因可能是檢查實際時刻不是 08:20、"
        "或 08:20 之後才收進的新聞被重建算進去（重建一律用 08:20）。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db_path = Path(args.db)
    problem = _load("backtest_research").production_problem(db_path, dict(os.environ))
    if problem or not db_path.is_file():
        print(json.dumps({"refused": [problem or f"{db_path} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if str(ROOT / "backend") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend"))
    # Importing app.config makes its data and raw directories: point them at
    # the copy's directory (it exists) and the output, and put them back after.
    names = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")
    saved = {name: os.environ.get(name) for name in names}
    os.environ["STOCK_DB_PATH"] = str(db_path.resolve())
    os.environ["STOCK_DATA_DIR"] = str(db_path.resolve().parent)
    os.environ["STOCK_RAW_DIR"] = str((out / ".raw-unused").resolve())
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        connect = _load("regime_report").connect_read_only
        engine = create_engine("sqlite://", creator=lambda: connect(db_path))
        try:
            with Session(engine, autoflush=False) as db:
                result = build(db)
                db.rollback()
        finally:
            engine.dispose()
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    command = "python tools/research/overnight_news_sample.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    fields = [
        "list_date",
        "run_id",
        "entry_day",
        "checked_at",
        "pending",
        "rows",
        "rows_with_news",
        "rows_with_negative",
        "news",
        *DIRECTIONS,
        "unscored",
    ]
    with (out / "lists.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([*fields, "stored_rows_with_news", "stored_news"])
        for item in result["lists"]:
            real = item["stored"] or {}
            writer.writerow(
                [item[name] for name in fields]
                + [real.get("rows_with_news"), real.get("news")]
            )
    print(json.dumps({"out": str(out.resolve()), **result["totals"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
