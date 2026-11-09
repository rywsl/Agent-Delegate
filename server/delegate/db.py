from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return _session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _upgrade_existing_tables() -> None:
    additions = {
        "users": {"sandbox_free_seconds": "INTEGER"},
        "tasks": {
            "billing_mode": "VARCHAR(16) DEFAULT 'platform'",
            "sandbox_started_at": "TIMESTAMP",
            "sandbox_billed_seconds": "INTEGER DEFAULT 0",
            "sandbox_billed_quota": "INTEGER DEFAULT 0",
            "sandbox_free_seconds_used": "INTEGER DEFAULT 0",
        },
    }
    engine = get_engine()
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())
    _upgrade_existing_tables()
