from __future__ import annotations

from logging.config import fileConfig

import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from alembic import context
import sqlalchemy as sa
from sqlalchemy import pool

from app.core.config import get_settings
from app.core.database import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

settings = get_settings()


def _to_sync_database_url(url: str) -> str:
    # Convierte URLs async (asyncpg) a sync (psycopg) para Alembic.
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+asyncpg:"):
        return url.replace("postgresql+asyncpg:", "postgresql+psycopg:", 1)
    # Si ya es sync, lo dejamos tal cual.
    return url


target_metadata = Base.metadata

# Asegura que los modelos se registren en metadata (si no se importan, autogenerate/migrations fallan).
from app.models.booking import Cita, Negocio, Paciente, Servicio  # noqa: F401,E402
from app.models.bot_state import BotEstado  # noqa: F401,E402


def run_migrations_offline() -> None:
    url = _to_sync_database_url(settings.DATABASE_URL)
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
    url = _to_sync_database_url(settings.DATABASE_URL)
    connectable = sa.create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

