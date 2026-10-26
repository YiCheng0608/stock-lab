from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.db import init_db

from .backfill import BACKFILL_SCOPES, chunked_backfill
from .candidate_notes import run_candidate_notes_batch
from .candidates import run_candidates
from .indicator_batch import run_indicator_batch
from .industry_repair import run_industry_repair
from .instrument_repair import run_instrument_repair
from .market_summary import backfill_market_summaries
from .news_batch import run_news_batch
from .news_llm import DEFAULT_LIMIT as NEWS_LLM_DEFAULT_LIMIT, run_news_llm_batch
from .pipeline import analyze, backtest, collect, evaluate, run_daily
from .plan_tracking import run_plan_tracking
from .schedule_runs import (
    PREFLIGHT_SKIP_REASONS,
    list_schedule_runs,
    record_preflight_skip,
)
from .strategy_levels import run_strategy_levels
from .theme_suggestions import run_theme_suggestions
from .themes import sync_themes


# daily exit codes, so Task Scheduler's "Last Run Result" shows an incomplete day.
DAILY_EXIT_CODES = {
    "success": 0,
    "skipped": 0,
    "non_trading_day": 0,
    "non_trading_unconfirmed": 0,
    "partial": 2,
}
# news-llm (and candidate-notes): the schedule wrapper logs this next to news's own
# exit code; any status other than these (failed, or one it does not know) is 1.
NEWS_LLM_EXIT_CODES = {
    "success": 0,
    "skipped": 0,
    "dry_run": 0,
    "no_data": 0,
    "partial": 2,
}


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="台股研究工具 Python worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="建立 SQLite 資料表")
    subparsers.add_parser("analyze", help="計算技術特徵與族群排名")
    subparsers.add_parser("evaluate", help="更新訊號追蹤狀態")
    daily_parser = subparsers.add_parser("daily", help="執行 collect/analyze/evaluate")
    daily_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD；未指定使用最近工作日"
    )
    daily_parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    daily_parser.add_argument(
        "--trigger",
        default="manual",
        choices=("manual", "scheduler", "simulation"),
        help="記錄在 schedule_runs 的觸發來源",
    )
    daily_parser.add_argument(
        "--force", action="store_true", help="目標日已完成仍重跑各步驟（資料仍不改寫）"
    )
    daily_parser.add_argument(
        "--catchup-sessions",
        type=int,
        default=None,
        help="先補抓目標日前最近 N 個缺 collect 的官方交易日（預設 5；0 不補）",
    )
    daily_parser.add_argument(
        "--skip-reason",
        choices=sorted(PREFLIGHT_SKIP_REASONS),
        help="排程包裝腳本起跑前檢查未通過：只記一列 skipped，不執行任何步驟",
    )
    runs_parser = subparsers.add_parser(
        "schedule-runs", help="列出 daily 排程 run 記錄與各步驟"
    )
    runs_parser.add_argument("--date", dest="run_date", help="只列此目標日 YYYY-MM-DD")
    runs_parser.add_argument("--limit", type=int, default=20)
    collect_parser = subparsers.add_parser(
        "collect", help="official TWSE/TPEx collection only"
    )
    collect_parser.add_argument("--date", dest="run_date")
    collect_parser.add_argument("--months-back", type=int, choices=range(4), default=0)
    backfill_parser = subparsers.add_parser(
        "backfill",
        help="official date-level backfill with resumable scope; long ranges run in 93-day windows",
    )
    backfill_parser.add_argument("--start-date", required=True)
    backfill_parser.add_argument("--end-date", required=True)
    backfill_parser.add_argument(
        "--scope", choices=sorted(BACKFILL_SCOPES), default="market"
    )
    backfill_parser.add_argument(
        "--force", action="store_true", help="重新擷取已完成日期"
    )
    summary_parser = subparsers.add_parser(
        "market-summary",
        help="以已存的 TWSE MI_INDEX raw 回補大盤概況（不發網路請求；TPEx 無歷史不回補）",
    )
    summary_parser.add_argument("--from", dest="start_date", required=True)
    summary_parser.add_argument("--to", dest="end_date", required=True)
    summary_parser.add_argument(
        "--force", action="store_true", help="與已存值不同時改寫並改指向這份 raw"
    )
    backtest_parser = subparsers.add_parser(
        "backtest", help="replay canonical rules on an as-of date range"
    )
    backtest_parser.add_argument("--start-date", required=True)
    backtest_parser.add_argument("--end-date", required=True)
    indicators_parser = subparsers.add_parser(
        "indicators", help="以保存日線計算技術指標（預設只寫最新未算日）"
    )
    indicators_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD；未指定使用 DB 最新日線日"
    )
    indicators_parser.add_argument(
        "--rebuild", action="store_true", help="重算並改寫全部歷史"
    )
    candidates_parser = subparsers.add_parser(
        "candidates",
        help="以 candidate_score_v1 產生每日候選清單（同日同版本重跑冪等）",
    )
    candidates_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD；未指定使用最新訊號日"
    )
    plans_parser = subparsers.add_parser(
        "track-plans",
        help="更新使用者追蹤計畫的模擬觸發與結果（daily 的 plan_tracking 步驟；同日重跑冪等）",
    )
    plans_parser.add_argument(
        "--date",
        dest="run_date",
        help="YYYY-MM-DD 目標交易日；未指定使用 DB 最新日線日",
    )
    levels_parser = subparsers.add_parser(
        "strategy-levels",
        help="計算訊號的條件價位 strategy_levels_v1（daily 的 strategy_levels 步驟；同日重跑冪等）",
    )
    levels_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD 訊號日；未指定使用最新訊號日"
    )
    notes_parser = subparsers.add_parser(
        "candidate-notes",
        help="以 claude -p 為每日候選產生 AI 進出點說明（同日同提示版本已完成者不重算）",
    )
    notes_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD 候選交易日；未指定使用最新一次候選"
    )
    notes_parser.add_argument(
        "--limit",
        type=int,
        help="本次最多說明幾檔（名次在前、尚未完成者優先）；未指定為全部",
    )
    notes_parser.add_argument(
        "--dry-run", action="store_true", help="只列出會送出的批次，不呼叫、不寫 DB"
    )
    themes_parser = subparsers.add_parser("themes", help="題材表")
    themes_subparsers = themes_parser.add_subparsers(
        dest="themes_command", required=True
    )
    themes_sync_parser = themes_subparsers.add_parser(
        "sync", help="驗證題材表並寫入族群與成員期間（重跑冪等）"
    )
    themes_sync_parser.add_argument(
        "--file", help="題材表 JSON；未指定使用 backend/data/themes/themes_v1.json"
    )
    subparsers.add_parser(
        "theme-suggestions",
        help="由新聞 AI 判讀的題材候選重算待核實題材建議（不進榜、不寫題材表，重跑冪等）",
    )
    industry_parser = subparsers.add_parser("industry", help="官方產業群組")
    industry_subparsers = industry_parser.add_subparsers(
        dest="industry_command", required=True
    )
    industry_repair_parser = industry_subparsers.add_parser(
        "repair",
        help="依已保存的公司基本資料 raw 把產業成員搬到正確群組（預設 dry-run，重跑冪等）",
    )
    industry_repair_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
    )
    industry_repair_parser.add_argument(
        "--rescore-days",
        type=int,
        default=0,
        help="--apply 後重算最近 N 個交易日的族群分數",
    )
    instruments_parser = subparsers.add_parser("instruments", help="標的狀態與歷史")
    instruments_subparsers = instruments_parser.add_subparsers(
        dest="instruments_command", required=True
    )
    instruments_repair_parser = instruments_subparsers.add_parser(
        "repair",
        help="依已保存的官方清單與行情 raw 同步標的狀態、補回被丟掉的日線與籌碼（預設 dry-run，重跑冪等）",
    )
    instruments_repair_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
    )
    instruments_repair_parser.add_argument(
        "--include-delisted",
        action="store_true",
        help="為已不在官方清單、DB 也沒有的普通股代號建 delisted／transferred 標的並補歷史",
    )
    instruments_repair_parser.add_argument(
        "--max-status-share",
        type=float,
        default=0.05,
        help="單一交易所一次最多改狀態的現行標的比例（預設 0.05；防呆觸發且已核對官方公告時才放寬）",
    )
    instruments_repair_parser.add_argument(
        "--rescore-days",
        type=int,
        default=0,
        help="--apply 後重算最近 N 個交易日的族群分數",
    )
    news_parser = subparsers.add_parser(
        "news", help="抓取國內／國際財經新聞 feed 並寫入 news_items"
    )
    news_parser.add_argument(
        "--date",
        dest="run_date",
        help="YYYY-MM-DD；只標記 run 日期，未指定使用台北今日",
    )
    news_llm_parser = subparsers.add_parser(
        "news-llm", help="以 claude -p 批次產生新聞摘要、關聯候選與方向判讀"
    )
    news_llm_parser.add_argument(
        "--date",
        dest="run_date",
        help="YYYY-MM-DD；只判讀該台北日收錄的新聞，未指定不限日期",
    )
    news_llm_parser.add_argument(
        "--limit", type=int, default=NEWS_LLM_DEFAULT_LIMIT, help="本次最多判讀則數"
    )
    news_llm_parser.add_argument(
        "--dry-run", action="store_true", help="只列出會送出的批次，不呼叫、不寫 DB"
    )
    args = parser.parse_args()
    if (
        args.command == "daily"
        and args.catchup_sessions is not None
        and args.catchup_sessions < 0
    ):
        parser.error("--catchup-sessions must not be negative")
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
    elif args.command == "market-summary":
        start, end = (
            date.fromisoformat(args.start_date),
            date.fromisoformat(args.end_date),
        )
        if end < start:
            parser.error("--to must not be before --from")
        result = backfill_market_summaries(start, end, force=args.force)
    elif args.command == "schedule-runs":
        result = list_schedule_runs(args.limit, parse_date(args.run_date))
    elif args.command == "backtest":
        result = backtest(
            date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
        )
    elif args.command == "indicators":
        result = run_indicator_batch(parse_date(args.run_date), rebuild=args.rebuild)
    elif args.command == "candidates":
        result = run_candidates(parse_date(args.run_date))
    elif args.command == "track-plans":
        result = run_plan_tracking(parse_date(args.run_date))
    elif args.command == "strategy-levels":
        result = run_strategy_levels(parse_date(args.run_date))
    elif args.command == "candidate-notes":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be at least 1")
        result = run_candidate_notes_batch(
            parse_date(args.run_date), dry_run=args.dry_run, limit=args.limit
        )
    elif args.command == "themes":
        result = sync_themes(args.file)
    elif args.command == "theme-suggestions":
        result = run_theme_suggestions()
    elif args.command == "industry":
        if args.rescore_days < 0 or (args.rescore_days and not args.apply):
            parser.error("--rescore-days needs --apply and must not be negative")
        result = run_industry_repair(apply=args.apply, rescore_days=args.rescore_days)
    elif args.command == "instruments":
        if args.rescore_days < 0 or (args.rescore_days and not args.apply):
            parser.error("--rescore-days needs --apply and must not be negative")
        if not 0 < args.max_status_share <= 1:
            parser.error("--max-status-share must be in (0, 1]")
        result = run_instrument_repair(
            apply=args.apply,
            include_delisted=args.include_delisted,
            rescore_days=args.rescore_days,
            max_status_share=args.max_status_share,
        )
    elif args.command == "news":
        result = run_news_batch(parse_date(args.run_date))
    elif args.command == "news-llm":
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        result = run_news_llm_batch(
            parse_date(args.run_date), limit=args.limit, dry_run=args.dry_run
        )
    else:
        if args.skip_reason:
            result = record_preflight_skip(
                parse_date(args.run_date), reason=args.skip_reason, trigger=args.trigger
            )
        else:
            result = run_daily(
                parse_date(args.run_date),
                months_back=args.months_back,
                trigger=args.trigger,
                force=args.force,
                catchup_sessions=args.catchup_sessions,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "daily":
        sys.exit(DAILY_EXIT_CODES.get(str(result.get("status")), 1))
    if args.command in {"news-llm", "candidate-notes"}:
        sys.exit(NEWS_LLM_EXIT_CODES.get(str(result.get("status")), 1))
    if args.command in {
        "candidates",
        "track-plans",
        "market-summary",
        "strategy-levels",
    } and result.get("status") not in {
        "success",
        "no_data",
    }:
        raise SystemExit(1)
    if (
        args.command in {"themes", "industry", "instruments", "theme-suggestions"}
        and isinstance(result, dict)
        and result.get("status") == "failed"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
