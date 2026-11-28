from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timezone

from . import job as scheduled_job, notify as daily_notify, serve as scheduler
from . import intraday as intraday_alerts, preopen as preopen_check
from . import premarket_ai as premarket_job

# Before app.config is imported: it reads STOCK_DATA_DIR and creates that
# directory, and a scheduled `job` (or `serve`) has only --data-dir.
os.environ.update(scheduled_job.cli_environment(sys.argv[1:]))

from app.config import DATA_DIR, DB_PATH
from app.db import init_db

from .action_tiers import run_action_tiers
from .backfill import BACKFILL_SCOPES, chunked_backfill
from .candidate_notes import notes_after_candidates, run_candidate_notes_batch
from .candidates import run_candidates
from .theme_heat import run_theme_heat, run_theme_heat_range
from .h2_list import backfill_h2
from .x4_list import backfill_x4
from .chip_provenance import run_fill_provenance
from .chip_revisions import run_fill_short_balance, run_revise_institutional
from .corporate_action_sync import (
    run_corporate_action_check,
    run_corporate_action_rebuild,
    run_corporate_action_reprice,
    run_corporate_action_sync,
)
from .index_bars import DEFAULT_FIRST_MONTH as INDEX_BARS_FIRST_MONTH
from .index_bars import run_index_bar_backfill
from .futures_history import DEFAULT_FIRST_MONTH as FUTURES_HISTORY_FIRST_MONTH
from .futures_history import (
    run_futures_collect,
    run_futures_history,
    run_futures_night,
)
from .us_index_bars import run_us_collect
from .indicator_batch import run_indicator_batch
from .industry_repair import run_industry_repair
from .instrument_repair import run_instrument_repair, run_unmatched_backfill
from .market_summary import backfill_market_summaries
from .monthly_revenue import DEFAULT_MONTHS as REVENUE_DEFAULT_MONTHS
from .monthly_revenue import run_revenue_backfill
from .monthly_revenue_company import refusal as monthly_revenue_refusal
from .monthly_revenue_company import (
    run_revenue_company_backfill,
    run_revenue_company_classify,
    run_revenue_transfers,
)
from .mops_events import run_event_backfill
from .news_batch import run_news_batch
from .news_llm import DEFAULT_LIMIT as NEWS_LLM_DEFAULT_LIMIT, run_news_llm_batch
from .news_projection import run_news_project
from .pipeline import analyze, backtest, collect, evaluate, run_daily
from .plan_tracking import run_plan_tracking
from .premarket_score import run_premarket_score
from . import premarket_score_report
from .quarterly_fundamentals import DEFAULT_QUARTERS as FUNDAMENTAL_DEFAULT_QUARTERS
from .quarterly_fundamentals import (
    run_foreign_deadline_recompute,
    run_fundamental_backfill,
)
from .quarterly_xbrl import research_refusal as xbrl_research_refusal
from .quarterly_xbrl import run_xbrl_apply, run_xbrl_fetch
from .valuation_backfill import FEEDS as VALUATION_FEEDS
from .valuation_backfill import run_valuation_backfill
from .schedule_runs import (
    LOCK_SKIP_REASON,
    PREFLIGHT_SKIP_REASONS,
    list_schedule_runs,
    record_preflight_skip,
)
from .strategy_levels import run_strategy_levels
from .candidate_pool import run_candidate_pool, run_morning_pool
from .theme_discovery import run_theme_discovery
from .theme_evidence import verify_themes
from .themes import sync_themes
from .margin_lists import run_margin_lists
from .no_trade_days import run_no_trade_days
from .trading_halts import run_trading_halts
from .sources import TWSE_QUOTES_FIRST_DATE, set_minimum_host_interval
from .trading_calendar import run_trading_calendar

# Every backfill command keeps at least this between two requests to one
# official host (#692 decision D3: a bulk history backfill must not get the
# sources to block the daily).  The daily's intervals are unchanged.
BACKFILL_HOST_INTERVAL_SECONDS = 3.0


# daily exit codes, so Task Scheduler's "Last Run Result" shows an incomplete day.
DAILY_EXIT_CODES = {
    "success": 0,
    "skipped": 0,
    "non_trading_day": 0,
    "non_trading_unconfirmed": 0,
    "partial": 2,
}
# index-bars us-collect (#568): a skip and a run that found D − 1 stored are no failure.
US_COLLECT_EXIT_CODES = {
    "success": 0,
    "already_complete": 0,
    "skipped": 0,
    "partial": 2,
}
# index-bars futures-night (#1040): a closed day, a night already stored and a
# job's skip are no failure; a night not listed yet is partial.
FUTURES_NIGHT_EXIT_CODES = {
    "success": 0,
    "already_complete": 0,
    "non_trading_day": 0,
    "skipped": 0,
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


# Printed as a held command starts (#468 AC-6 decision 6646001167).
MAINTENANCE_HINT = (
    "{command}: 已開維護模式（作業持有，每分鐘心跳，結束時自動關閉）：排程的 daily 與 news"
    " 期間只記 skipped，看門狗與 monitor 照常。預估會跨過 21:30 時，請改在 23:30 後開始："
    "21:30 的 daily 會被跳過，要等維護模式解除才補跑。"
)


def maintenance_guarded(args: argparse.Namespace) -> str | None:
    """The name of a command that writes the database for long, as a daily does (#468).

    Backfills and backtests run holding maintenance mode (worker.job.MaintenanceHold;
    docs/ops/SCHEDULING.md 維護模式): the scheduled daily and news skip meanwhile.
    """

    if args.command in {"backfill", "backtest"}:
        return args.command
    if args.command == "events" and args.events_command == "backfill":
        return "events backfill"
    if args.command == "fundamentals" and args.fundamentals_command == "backfill":
        return "fundamentals backfill"
    if (
        args.command == "fundamentals"
        and args.fundamentals_command == "xbrl-apply"
        and not args.dry_run
    ):
        # Writes the research DB; a research batch holding maintenance mode refuses it.
        return "fundamentals xbrl-apply"
    if (
        args.command == "fundamentals"
        and args.fundamentals_command == "foreign-deadlines"
        and args.apply
    ):
        return "fundamentals foreign-deadlines --apply"
    if args.command == "revenue" and args.revenue_command == "backfill":
        return "revenue backfill"
    if args.command == "valuation" and args.valuation_command == "backfill":
        return "valuation backfill"
    if args.command == "revenue" and args.revenue_command == "transfers" and args.apply:
        return "revenue transfers --apply"
    if (
        args.command == "revenue"
        and args.revenue_command in {"company-classify", "company-backfill"}
        and not args.plan
    ):
        return f"revenue {args.revenue_command}"
    if args.command == "index-bars" and args.index_bars_command in {
        "backfill",
        "futures-history",
    }:
        return f"index-bars {args.index_bars_command}"
    if (
        args.command == "instruments"
        and args.instruments_command == "repair"
        and args.apply
    ):
        return "instruments repair --apply"
    if args.command == "chips" and args.chips_command == "short-balance" and args.apply:
        return "chips short-balance --apply"
    if args.command == "strategy-lists" and args.strategy_lists_command == "backfill":
        return "strategy-lists backfill"
    return None


# Taipei hours of the scheduled daily (docs/ops/SCHEDULING.md), from 15 minutes
# before 21:30: a command in DAILY_WINDOW_REFUSED does not start then, so the
# maintenance mode it holds never makes a daily skip.  ``chips short-balance``
# also stops between captures from 21:25 (chip_revisions).
DAILY_WINDOW = (time(21, 15), time(23, 30))
DAILY_WINDOW_REFUSED = {
    "chips short-balance --apply",
    "strategy-lists backfill",
    "fundamentals foreign-deadlines --apply",
}


def in_daily_window(moment: datetime | None = None) -> bool:
    now = (moment or datetime.now(timezone.utc)).astimezone(scheduled_job.TAIPEI)
    return DAILY_WINDOW[0] <= now.time() < DAILY_WINDOW[1]


def _utc_naive_moment(value: str | None) -> datetime:
    """``--now`` (Taipei when it has no zone; now when absent) as UTC-naive."""

    taipei = scheduled_job.TAIPEI
    moment = datetime.now(taipei) if not value else datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=taipei)
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="台股研究工具 Python worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="建立 SQLite 資料表")
    subparsers.add_parser("analyze", help="計算技術特徵與族群排名")
    evaluate_parser = subparsers.add_parser("evaluate", help="更新訊號追蹤狀態")
    evaluate_parser.add_argument(
        "--force",
        action="store_true",
        help="全量重算：不跳過已結算的訊號（修正追蹤程式或回補後用，#841）",
    )
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
    notify_parser = subparsers.add_parser(
        "notify",
        help="每日 Telegram 通知（#728）：今日名單與隔夜美股；--dry-run 只印出、--send 送出",
    )
    daily_notify.add_arguments(notify_parser)
    preopen_parser = subparsers.add_parser(
        "preopen",
        help="開盤前檢查（#755）：今日名單每檔在名單產生之後才收到的新聞與 AI 判讀，存進 preopen_news_checks",
    )
    preopen_check.add_arguments(preopen_parser)
    premarket_parser = subparsers.add_parser(
        "premarket-ai",
        help="早盤 AI 判讀（#1041）：截止 08:15 的輸入快照、claude -p（sonnet）、核對，存進 premarket_ai_readings",
    )
    premarket_job.add_arguments(premarket_parser)
    intraday_parser = subparsers.add_parser(
        "intraday",
        help="盤中即時通知（#801）：今日名單與我的追蹤觸及規則價位時傳 Telegram（富果行情）；--dry-run 不送、--send 送出",
    )
    intraday_alerts.add_arguments(intraday_parser)
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
    maintenance_parser.add_argument(
        "--only-manual",
        action="store_true",
        help="只給 off：只關手動開的（沒有心跳）；作業持有的不動（deploy.sh 用）",
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
        help="以目前評分版本產生每日候選清單（同日同版本重跑冪等），接著補同一天還沒完成的 AI 說明",
    )
    candidates_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD；未指定使用最新訊號日"
    )
    candidates_parser.add_argument(
        "--skip-notes",
        action="store_true",
        help="只產生候選，不接著跑 candidate-notes（之後可手動補）",
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
    score_parser = subparsers.add_parser(
        "premarket-score",
        help="早盤 AI 判讀對答案（#1043，daily 的 premarket_score 步驟）：到 --date 為止已到期、還沒寫的 horizon 寫進 premarket_ai_scores；同日重跑不重複寫",
    )
    score_parser.add_argument(
        "--date",
        dest="run_date",
        help="YYYY-MM-DD 目標交易日（不讀之後的日 K）；未指定使用 DB 最新日線日",
    )
    score_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只算、印出各列的 outcome，不寫 DB",
    )
    report_parser = subparsers.add_parser(
        "premarket-score-report",
        help="早盤 AI 判讀對答案的月報（#1043）：累積到該月底的數字，markdown，不寫 DB",
    )
    report_parser.add_argument("--month", required=True, help="YYYY-MM")
    report_parser.add_argument("--out", help="寫到這個檔；未指定印到 stdout")
    levels_parser = subparsers.add_parser(
        "strategy-levels",
        help="計算訊號的條件價位 STRATEGY_LEVELS_VERSION（daily 的 strategy_levels 步驟；同日重跑冪等）",
    )
    levels_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD 訊號日；未指定使用最新訊號日"
    )
    heat_parser = subparsers.add_parser(
        "theme-heat",
        help="計算題材熱度 theme_heat_v1（daily 的 theme_heat 步驟；逐日重算，同日重跑改寫，#1017）",
    )
    heat_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD 交易日；只算這一天"
    )
    heat_parser.add_argument(
        "--since", help="YYYY-MM-DD 起日；與 --until 一起逐個交易日重算"
    )
    heat_parser.add_argument("--until", help="YYYY-MM-DD 迄日；未指定為 --since 當天")
    heat_parser.add_argument(
        "--weekly",
        action="store_true",
        help="輸出每週最後一個交易日的排名（題材 id 與熱度）",
    )
    lists_parser = subparsers.add_parser(
        "strategy-lists", help="策略名單（接近年高前 20、盈餘殖利率前 20；#1014）"
    )
    lists_subparsers = lists_parser.add_subparsers(
        dest="strategy_lists_command", required=True
    )
    lists_backfill_parser = lists_subparsers.add_parser(
        "backfill",
        help="逐日回補最近 N 個交易日的名單（「近 60 日入選過」，#1021）；已存的日子不重寫",
    )
    lists_backfill_parser.add_argument(
        "--strategy",
        choices=("h2", "x4", "all"),
        default="all",
        help="h2、x4 或 all（預設，依序 h2、x4）",
    )
    lists_backfill_parser.add_argument(
        "--sessions", type=int, default=60, help="交易日數（預設 60）"
    )
    lists_backfill_parser.add_argument(
        "--until", help="YYYY-MM-DD 最後一個交易日；未指定使用 DB 最新的 stock 日線日"
    )
    lists_backfill_parser.add_argument(
        "--force", action="store_true", help="已存的日子也重算改寫"
    )
    discovery_parser = subparsers.add_parser(
        "theme-discovery",
        help="量價共振分群與候選題材（daily 的 theme_discovery 步驟；同日重跑改寫分群，#1018）",
    )
    discovery_parser.add_argument(
        "--date", dest="run_date", required=True, help="YYYY-MM-DD 交易日"
    )
    discovery_parser.add_argument(
        "--no-ai",
        action="store_true",
        help="只重算並存分群，不呼叫 claude -p、不寫候選題材（重放用）",
    )
    pool_parser = subparsers.add_parser(
        "candidate-pool",
        help="候選池 candidate_pool_v1（daily 的 candidate_pool 步驟與 preopen 的早上那輪；寫了不改，#1020）",
    )
    pool_parser.add_argument(
        "--date",
        dest="run_date",
        required=True,
        help="YYYY-MM-DD 交易日（晚上那輪的資料日）",
    )
    pool_parser.add_argument(
        "--phase",
        choices=("evening", "morning"),
        default="evening",
        help="evening（預設）或 morning（只補晚上之後收進來的新聞點到的股票）",
    )
    pool_parser.add_argument(
        "--now",
        help=(
            "morning 的檢查時刻：ISO 8601，沒有時區時為台北時間；預設現在。"
            "窗口收到這個時刻為止的新聞，晚於下一個交易日開盤就含開盤後的新聞，"
            "寫了不改：不要拿它補過去的日期"
        ),
    )
    pool_parser.add_argument(
        "--dry-run", action="store_true", help="只計算並印出結果，不寫 DB"
    )
    tiers_parser = subparsers.add_parser(
        "action-tiers",
        help="預算首頁與行動頁的 action tier 日資料（daily 的 action_tiers 步驟；同日重跑改寫，#476）",
    )
    tiers_parser.add_argument(
        "--date", dest="run_date", help="YYYY-MM-DD 交易日；未指定使用頁面的最新官方日"
    )
    subparsers.add_parser(
        "news-project",
        help="把全部官方事件投影成新聞並記下指紋（部署改投影規則的版本後跑一次，#476）",
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
    halts_parser = subparsers.add_parser(
        "trading-halts",
        help="抓 TWSE TWTAUU、TPEx revivt 的減資停止買賣存入 trading_halts（collect 會抓當日前 10 天到後 60 天恢復的；每個交易所 1 個請求，內容沒變不改寫）",
    )
    halts_parser.add_argument(
        "--start", required=True, help="YYYY-MM-DD，恢復買賣日的起日"
    )
    halts_parser.add_argument("--end", help="YYYY-MM-DD；未指定為今天後 60 天")
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
    themes_verify_parser = themes_subparsers.add_parser(
        "verify",
        help="抓證據頁核對成員：quote 逐字在頁面上、quote 含題材詞、代號是股票（不寫 DB）",
    )
    themes_verify_parser.add_argument(
        "--file", help="題材表 JSON；未指定使用 backend/data/themes/themes_v1.json"
    )
    themes_verify_parser.add_argument(
        "--theme",
        action="append",
        dest="theme_ids",
        help="只核對這個題材 id（可重複）；未指定為全部",
    )
    themes_verify_parser.add_argument(
        "--since", help="只核對生效日在這天（YYYY-MM-DD）以後的成員"
    )
    themes_verify_parser.add_argument(
        "--pages-dir", help="讀已存的證據頁目錄（含 index.json），不連網"
    )
    themes_verify_parser.add_argument(
        "--save-dir", help="把抓到的證據頁與 index.json 存到這個目錄"
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
    fundamentals_parser = subparsers.add_parser(
        "fundamentals", help="季度 EPS 與營收：MOPS t163sb04 彙總報表（#529）"
    )
    fundamentals_subparsers = fundamentals_parser.add_subparsers(
        dest="fundamentals_command", required=True
    )
    fundamentals_backfill_parser = fundamentals_subparsers.add_parser(
        "backfill",
        help="上市、上櫃各季 1 個請求（間隔 3 秒），回補近 N 季的累計營收與基本 EPS，重跑冪等",
    )
    fundamentals_backfill_parser.add_argument(
        "--quarters", type=int, default=FUNDAMENTAL_DEFAULT_QUARTERS
    )
    fundamentals_backfill_parser.add_argument(
        "--end-quarter", help="YYYYQn；預設是最近一個已結束的季度"
    )
    xbrl_fetch_parser = fundamentals_subparsers.add_parser(
        "xbrl-fetch",
        help="下載 MOPS 季度 XBRL 整包到目錄（一季 1 個請求（截斷時整包重抓，最多 3 個）、間隔 5 秒、不碰 DB；已有的不重抓，#781）",
    )
    xbrl_apply_parser = fundamentals_subparsers.add_parser(
        "xbrl-apply",
        help="把目錄裡的季度 XBRL 整包寫進下市、轉板標的缺的季報 EPS（先和 t163sb04 核對，不同就停；重跑冪等，#781）",
    )
    for xbrl_parser in (xbrl_fetch_parser, xbrl_apply_parser):
        xbrl_parser.add_argument("--start", required=True, help="YYYYQn，最早 2013Q1")
        xbrl_parser.add_argument("--end", required=True, help="YYYYQn")
        xbrl_parser.add_argument(
            "--dir", required=True, help="整包與 manifest.json 的目錄"
        )
    xbrl_apply_parser.add_argument(
        "--dry-run", action="store_true", help="不寫入，只印每季的計數"
    )
    xbrl_apply_parser.add_argument(
        "--exclude-file", help="JSON 陣列：不寫入的 instrument id（代號重用的舊公司）"
    )
    foreign_deadlines_parser = fundamentals_subparsers.add_parser(
        "foreign-deadlines",
        help="把已存的外國發行人 2021 年起 Q2 列的可得日改成它們的法定期限 8/31（只動 statutory_deadline 的列，0 個請求，重跑冪等，#1101）",
    )
    foreign_deadlines_parser.add_argument(
        "--apply", action="store_true", help="寫入；不加只印要改的列"
    )
    valuation_parser = subparsers.add_parser(
        "valuation",
        help="研究 DB 的股價淨值比、發行股數與外資持股（#1075、#1121）：TWSE BWIBBU_d／MI_QFIIS、TPEx peQryDate／insti/qfii、已存的上櫃行情表",
    )
    valuation_subparsers = valuation_parser.add_subparsers(
        dest="valuation_command", required=True
    )
    valuation_backfill_parser = valuation_subparsers.add_parser(
        "backfill",
        help="逐交易日回補（每 host 間隔 3.5 秒、台北 21:15～23:30 等待；已成功的日子不再請求，重跑冪等）；只在研究 DB 跑",
    )
    valuation_backfill_parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    valuation_backfill_parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    valuation_backfill_parser.add_argument(
        "--feed",
        action="append",
        choices=sorted(VALUATION_FEEDS),
        help="只跑這個 feed（可重複）；預設六個都跑（twse-foreign 讀 twse-shares 存的 raw，不送請求）",
    )
    valuation_backfill_parser.add_argument(
        "--reapply",
        action="store_true",
        help="不送請求：有已存 raw 的日子（成功的，或回應讀不懂而失敗的）改讀 raw 重寫（沒有差異時 changed 0）",
    )
    valuation_backfill_parser.add_argument(
        "--fallback-raw-dir",
        help="raw 檔不在本 volume 時，到這個目錄找同一個相對路徑（正式 volume 的 raw，唯讀掛載）",
    )
    revenue_parser = subparsers.add_parser(
        "revenue", help="月營收：MOPS t21sc03 營業收入統計表（#530）"
    )
    revenue_subparsers = revenue_parser.add_subparsers(
        dest="revenue_command", required=True
    )
    revenue_backfill_parser = revenue_subparsers.add_parser(
        "backfill",
        help="上市、上櫃各月國內與國外公司各 1 頁（間隔 3 秒），回補近 N 個月的月營收，重跑冪等",
    )
    revenue_backfill_parser.add_argument(
        "--months", type=int, default=REVENUE_DEFAULT_MONTHS
    )
    revenue_backfill_parser.add_argument(
        "--end-month", help="YYYY-MM；預設是上個月（最近一個已結束的月份）"
    )
    revenue_transfers_parser = revenue_subparsers.add_parser(
        "transfers",
        help="研究 DB：轉板公司舊標的的月營收，從另一交易所的同一家公司複製（0 個請求，#782）",
    )
    revenue_transfers_parser.add_argument(
        "--apply", action="store_true", help="寫入；不加只印對應與月數"
    )
    for name, text in (
        (
            "company-classify",
            "研究 DB：每檔下市股問 1 次 MOPS 單一公司月營收（最後一個有日線的月），"
            "分成查得到與不繼續公開發行（間隔 5 秒，#782）",
        ),
        (
            "company-backfill",
            "研究 DB：查得到的下市股，每家每月 1 個請求補月營收（間隔 5 秒，#782）",
        ),
    ):
        company_parser = revenue_subparsers.add_parser(name, help=text)
        company_parser.add_argument(
            "--plan", action="store_true", help="只印對象與請求數，不發請求、不寫入"
        )
        company_parser.add_argument(
            "--max-requests", type=int, help="這次最多發幾個請求（已存的回應不算）"
        )
    index_bars_parser = subparsers.add_parser(
        "index-bars",
        help="加權、櫃買指數的日 K（#552）與指數、台指期、美股的歷史回補（#563）",
    )
    index_bars_subparsers = index_bars_parser.add_subparsers(
        dest="index_bars_command", required=True
    )
    index_bars_backfill_parser = index_bars_subparsers.add_parser(
        "backfill",
        help="每月每個指數 2 個請求（間隔 3 秒），寫入真實日 K、把加權的收盤列原地升級，重跑冪等",
    )
    index_bars_backfill_parser.add_argument(
        "--from-month",
        default=INDEX_BARS_FIRST_MONTH,
        help=f"YYYY-MM；預設 {INDEX_BARS_FIRST_MONTH}",
    )
    index_bars_backfill_parser.add_argument(
        "--to-month", help="YYYY-MM；預設是本月（台北）"
    )
    index_bars_backfill_parser.add_argument(
        "--force", action="store_true", help="同來源已存的列也以報表值改寫"
    )
    index_bars_us_parser = index_bars_subparsers.add_parser(
        "us-collect",
        help=(
            "美股四檔抓到台北前一天：每檔 1 個 FinMind 請求；沒有列時從 2023-09-01 起，"
            "有列時從最後一列往前 10 天（#568）"
        ),
    )
    index_bars_us_parser.add_argument(
        "--date", help="台北日期 YYYY-MM-DD，抓到它的前一天；預設今天（台北）"
    )
    index_bars_us_parser.add_argument(
        "--force",
        action="store_true",
        help="四檔都已存到前一個平日也照樣請求（FinMind 列的更正不需要它；FRED 列一律不改）",
    )
    index_bars_us_parser.add_argument(
        "--trigger", choices=("scheduler", "manual"), default="manual"
    )
    index_bars_us_parser.add_argument("--skip-reason", help=argparse.SUPPRESS)
    index_bars_futures_parser = index_bars_subparsers.add_parser(
        "futures-history",
        help="台指期近月從期交所網站 futDataDown 回補 DB 沒有的日子（不含今天）：每月 1 個請求、間隔 3 秒（#563、#586）",
    )
    index_bars_futures_parser.add_argument(
        "--from-month",
        default=FUTURES_HISTORY_FIRST_MONTH,
        help=f"YYYY-MM；預設 {FUTURES_HISTORY_FIRST_MONTH}",
    )
    index_bars_futures_parser.add_argument(
        "--to-month", help="YYYY-MM；預設是本月（台北）"
    )
    index_bars_futures_parser.add_argument(
        "--force", action="store_true", help="同來源已存的列也以報表值改寫"
    )
    index_bars_subparsers.add_parser(
        "futures-collect",
        help=(
            "只跑 collect 的台指期這段：OpenAPI 1 個請求、存檔內那天，"
            "再補今天之前 10 個交易日的缺日（futDataDown 最多 2 個請求，#586）"
        ),
    )
    index_bars_night_parser = index_bars_subparsers.add_parser(
        "futures-night",
        help=(
            "台指期近月夜盤（期交所 futDataDown 的盤後列，日期是期交所的下一個交易日）"
            "存進 futures_night_bars：1 個請求（#1040）"
        ),
    )
    night_range = index_bars_night_parser.add_mutually_exclusive_group()
    night_range.add_argument(
        "--date",
        help="YYYY-MM-DD：期交所歸屬的交易日（前一晚的夜盤）；預設今天（台北）",
    )
    night_range.add_argument(
        "--month", help="YYYY-MM：一次讀整月（到今天為止），回補用"
    )
    index_bars_night_parser.add_argument(
        "--force",
        action="store_true",
        help="已存的夜盤也重抓，值不同時改寫；休市日也照樣請求",
    )
    index_bars_night_parser.add_argument(
        "--trigger", choices=("scheduler", "manual"), default="manual"
    )
    index_bars_night_parser.add_argument("--skip-reason", help=argparse.SUPPRESS)
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
    chips_short_parser = chips_subparsers.add_parser(
        "short-balance",
        help="依各列融資組引用的已保存融資 raw，補寫空的融券餘額 short_balance（預設 dry-run，不發網路，只補空值，重跑冪等）",
    )
    chips_short_parser.add_argument("--start-date", help="YYYY-MM-DD；預設不限")
    chips_short_parser.add_argument("--end-date", help="YYYY-MM-DD；預設不限")
    chips_short_parser.add_argument(
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
    if args.command == "backfill":
        try:
            backfill_start = date.fromisoformat(args.start_date)
        except ValueError:
            parser.error(f"--start-date must be YYYY-MM-DD, got {args.start_date!r}")
    if args.command == "backfill" and backfill_start < TWSE_QUOTES_FIRST_DATE:
        # MI_INDEX answers nothing before 2004-02-11 (Issue #692).
        parser.error(
            f"--start-date must not be before {TWSE_QUOTES_FIRST_DATE.isoformat()}"
            "（TWSE MI_INDEX 最早的交易日）"
        )
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
    if args.command == "notify":
        problem = daily_notify.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(daily_notify.run(args))
    if args.command == "preopen":
        problem = preopen_check.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(preopen_check.run(args))
    if args.command == "premarket-score-report":
        problem = premarket_score_report.month_problem(args.month)
        if problem:
            parser.error(problem)
        text = premarket_score_report.run(args.month, args.out)
        if not args.out:
            print(text)
        return
    if args.command == "premarket-ai":
        problem = premarket_job.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(premarket_job.run(args))
    if args.command == "intraday":
        problem = intraday_alerts.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(intraday_alerts.run(args))
    if args.command == "maintenance":
        data_dir = scheduled_job.resolve_data_dir(args.data_dir or str(DATA_DIR))
        reason = (args.reason or "").strip()
        if args.action != "status" and not reason:
            parser.error(f"maintenance {args.action} needs --reason")
        if args.only_manual and args.action != "off":
            parser.error("--only-manual applies only to maintenance off")
        if args.action == "on":
            result = scheduled_job.maintenance_on(data_dir, reason)
        elif args.action == "off":
            off = (
                scheduled_job.maintenance_off_if_manual
                if args.only_manual
                else scheduled_job.maintenance_off
            )
            result = off(data_dir, reason)
        else:
            result = scheduled_job.maintenance_status(data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    refused = research_command_refusal(args)
    if refused is not None:
        # Before maintenance mode and before any session: on the production
        # volume a hold would write the production marker and log (#781;
        # #782 review 6895006123 3).
        print(
            json.dumps(
                {"status": "refused", "error": refused}, ensure_ascii=False, indent=2
            )
        )
        sys.exit(2)
    guarded = maintenance_guarded(args)
    if guarded in DAILY_WINDOW_REFUSED and in_daily_window():
        print(
            f"{guarded}: 台北 21:15～23:30 接近或在 daily 時段，不起跑；請在 23:30 後再跑。",
            file=sys.stderr,
        )
        sys.exit(scheduled_job.MAINTENANCE_REFUSED_EXIT)
    if not guarded:
        run_command(args, parser)
        return
    try:
        with scheduled_job.MaintenanceHold(
            scheduled_job.resolve_data_dir(str(DATA_DIR)),
            guarded,
            reason=" ".join(sys.argv[1:]),
        ):
            print(MAINTENANCE_HINT.format(command=guarded), file=sys.stderr, flush=True)
            run_command(args, parser)
    except scheduled_job.MaintenanceRefused as exc:
        print(exc, file=sys.stderr)
        sys.exit(scheduled_job.MAINTENANCE_REFUSED_EXIT)
    except scheduled_job.MaintenanceLost as exc:
        print(f"{guarded}: stopped, maintenance mode was lost: {exc}", file=sys.stderr)
        sys.exit(scheduled_job.MAINTENANCE_LOST_EXIT)


RESEARCH_REVENUE_COMMANDS = {"transfers", "company-classify", "company-backfill"}


def research_command_refusal(args: argparse.Namespace) -> str | None:
    """Why a research-database-only command may not run here; None otherwise.

    ``fundamentals xbrl-apply`` (#781), the revenue commands of #782 and
    ``valuation backfill`` (#1075).
    """

    if args.command == "fundamentals" and args.fundamentals_command == "xbrl-apply":
        return xbrl_research_refusal(DB_PATH)
    if args.command == "revenue" and args.revenue_command in RESEARCH_REVENUE_COMMANDS:
        return monthly_revenue_refusal(DB_PATH)
    if args.command == "valuation":
        return xbrl_research_refusal(DB_PATH)
    return None


def backfill_command(args: argparse.Namespace) -> str | None:
    """The name of a command that asks the official hosts for history (Issue #692).

    These keep at least ``BACKFILL_HOST_INTERVAL_SECONDS`` between two requests
    to any one host; the daily (and its catch-up) keeps the per-host intervals.
    """

    if args.command in {"backfill", "trading-halts"}:
        return args.command
    if args.command == "corporate-actions" and args.actions_command == "sync":
        return "corporate-actions sync"
    if args.command == "fundamentals" and args.fundamentals_command == "xbrl-fetch":
        return "fundamentals xbrl-fetch"
    for command, sub in (
        ("events", "events_command"),
        ("fundamentals", "fundamentals_command"),
        ("revenue", "revenue_command"),
        ("valuation", "valuation_command"),
    ):
        if args.command == command and getattr(args, sub, None) == "backfill":
            return f"{command} backfill"
    if args.command == "index-bars" and args.index_bars_command in {
        "backfill",
        "futures-history",
    }:
        return f"index-bars {args.index_bars_command}"
    return None


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Run one command; a backfill holds the 3-second floor only while it runs.

    The floor is a process-wide value (sources.set_minimum_host_interval), so
    it is restored when the command returns or raises (#701 review): nothing
    after it in the same process (another command, the next test) keeps it.
    """

    if not backfill_command(args):
        _run_command(args, parser)
        return
    previous = set_minimum_host_interval(BACKFILL_HOST_INTERVAL_SECONDS)
    try:
        _run_command(args, parser)
    finally:
        set_minimum_host_interval(previous)


def _run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "init-db":
        init_db()
        result = {"status": "success"}
    elif args.command == "analyze":
        result = analyze()
    elif args.command == "evaluate":
        result = evaluate(force=args.force)
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
        # The notes' outcome is only notes_status: the exit code follows the list.
        result = notes_after_candidates(
            run_candidates(parse_date(args.run_date)), skip=args.skip_notes
        )
    elif args.command == "track-plans":
        result = run_plan_tracking(parse_date(args.run_date))
    elif args.command == "premarket-score":
        result = run_premarket_score(parse_date(args.run_date), dry_run=args.dry_run)
    elif args.command == "strategy-levels":
        result = run_strategy_levels(parse_date(args.run_date))
    elif args.command == "action-tiers":
        result = run_action_tiers(parse_date(args.run_date))
    elif args.command == "theme-heat":
        since, until = parse_date(args.since), parse_date(args.until)
        if until is not None and since is None:
            parser.error("theme-heat 的 --until 要搭配 --since")
        if since is not None:
            result = run_theme_heat_range(since, until or since, weekly=args.weekly)
        elif args.run_date:
            result = run_theme_heat(parse_date(args.run_date))
        else:
            parser.error("theme-heat 要 --date 或 --since")
    elif args.command == "strategy-lists" and args.strategy_lists_command == "backfill":
        if args.sessions < 1:
            parser.error("strategy-lists backfill 的 --sessions 要 ≥ 1")
        runners = {"h2": backfill_h2, "x4": backfill_x4}
        keys = ("h2", "x4") if args.strategy == "all" else (args.strategy,)
        until = parse_date(args.until)
        runs = [runners[key](until, args.sessions, force=args.force) for key in keys]
        result = {
            "status": "success"
            if all(run["status"] == "success" for run in runs)
            else "failed",
            "strategies": runs,
        }
    elif args.command == "theme-discovery":
        result = run_theme_discovery(
            date.fromisoformat(args.run_date), ai=not args.no_ai
        )
    elif args.command == "candidate-pool":
        pool_date = date.fromisoformat(args.run_date)
        if args.phase == "evening":
            if args.now:
                parser.error("candidate-pool 的 --now 只給 --phase morning")
            result = run_candidate_pool(pool_date, dry_run=args.dry_run)
        else:
            try:
                moment = _utc_naive_moment(args.now)
            except ValueError:
                parser.error(
                    f"candidate-pool 的 --now 要是 ISO 8601，收到 {args.now!r}"
                )
            result = run_morning_pool(pool_date, moment, dry_run=args.dry_run)
    elif args.command == "news-project":
        result = run_news_project()
    elif args.command == "trading-calendar":
        result = run_trading_calendar(years=args.years)
    elif args.command == "no-trade-days":
        result = run_no_trade_days(parse_date(args.start), parse_date(args.end))
    elif args.command == "trading-halts":
        result = run_trading_halts(
            date.fromisoformat(args.start),
            date.fromisoformat(args.end) if args.end else None,
        )
    elif args.command == "margin-lists":
        result = run_margin_lists(parse_date(args.start), parse_date(args.end))
    elif args.command == "candidate-notes":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be at least 1")
        result = run_candidate_notes_batch(
            parse_date(args.run_date), dry_run=args.dry_run, limit=args.limit
        )
    elif args.command == "themes" and args.themes_command == "verify":
        try:
            since = parse_date(args.since)
        except ValueError:
            parser.error("--since must be YYYY-MM-DD")
        result = verify_themes(
            args.file,
            theme_ids=args.theme_ids,
            since=since,
            pages_dir=args.pages_dir,
            save_dir=args.save_dir,
        )
    elif args.command == "themes":
        result = sync_themes(args.file)
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
    elif args.command == "fundamentals" and args.fundamentals_command == "backfill":
        result = run_fundamental_backfill(args.quarters, args.end_quarter)
    elif args.command == "fundamentals" and args.fundamentals_command == "xbrl-fetch":
        result = run_xbrl_fetch(args.dir, args.start, args.end)
    elif (
        args.command == "fundamentals"
        and args.fundamentals_command == "foreign-deadlines"
    ):
        result = run_foreign_deadline_recompute(args.apply)
    elif args.command == "fundamentals" and args.fundamentals_command == "xbrl-apply":
        result = run_xbrl_apply(
            args.dir,
            args.start,
            args.end,
            dry_run=args.dry_run,
            exclude_file=args.exclude_file,
        )
    elif args.command == "valuation" and args.valuation_command == "backfill":
        result = run_valuation_backfill(
            args.start,
            args.end,
            feeds=args.feed,
            reapply=args.reapply,
            fallback_raw_dir=args.fallback_raw_dir,
        )
    elif args.command == "revenue" and args.revenue_command == "backfill":
        result = run_revenue_backfill(args.months, args.end_month)
    elif args.command == "revenue" and args.revenue_command == "transfers":
        result = run_revenue_transfers(args.apply, DB_PATH)
    elif args.command == "revenue" and args.revenue_command == "company-classify":
        result = run_revenue_company_classify(args.plan, args.max_requests, DB_PATH)
    elif args.command == "revenue" and args.revenue_command == "company-backfill":
        result = run_revenue_company_backfill(args.plan, args.max_requests, DB_PATH)
    elif args.command == "index-bars" and args.index_bars_command == "backfill":
        result = run_index_bar_backfill(
            args.from_month, args.to_month, force=args.force
        )
    elif args.command == "index-bars" and args.index_bars_command == "us-collect":
        result = run_us_collect(
            session=date.fromisoformat(args.date) if args.date else None,
            force=args.force,
            trigger=args.trigger,
            skip_reason=args.skip_reason,
        )
    elif args.command == "index-bars" and args.index_bars_command == "futures-history":
        result = run_futures_history(args.from_month, args.to_month, force=args.force)
    elif args.command == "index-bars" and args.index_bars_command == "futures-collect":
        result = run_futures_collect()
    elif args.command == "index-bars" and args.index_bars_command == "futures-night":
        result = run_futures_night(
            args.date,
            args.month,
            force=args.force,
            trigger=args.trigger,
            skip_reason=args.skip_reason,
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
    elif args.command == "chips" and args.chips_command == "short-balance":
        start = parse_date(args.start_date)
        end = parse_date(args.end_date)
        if start and end and end < start:
            parser.error("--end-date must not be before --start-date")
        result = run_fill_short_balance(start, end, apply=args.apply)
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
        "premarket-score",
        "market-summary",
        "strategy-levels",
        "trading-calendar",
        "action-tiers",
        "news-project",
        "theme-heat",
        "theme-discovery",
        "strategy-lists",
        "candidate-pool",
    } and result.get("status") not in {
        "success",
        "no_data",
    }:
        raise SystemExit(1)
    if (
        args.command in {"margin-lists", "no-trade-days", "trading-halts"}
        and result.get("status") != "success"
    ):
        raise SystemExit(2 if result.get("status") == "partial" else 1)
    if args.command == "index-bars" and args.index_bars_command == "us-collect":
        sys.exit(US_COLLECT_EXIT_CODES.get(str(result.get("status")), 1))
    if args.command == "index-bars" and args.index_bars_command == "futures-night":
        sys.exit(FUTURES_NIGHT_EXIT_CODES.get(str(result.get("status")), 1))
    if args.command == "revenue" and result.get("status") == "refused":
        raise SystemExit(2)
    if (
        args.command in {"fundamentals", "revenue", "index-bars", "valuation"}
        and result.get("status") != "success"
    ):
        raise SystemExit(2 if result.get("status") == "partial" else 1)
    if args.command == "chips" and result.get("status") != "success":
        raise SystemExit(2 if result.get("status") == "partial" else 1)
    if (
        args.command in {"themes", "industry", "instruments"}
        and isinstance(result, dict)
        and result.get("status") == "failed"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
