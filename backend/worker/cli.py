from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from . import job as scheduled_job, serve as scheduler

# Before app.config is imported: it reads STOCK_DATA_DIR and creates that
# directory, and a scheduled `job` (or `serve`) has only --data-dir.
os.environ.update(scheduled_job.cli_environment(sys.argv[1:]))

from app.config import DATA_DIR
from app.db import init_db

from .backfill import BACKFILL_SCOPES, chunked_backfill
from .candidate_notes import run_candidate_notes_batch
from .candidates import run_candidates
from .chip_provenance import run_fill_provenance
from .chip_revisions import run_revise_institutional
from .corporate_action_sync import (
    run_corporate_action_check,
    run_corporate_action_rebuild,
    run_corporate_action_reprice,
    run_corporate_action_sync,
)
from .indicator_batch import run_indicator_batch
from .industry_repair import run_industry_repair
from .instrument_repair import run_instrument_repair, run_unmatched_backfill
from .market_summary import backfill_market_summaries
from .mops_events import run_event_backfill
from .news_batch import run_news_batch
from .news_llm import DEFAULT_LIMIT as NEWS_LLM_DEFAULT_LIMIT, run_news_llm_batch
from .pipeline import analyze, backtest, collect, evaluate, run_daily
from .plan_tracking import run_plan_tracking
from .schedule_runs import (
    LOCK_SKIP_REASON,
    PREFLIGHT_SKIP_REASONS,
    list_schedule_runs,
    record_preflight_skip,
)
from .strategy_levels import run_strategy_levels
from .theme_suggestions import run_theme_suggestions
from .themes import sync_themes
from .margin_lists import run_margin_lists
from .no_trade_days import run_no_trade_days
from .trading_calendar import run_trading_calendar


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


def maintenance_guarded(args: argparse.Namespace) -> str | None:
    """The name of a command that writes the database for long, as a daily does (#468).

    Backfills and backtests: with the scheduler running they need maintenance mode
    (worker.job.maintenance_refusal; docs/ops/SCHEDULING.md 維護模式).
    """

    if args.command in {"backfill", "backtest"}:
        return args.command
    if args.command == "events" and args.events_command == "backfill":
        return "events backfill"
    if (
        args.command == "instruments"
        and args.instruments_command == "repair"
        and args.apply
    ):
        return "instruments repair --apply"
    return None


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
        choices=sorted(PREFLIGHT_SKIP_REASONS | {LOCK_SKIP_REASON}),
        help="job 起跑前檢查未通過或另一個 daily job 持有鎖：只記一列 skipped，不執行任何步驟",
    )
    job_parser = subparsers.add_parser(
        "job",
        help="排程工作：鎖、起跑前檢查、逾時與日誌後執行 daily 或 news（＋news-llm）",
    )
    scheduled_job.add_arguments(job_parser)
    serve_parser = subparsers.add_parser(
        "serve",
        help="scheduler 容器的常駐排程：定時執行 job daily、job news 與看門狗（取代工作排程器）",
    )
    scheduler.add_arguments(serve_parser)
    maintenance_parser = subparsers.add_parser(
        "maintenance",
        help="維護模式（#468）：開啟時排程的 daily 與 news 只記 skipped，看門狗與 monitor 照常",
    )
    maintenance_parser.add_argument("action", choices=("on", "off", "status"))
    maintenance_parser.add_argument(
        "--reason", help="開啟或關閉的原因（on、off 必填），記在 logs/maintenance.log"
    )
    maintenance_parser.add_argument(
        "--data-dir", help="資料目錄；預設 STOCK_DATA_DIR（scheduler 容器是 /data）"
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
    margin_lists_parser = subparsers.add_parser(
        "margin-lists",
        help="從已存的官方融資融券餘額 raw 回補融資標的清單 margin_lists（collect 會寫當日；不發網路，內容沒變不改寫）",
    )
    margin_lists_parser.add_argument("--start", help="YYYY-MM-DD；未指定為最早的 raw")
    margin_lists_parser.add_argument("--end", help="YYYY-MM-DD；未指定為最新的 raw")
    no_trade_parser = subparsers.add_parser(
        "no-trade-days",
        help="從已存的官方每日行情 raw 回補官方無成交日 no_trade_days（collect 會寫當日；不發網路，內容沒變不改寫）",
    )
    no_trade_parser.add_argument("--start", help="YYYY-MM-DD；未指定為最早的 raw")
    no_trade_parser.add_argument("--end", help="YYYY-MM-DD；未指定為最新的 raw")
    calendar_parser = subparsers.add_parser(
        "trading-calendar",
        help="抓 TWSE 官方休市表存入 trading_calendar_days（daily 的 trading_calendar 步驟；預設今年與明年，內容沒變不改寫）",
    )
    calendar_parser.add_argument(
        "--year",
        dest="years",
        type=int,
        action="append",
        help="西元年度，可重複；未指定為今年與明年",
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
    actions_parser = subparsers.add_parser(
        "corporate-actions", help="除權息：官方計算結果表回補與因子核對（#386）"
    )
    actions_subparsers = actions_parser.add_subparsers(
        dest="actions_command", required=True
    )
    actions_sync_parser = actions_subparsers.add_parser(
        "sync",
        help="以 TWSE TWT49U／TPEx exDailyQ 回補區間內的除權息事件（預設 dry-run，重跑冪等）",
    )
    actions_sync_parser.add_argument("--start-date", required=True)
    actions_sync_parser.add_argument("--end-date", required=True)
    actions_sync_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
    )
    actions_check_parser = actions_subparsers.add_parser(
        "check", help="列出欄位算出的因子與官方減除股利參考價比不符的列（不寫 DB）"
    )
    actions_check_parser.add_argument("--start-date")
    actions_check_parser.add_argument("--end-date")
    actions_reprice_parser = actions_subparsers.add_parser(
        "reprice",
        help="列出因子改由官方除權息參考價決定的列（#394；預設 dry-run，--apply 只記一筆 run 給 rebuild 用）",
    )
    actions_reprice_parser.add_argument(
        "--apply", action="store_true", help="記錄 reprice run；不改 corporate_actions"
    )
    actions_rebuild_parser = actions_subparsers.add_parser(
        "rebuild",
        help="依 sync／reprice run 改到的標的重算指標、特徵與最早改動日起的族群分數（不重算訊號；重跑冪等）",
    )
    actions_rebuild_parser.add_argument("--run-id", type=int, required=True)
    actions_rebuild_parser.add_argument(
        "--group-scores-from",
        help="接續在族群分數中途停下的 rebuild：跳過指標與特徵，只重算此日起的族群分數",
    )
    events_parser = subparsers.add_parser(
        "events", help="官方重大訊息：MOPS t05st02 依日期查詢（#464）"
    )
    events_subparsers = events_parser.add_subparsers(
        dest="events_command", required=True
    )
    events_backfill_parser = events_subparsers.add_parser(
        "backfill",
        help="逐日查詢區間內每個日曆日的重大訊息清單，寫入事件與已核實查詢日（每請求間隔 3 秒，重跑冪等）",
    )
    events_backfill_parser.add_argument("--start-date", required=True)
    events_backfill_parser.add_argument("--end-date", required=True)
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
        help="為已不在官方清單、DB 也沒有的普通股與 ETF 代號建 delisted／transferred 標的並補歷史",
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
    instruments_backfill_parser = instruments_subparsers.add_parser(
        "backfill-unmatched",
        help="代號已有標的時，以已保存的行情 raw 補寫先前記為 unmatched_bar 的日線（collect 也會做；預設 dry-run，重跑冪等）",
    )
    instruments_backfill_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
    )
    chips_parser = subparsers.add_parser("chips", help="籌碼")
    chips_subparsers = chips_parser.add_subparsers(dest="chips_command", required=True)
    chips_revise_parser = chips_subparsers.add_parser(
        "revise",
        help="依已保存的 T86／insti raw，以較晚 capture 的三大法人值更正既有籌碼列（預設 dry-run，不發網路）",
    )
    chips_revise_parser.add_argument("--start-date", required=True)
    chips_revise_parser.add_argument(
        "--end-date", help="預設與 --start-date 同日；YYYY-MM-DD"
    )
    chips_revise_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
    )
    chips_provenance_parser = chips_subparsers.add_parser(
        "provenance",
        help="依已保存的 raw 與 value_fill_groups，補寫既有籌碼列法人／融資各自的來源（預設 dry-run，不發網路，重跑冪等）",
    )
    chips_provenance_parser.add_argument(
        "--apply", action="store_true", help="寫入 DB；未指定只列出預計變更"
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
    if args.command == "job":
        problem = scheduled_job.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(scheduled_job.run(args))
    if args.command == "serve":
        problem = scheduler.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(scheduler.run(args))
    if args.command == "maintenance":
        data_dir = scheduled_job.resolve_data_dir(args.data_dir or str(DATA_DIR))
        reason = (args.reason or "").strip()
        if args.action != "status" and not reason:
            parser.error(f"maintenance {args.action} needs --reason")
        if args.action == "on":
            result = scheduled_job.maintenance_on(data_dir, reason)
        elif args.action == "off":
            result = scheduled_job.maintenance_off(data_dir, reason)
        else:
            result = scheduled_job.maintenance_status(data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    guarded = maintenance_guarded(args)
    if guarded:
        refusal = scheduled_job.maintenance_refusal(DATA_DIR, guarded)
        if refusal:
            print(refusal, file=sys.stderr)
            sys.exit(scheduled_job.MAINTENANCE_REFUSED_EXIT)
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
    elif args.command == "trading-calendar":
        result = run_trading_calendar(years=args.years)
    elif args.command == "no-trade-days":
        result = run_no_trade_days(parse_date(args.start), parse_date(args.end))
    elif args.command == "margin-lists":
        result = run_margin_lists(parse_date(args.start), parse_date(args.end))
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
    elif (
        args.command == "instruments"
        and args.instruments_command == "backfill-unmatched"
    ):
        result = run_unmatched_backfill(apply=args.apply)
    elif args.command == "events" and args.events_command == "backfill":
        result = run_event_backfill(
            date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
        )
    elif args.command == "corporate-actions":
        if args.actions_command == "sync":
            result = run_corporate_action_sync(
                date.fromisoformat(args.start_date),
                date.fromisoformat(args.end_date),
                apply=args.apply,
            )
        elif args.actions_command == "reprice":
            result = run_corporate_action_reprice(apply=args.apply)
        elif args.actions_command == "rebuild":
            result = run_corporate_action_rebuild(
                args.run_id, group_scores_from=parse_date(args.group_scores_from)
            )
        else:
            result = run_corporate_action_check(
                parse_date(args.start_date), parse_date(args.end_date)
            )
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
    elif args.command == "chips" and args.chips_command == "provenance":
        result = run_fill_provenance(apply=args.apply)
    elif args.command == "chips":
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date) if args.end_date else start
        if end < start:
            parser.error("--end-date must not be before --start-date")
        result = run_revise_institutional(start, end, apply=args.apply)
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
                parse_date(args.run_date),
                reason=args.skip_reason,
                trigger=args.trigger,
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
        "trading-calendar",
    } and result.get("status") not in {
        "success",
        "no_data",
    }:
        raise SystemExit(1)
    if (
        args.command in {"margin-lists", "no-trade-days"}
        and result.get("status") != "success"
    ):
        raise SystemExit(2 if result.get("status") == "partial" else 1)
    if args.command == "chips" and result.get("status") != "success":
        raise SystemExit(2 if result.get("status") == "partial" else 1)
    if (
        args.command in {"themes", "industry", "instruments", "theme-suggestions"}
        and isinstance(result, dict)
        and result.get("status") == "failed"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
