"""Child-process probes; run with the backend importable and STOCK_* already set.

Executed only by ``product.ProductRunner`` as ``python -P _child.py <action>``.
Each action prints one JSON object as the last stdout line (Alembic logs go to
stderr).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _config() -> dict:
    from app import config

    return {
        "STOCK_DATA_DIR": str(config.DATA_DIR),
        "STOCK_DB_PATH": str(config.DB_PATH),
        "STOCK_RAW_DIR": str(config.RAW_DIR),
    }


def action_config(_args) -> dict:
    return {"config": _config()}


def action_check(args) -> dict:
    """Product schema consistency of ``--db``: the product's own readiness check plus its head revision."""

    from app import config
    from app.database_readiness import REVISIONS, DatabaseReadinessError, check_database_readiness

    result = {"config": _config(), "revisions_head": REVISIONS[-1], "alembic_head": None, "readiness": "ok"}
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        alembic_config = Config(str(config.ALEMBIC_CONFIG_PATH))
        alembic_config.set_main_option("script_location", str(Path(config.ALEMBIC_CONFIG_PATH).parent / "alembic"))
        heads = ScriptDirectory.from_config(alembic_config).get_heads()
        result["alembic_head"] = heads[0] if len(heads) == 1 else None
    except ImportError:
        pass
    try:
        check_database_readiness(Path(args.db))
    except DatabaseReadinessError as exc:
        result["readiness"] = str(exc).split(". Verify STOCK_DATA_DIR")[0]
    return result


def action_insert_instrument(args) -> dict:
    """Write one instrument through the product's own engine (bound to STOCK_DB_PATH at import)."""

    from app.db import SessionLocal
    from app.models import Instrument

    with SessionLocal() as session:
        row = Instrument(market="TW", exchange="TWSE", symbol=args.symbol, name=args.name)
        session.add(row)
        session.commit()
        return {"config": _config(), "instrument_id": row.id, "symbol": args.symbol}


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("config")
    check = commands.add_parser("check")
    check.add_argument("--db", required=True)
    insert = commands.add_parser("insert-instrument")
    insert.add_argument("--symbol", required=True)
    insert.add_argument("--name", default="probe instrument")
    args = parser.parse_args()
    actions = {"config": action_config, "check": action_check, "insert-instrument": action_insert_instrument}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(actions[args.action](args), ensure_ascii=False))


if __name__ == "__main__":
    main()
