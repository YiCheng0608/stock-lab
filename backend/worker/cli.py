from __future__ import annotations

import argparse
import json
from datetime import date

from app.db import init_db

from .backfill import BACKFILL_SCOPES, targeted_backfill
from .pipeline import analyze, backtest, collect, evaluate, run_daily


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
    collect_parser = subparsers.add_parser("collect", help="official TWSE/TPEx collection only")
    collect_parser.add_argument("--date", dest="run_date")
    collect_parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    backfill_parser = subparsers.add_parser("backfill", help="official date-level backfill with resumable scope")
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
        result = targeted_backfill(
            date.fromisoformat(args.start_date),
            date.fromisoformat(args.end_date),
            scope=args.scope,
            force=args.force,
        )
    elif args.command == "backtest":
        result = backtest(date.fromisoformat(args.start_date), date.fromisoformat(args.end_date))
    else:
        result = run_daily(parse_date(args.run_date), months_back=args.months_back)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
