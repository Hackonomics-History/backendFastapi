from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic's autogenerate can detect schema changes.
from app.db import Base  # noqa: E402
import app.news.models  # noqa: F401, E402
import app.user_calendar.models  # noqa: F401, E402

target_metadata = Base.metadata


def _get_url() -> str:
    from app.config import settings
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Exclude the account table — owned and migrated by Kotlin/Flyway.
        include_object=_exclude_kotlin_tables,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_exclude_kotlin_tables,
        )
        with context.begin_transaction():
            context.run_migrations()


def _exclude_kotlin_tables(_obj, name, type_, _reflected, _compare_to):
    """Keep Kotlin-owned tables out of FastAPI migrations."""
    if type_ == "table" and name in {"account", "outbox_event"}:
        return False
    return True


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
