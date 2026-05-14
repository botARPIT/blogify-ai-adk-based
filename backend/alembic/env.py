"""Alembic env configuration."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

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
    """Run migrations in online mode using sync psycopg2 engine."""
    url = get_url()
    sync_url = url.replace("+asyncpg", "")

    engine = create_engine(sync_url, poolclass=None)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
