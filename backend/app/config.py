from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("STOCK_DATA_DIR", str(PROJECT_ROOT / "data")))
DB_PATH = Path(os.getenv("STOCK_DB_PATH", str(DATA_DIR / "stock.db")))
RAW_DIR = Path(os.getenv("STOCK_RAW_DIR", str(DATA_DIR / "raw")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

API_PREFIX = "/api"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "backend" / "alembic.ini"
OFFICIAL_MAX_BACKFILL_DAYS = 93
MIN_GROUP_MEMBERS = 3
MAX_GROUP_CANDIDATES = 4
MIN_GROUP_CANDIDATES = 2
# These are explicit modelling assumptions, not market observations.  They
# are persisted in signal evidence so a backtest/review can distinguish a
# net-of-cost result from a raw price return.
EXECUTION_SLIPPAGE_BPS = 5.0
ROUND_TRIP_TRANSACTION_COST_BPS = 30.0
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
