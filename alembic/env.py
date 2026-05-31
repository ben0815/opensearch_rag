import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Importiert alle Modelle, damit Alembic das vollständige Ziel-Schema kennt
# (wird für --autogenerate benötigt).
from app.db.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Liest die Datenbank-URL aus der Umgebungsvariable DATABASE_URL.
    Bricht beim Start ab wenn DATABASE_URL fehlt, statt den Platzhalter aus alembic.ini zu nutzen."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Umgebungsvariable DATABASE_URL ist nicht gesetzt. "
            "Beispiel: DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ragdb"
        )
    return url


def run_migrations_offline() -> None:
    """Offline-Modus: generiert SQL-Statements ohne Live-Verbindung.
    Nützlich für Code-Review oder manuelle Ausführung: alembic upgrade --sql head
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online-Modus: verbindet sich mit der Datenbank und führt ausstehende Migrations aus."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
