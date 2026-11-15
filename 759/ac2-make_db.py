"""AC-2 (#759): a fixture DB with T's list of 20 candidates, every one with overnight
news, and the pre-open check stored; argv[2] == "pending" stores no check."""

import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/backend")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, enable_sqlite_foreign_keys  # noqa: E402
from app.preopen_news import check_rows, replace_check  # noqa: E402
from test_notify import _us_bars  # noqa: E402
from test_preopen import CHECKED, _news, _taipei  # noqa: E402
from test_preopen import _list as preopen_list  # noqa: E402
from worker import pipeline  # noqa: E402

path, case = sys.argv[1], sys.argv[2]
engine = create_engine(f"sqlite:///{path}")
enable_sqlite_foreign_keys(engine)
Base.metadata.create_all(engine)
with Session(engine, autoflush=False, expire_on_commit=False) as db:
    db.info["strategies"] = pipeline._ensure_strategies(db)
    db.commit()
    symbols = [f"{1101 + i}" for i in range(20)]
    run, _ = preopen_list(db, symbols)
    late = _taipei(2026, 9, 4, 23, 0)
    for i, symbol in enumerate(symbols):
        for n in range(1 + i % 4):
            direction = "negative" if n < i % 3 else "positive"
            _news(
                db,
                [symbol],
                published=late + timedelta(minutes=n),
                collected=late,
                direction=direction,
            )
    db.commit()
    _us_bars(db)
    db.commit()
    if case == "checked":
        replace_check(db, run, check_rows(db, run, CHECKED))
        db.commit()
print("ok", path, case)
