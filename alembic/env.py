from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db.models import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def _migration_urls() -> list[str]:
    urls = [settings.database_url]
    if "@db:" in settings.database_url:
        urls.append(settings.database_url.replace("@db:", "@localhost:", 1))
    return urls


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    last_exc: OperationalError | None = None
    for url in _migration_urls():
        section = config.get_section(config.config_ini_section) or {}
        section["sqlalchemy.url"] = url
        connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
        try:
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
            return
        except OperationalError as exc:
            last_exc = exc
            if "@localhost:" not in url:
                continue
            raise
    if last_exc:
        raise last_exc


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
