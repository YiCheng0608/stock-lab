from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_PATH


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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


def get_session() -> Session:
    return SessionLocal()
