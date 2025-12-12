from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool  # type: ignore[import-not-found]

from alembic import context
from reflections.core.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_url() -> str:
    return (
        "postgresql+psycopg://"
        f"{settings.REFLECTIONS_DB_USER}:{settings.REFLECTIONS_DB_PASSWORD}"
        f"@{settings.REFLECTIONS_DB_HOST}:{settings.REFLECTIONS_DB_PORT}"
        f"/{settings.REFLECTIONS_DB_NAME}"
    )


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
