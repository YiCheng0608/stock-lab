"""Two writers on one SQLite file wait for each other instead of failing."""

import threading
import time

from sqlalchemy import create_engine, text

from app.db import SQLITE_BUSY_TIMEOUT_MS, enable_sqlite_concurrent_writes, enable_sqlite_foreign_keys


def _engine(path):
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    enable_sqlite_foreign_keys(engine)
    enable_sqlite_concurrent_writes(engine)
    return engine


def test_connections_use_wal_and_busy_timeout(tmp_path):
    engine = _engine(tmp_path / "pragma.db")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == SQLITE_BUSY_TIMEOUT_MS
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        engine.dispose()


def test_interleaved_writers_do_not_raise_database_is_locked(tmp_path):
    path = tmp_path / "writers.db"
    first, second = _engine(path), _engine(path)
    try:
        with first.begin() as connection:
            connection.execute(text("CREATE TABLE runs (id INTEGER PRIMARY KEY, job TEXT NOT NULL)"))
        holding = threading.Event()
        errors = []

        def hold_write_lock():
            try:
                with first.connect() as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    connection.exec_driver_sql("INSERT INTO runs (job) VALUES ('daily')")
                    holding.set()
                    # Past sqlite3's own 5 s default wait, so only busy_timeout keeps it alive.
                    time.sleep(6.0)
                    connection.exec_driver_sql("COMMIT")
            except Exception as exc:  # surfaced through the assertion below
                errors.append(exc)

        thread = threading.Thread(target=hold_write_lock)
        thread.start()
        assert holding.wait(5)
        started = time.monotonic()
        with second.begin() as connection:
            connection.execute(text("INSERT INTO runs (job) VALUES ('news')"))
        waited = time.monotonic() - started
        thread.join(20)
        assert errors == []
        assert waited >= 5.5  # the second writer really waited for the first
        with second.connect() as connection:
            assert sorted(connection.execute(text("SELECT job FROM runs")).scalars()) == ["daily", "news"]
    finally:
        first.dispose()
        second.dispose()
