from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.db import init_db

from .backfill import BACKFILL_SCOPES, chunked_backfill
from .indicator_batch import run_indicator_batch
from .industry_repair import run_industry_repair
from .news_batch import run_news_batch
from .news_llm import DEFAULT_LIMIT as NEWS_LLM_DEFAULT_LIMIT, run_news_llm_batch
from .pipeline import analyze, backtest, collect, evaluate, run_daily
from .schedule_runs import PREFLIGHT_SKIP_REASONS, list_schedule_runs, record_preflight_skip
from .themes import sync_themes


# daily exit codes, so Task Scheduler's "Last Run Result" shows an incomplete day.
DAILY_EXIT_CODES = {"success": 0, "skipped": 0, "non_trading_day": 0, "partial": 2}
# news-llm: the schedule wrapper logs this next to news's own exit code; any status
# other than these (failed, or one it does not know) is 1.
NEWS_LLM_EXIT_CODES = {"success": 0, "skipped": 0, "dry_run": 0, "partial": 2}


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
    daily_parser.add_argument(
        "--skip-reason",
        choices=sorted(PREFLIGHT_SKIP_REASONS),
        help="排程包裝腳本起跑前檢查未通過：只記一列 skipped，不執行任何步驟",
    )
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
    indicators_parser = subparsers.add_parser("indicators", help="以保存日線計算技術指標（預設只寫最新未算日）")
    indicators_parser.add_argument("--date", dest="run_date", help="YYYY-MM-DD；未指定使用 DB 最新日線日")
    indicators_parser.add_argument("--rebuild", action="store_true", help="重算並改寫全部歷史")
    themes_parser = subparsers.add_parser("themes", help="題材表")
    themes_subparsers = themes_parser.add_subparsers(dest="themes_command", required=True)
    themes_sync_parser = themes_subparsers.add_parser("sync", help="驗證題材表並寫入族群與成員期間（重跑冪等）")
    themes_sync_parser.add_argument("--file", help="題材表 JSON；未指定使用 backend/data/themes/themes_v1.json")
    industry_parser = subparsers.add_parser("industry", help="官方產業群組")
    industry_subparsers = industry_parser.add_subparsers(dest="industry_command", required=True)
    industry_repair_parser = industry_subparsers.add_parser(
        "repair", help="依已保存的公司基本資料 raw 把產業成員搬到正確群組（預設 dry-run，重跑冪等）"
    )
    industry_repair_parser.add_argument("--apply", action="store_true", help="寫入 DB；未指定只列出預計變更")
    industry_repair_parser.add_argument(
        "--rescore-days", type=int, default=0, help="--apply 後重算最近 N 個交易日的族群分數"
    )
    news_parser = subparsers.add_parser("news", help="抓取國內／國際財經新聞 feed 並寫入 news_items")
    news_parser.add_argument("--date", dest="run_date", help="YYYY-MM-DD；只標記 run 日期，未指定使用台北今日")
    news_llm_parser = subparsers.add_parser("news-llm", help="以 claude -p 批次產生新聞摘要、關聯候選與方向判讀")
    news_llm_parser.add_argument("--date", dest="run_date", help="YYYY-MM-DD；只判讀該台北日收錄的新聞，未指定不限日期")
    news_llm_parser.add_argument("--limit", type=int, default=NEWS_LLM_DEFAULT_LIMIT, help="本次最多判讀則數")
    news_llm_parser.add_argument("--dry-run", action="store_true", help="只列出會送出的批次，不呼叫、不寫 DB")
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
    elif args.command == "indicators":
        result = run_indicator_batch(parse_date(args.run_date), rebuild=args.rebuild)
    elif args.command == "themes":
        result = sync_themes(args.file)
    elif args.command == "industry":
        if args.rescore_days < 0 or (args.rescore_days and not args.apply):
            parser.error("--rescore-days needs --apply and must not be negative")
        result = run_industry_repair(apply=args.apply, rescore_days=args.rescore_days)
    elif args.command == "news":
        result = run_news_batch(parse_date(args.run_date))
    elif args.command == "news-llm":
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        result = run_news_llm_batch(parse_date(args.run_date), limit=args.limit, dry_run=args.dry_run)
    else:
        if args.skip_reason:
            result = record_preflight_skip(parse_date(args.run_date), reason=args.skip_reason, trigger=args.trigger)
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
    if args.command == "news-llm":
        sys.exit(NEWS_LLM_EXIT_CODES.get(str(result.get("status")), 1))
    if args.command in {"themes", "industry"} and isinstance(result, dict) and result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
