"""Ordered Alembic revision ids, the one definition of the migration chain.

Imports nothing and does no I/O, so the worker and the Alembic environment can load it
without app.config, whose import-time mkdir creates the configured data/raw directories.
Append the new head here together with its alembic/versions file.
"""

REVISIONS = (
    "0001_schema_v1",
    "0002_instrument_exchange_key",
    "0003_backtest_run_metadata",
    "0004_product_news_themes",
    "0005_news_temporal_contract",
    "0006_news_json_defaults",
    "0007_turnover_availability",
    "0008_portfolio_share_integer",
    "0009_strategy_formula_version",
    "0010_technical_indicators",
    "0011_schedule_runs",
    "0012_news_llm",
    "0013_candidates",
    "0014_theme_suggestions",
    "0015_candidate_llm_notes",
    "0016_group_score_archive",
    "0017_tracking_plans",
    "0018_market_summaries",
)
# The instrument identity gates match 0002 onward and never 0001.
INSTRUMENT_IDENTITY_REVISIONS = REVISIONS[1:]
