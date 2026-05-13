"""Alembic env configuration.

Updated (Phase 1) to wire the ORM Base.metadata so that autogenerate works.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from alembic import context

from src.models.orm_models import Base  # noqa: E402

config = context.config

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(BASE_DIR / f".env.{os.getenv('ENVIRONMENT', 'dev')}", override=False)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Prefer DATABASE_URL env var so we don't have to keep alembic.ini in sync."""
    return os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))


def run_migrations_offline() -> None:
    """Run migrations in offline mode (no live DB connection)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode using sync psycopg2 engine for alembic compatibility."""
    import psycopg2
    from urllib.parse import urlparse

    url = get_url()
    sync_url = url.replace("+asyncpg", "")

    parsed = urlparse(sync_url)
    pg_conn = psycopg2.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "blogify",
        password=parsed.password or "",
        database=parsed.path.lstrip("/") or "blogify",
    )
    pg_conn.autocommit = True
    cursor = pg_conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num character varying(32) NOT NULL)"
    )
    cursor.close()
    pg_conn.close()

    engine = create_engine(sync_url, poolclass=None)

    with engine.connect() as connection:
        raw_conn = connection.connection
        db_conn = raw_conn.connection if hasattr(raw_conn, "connection") else raw_conn

        db_conn.set_session(autocommit=True)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transactional_ddl=False,
        )

        context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
