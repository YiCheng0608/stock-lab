from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.db import init_db

from .backfill import BACKFILL_SCOPES, chunked_backfill
from .pipeline import analyze, backtest, collect, evaluate, run_daily
from .schedule_runs import list_schedule_runs


# daily exit codes, so Task Scheduler's "Last Run Result" shows an incomplete day.
DAILY_EXIT_CODES = {"success": 0, "skipped": 0, "non_trading_day": 0, "partial": 2}


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="台股研究工具 Python worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="建立 SQLite 資料表")
    subparsers.add_parser("analyze", help="計算技術特徵與族群排名")
    subparsers.add_parser("evaluate", help="更新訊號追蹤狀態")
    daily_parser = subparsers.add_parser("daily", help="執行 collect/analyze/evaluate")
    daily_parser.add_argument("--date", dest="run_date", help="YYYY-MM-DD；未指定使用最近工作日")
    daily_parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    daily_parser.add_argument(
        "--trigger",
        default="manual",
        choices=("manual", "scheduler", "simulation"),
        help="記錄在 schedule_runs 的觸發來源",
    )
    daily_parser.add_argument("--force", action="store_true", help="目標日已完成仍重跑各步驟（資料仍不改寫）")
    runs_parser = subparsers.add_parser("schedule-runs", help="列出 daily 排程 run 記錄與各步驟")
    runs_parser.add_argument("--date", dest="run_date", help="只列此目標日 YYYY-MM-DD")
    runs_parser.add_argument("--limit", type=int, default=20)
    collect_parser = subparsers.add_parser("collect", help="official TWSE/TPEx collection only")
    collect_parser.add_argument("--date", dest="run_date")
    collect_parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    backfill_parser = subparsers.add_parser(
        "backfill",
        help="official date-level backfill with resumable scope; long ranges run in 93-day windows",
    )
    backfill_parser.add_argument("--start-date", required=True)
    backfill_parser.add_argument("--end-date", required=True)
    backfill_parser.add_argument("--scope", choices=sorted(BACKFILL_SCOPES), default="market")
    backfill_parser.add_argument("--force", action="store_true", help="重新擷取已完成日期")
    backtest_parser = subparsers.add_parser("backtest", help="replay canonical rules on an as-of date range")
    backtest_parser.add_argument("--start-date", required=True)
    backtest_parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        result = {"status": "success"}
    elif args.command == "analyze":
        result = analyze()
    elif args.command == "evaluate":
        result = evaluate()
    elif args.command == "collect":
        result = collect(parse_date(args.run_date), months_back=args.months_back)
    elif args.command == "backfill":
        result = chunked_backfill(
            date.fromisoformat(args.start_date),
            date.fromisoformat(args.end_date),
            scope=args.scope,
            force=args.force,
        )
    elif args.command == "schedule-runs":
        result = list_schedule_runs(args.limit, parse_date(args.run_date))
    elif args.command == "backtest":
        result = backtest(date.fromisoformat(args.start_date), date.fromisoformat(args.end_date))
    else:
        result = run_daily(
            parse_date(args.run_date),
            months_back=args.months_back,
            trigger=args.trigger,
            force=args.force,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "daily":
        sys.exit(DAILY_EXIT_CODES.get(str(result.get("status")), 1))


if __name__ == "__main__":
    main()
