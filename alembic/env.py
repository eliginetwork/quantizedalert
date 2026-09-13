import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = None


def get_database_url() -> str:
    """Resolve database URL dynamically from env, platform config, or alembic.ini."""
    env_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("QUANTIZEDALERT_DATABASE_URL")
        or os.environ.get("UNLOCKAID_DATABASE_URL")
    )
    if env_url:
        return env_url

    db_path_env = os.environ.get("QUANTIZEDALERT_DB_PATH") or os.environ.get("UNLOCKAID_DB_PATH")
    if db_path_env:
        return f"sqlite:///{Path(db_path_env).resolve()}"

    try:
        from quantizedalert.config import PlatformConfig
        pcfg = PlatformConfig.load()
        if pcfg.db_path:
            return f"sqlite:///{Path(pcfg.db_path).resolve()}"
    except Exception:
        pass

    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
