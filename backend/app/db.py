from __future__ import annotations

from typing import Callable

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_PATH
from .migration_revisions import REVISIONS


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def enable_sqlite_foreign_keys(target_engine: Engine) -> None:
    """Enable SQLite referential integrity on every new connection."""

    @event.listens_for(target_engine, "connect", insert=True)
    def _set_foreign_keys(dbapi_connection, _connection_record) -> None:
        if target_engine.url.get_backend_name() != "sqlite":
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


# The scheduled daily and news jobs write the same database file; a writer
# waits for the other's lock instead of failing with "database is locked".
SQLITE_BUSY_TIMEOUT_MS = 30000


def enable_sqlite_concurrent_writes(target_engine: Engine) -> None:
    """Use WAL and a busy timeout on every new SQLite file connection."""

    @event.listens_for(target_engine, "connect")
    def _set_concurrency(dbapi_connection, _connection_record) -> None:
        if target_engine.url.get_backend_name() != "sqlite":
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            # In-memory databases report "memory" and keep working unchanged.
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


enable_sqlite_foreign_keys(engine)
enable_sqlite_concurrent_writes(engine)


def init_db() -> None:
    # Alembic is the source of truth.  The compatibility fallback in
    # app.migrations is used only when the bundled runtime has not installed
    # Alembic from requirements.txt yet.
    from .migrations import upgrade_database

    upgrade_database(engine)


def schema_revisions(
    session_factory: Callable[[], Session] | None = None,
) -> list[str] | None:
    """The database's Alembic revisions; None before any migration ran."""

    with (session_factory or SessionLocal)() as db:
        if not inspect(db.get_bind()).has_table("alembic_version"):
            return None
        return list(
            db.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )


def schema_is_current(revisions: list[str] | None) -> bool:
    """Whether ``schema_revisions()`` says the database is at the code head."""

    return revisions == [REVISIONS[-1]]


def ensure_schema(
    *,
    session_factory: Callable[[], Session] | None = None,
    migrate: Callable[[], None] | None = None,
) -> str:
    """Migrate only when the database is not already at the code head.

    ``init_db`` always runs the whole-database migration integrity check
    (``PRAGMA integrity_check`` twice, alembic/env.py), which takes minutes on
    a multi-year market database and grows with it even when no revision is
    pending (#150 for the daily, #722 for each backfill month), so a database
    at the head skips it.  Any other state runs ``migrate`` (``init_db``) with
    its checks.  Callers pass their own factory and migrate function so the
    ones they look up at call time (``worker.pipeline``'s) are used.
    """

    if schema_is_current(schema_revisions(session_factory)):
        return "current"
    (migrate or init_db)()
    return "upgraded"


def get_session() -> Session:
    return SessionLocal()
