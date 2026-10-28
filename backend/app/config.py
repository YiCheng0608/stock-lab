from __future__ import annotations

import os
import re
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
# The tracking cost and slippage assumptions are in app.tracking.
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Extra Host / Origin values admitted by app.browser_gate (Issue 343), read when app.main is imported, not here, so a bad value
# stops the API and not the worker. Comma-separated; unset or blank keeps the defaults. Only the two loopback names are
# accepted, each with an explicit port: no wildcard, scheme other than http, path, query, userinfo or empty item.
PUBLIC_HOSTS_ENV = "STOCK_API_PUBLIC_HOSTS"
ALLOWED_ORIGINS_ENV = "STOCK_API_ALLOWED_ORIGINS"
LOCAL_HOST = re.compile(r"(?:127\.0\.0\.1|localhost):([1-9][0-9]{0,4})")


def _local_hosts(name, environ, prefix=""):
    raw = environ.get(name, "")
    if not raw.strip():
        return []
    values = []
    for item in raw.split(","):
        item = item.strip()
        match = (
            LOCAL_HOST.fullmatch(item[len(prefix) :])
            if item.startswith(prefix)
            else None
        )
        if match is None or int(match.group(1)) > 65535:
            raise ValueError(
                "%s: %r is not %slocalhost:<port> or %s127.0.0.1:<port> (port 1-65535, comma-separated, no wildcard, "
                "path or userinfo)" % (name, item, prefix, prefix)
            )
        if item not in values:
            values.append(item)
    return values


def public_hosts(environ=os.environ):
    """Host values admitted besides ``<loopback name>:<listening port>``, e.g. the port a proxy or a mapped port shows."""
    return tuple(_local_hosts(PUBLIC_HOSTS_ENV, environ))


def allowed_origins(environ=os.environ):
    """CORS and gate allow list: ``DEFAULT_CORS_ORIGINS`` itself when nothing is set, else it followed by the set origins."""
    extra = [
        o
        for o in _local_hosts(ALLOWED_ORIGINS_ENV, environ, "http://")
        if o not in DEFAULT_CORS_ORIGINS
    ]
    return DEFAULT_CORS_ORIGINS + extra if extra else DEFAULT_CORS_ORIGINS
