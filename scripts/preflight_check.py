from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.services import build_llm_router


def _ok(label: str) -> tuple[str, str]:
    return "ok", label


def _fail(label: str) -> tuple[str, str]:
    return "fail", label


def _warn(label: str) -> tuple[str, str]:
    return "warn", label


def check_env() -> list[tuple[str, str]]:
    settings = get_settings()
    rows: list[tuple[str, str]] = []
    rows.append(_ok("APP_ENV=prod") if settings.app_env == "prod" else _warn(f"APP_ENV={settings.app_env}"))
    rows.append(_ok("DEBUG=false") if settings.debug is False else _fail("DEBUG must be false for beta/prod"))
    rows.append(_ok("TELEGRAM_BOT_TOKEN is set") if bool(settings.telegram_bot_token) else _fail("TELEGRAM_BOT_TOKEN is missing"))
    rows.append(_ok("DATABASE_URL is set") if bool(settings.database_url) else _fail("DATABASE_URL is missing"))
    rows.append(_ok("USER_ID_HASH_SALT is set") if bool(settings.user_id_hash_salt) else _fail("USER_ID_HASH_SALT is missing"))
    rows.append(_ok("ALLOWED_TELEGRAM_USER_IDS has entries") if settings.allowed_user_ids else _fail("ALLOWED_TELEGRAM_USER_IDS is empty"))
    rows.append(_ok("WEB_OWNER_TELEGRAM_ID is set") if settings.web_owner_telegram_id else _warn("WEB_OWNER_TELEGRAM_ID not set; web falls back to first allowlist id"))
    rows.append(_ok("WEB_OWNER_PASSWORD is non-default") if settings.web_owner_password not in {"", "vetstudy-owner", "change-me"} else _fail("WEB_OWNER_PASSWORD is default/missing"))
    rows.append(_ok("WEB_OWNER_TOKEN is non-default") if settings.web_owner_token not in {"", "vetstudy-local-token", "change-me-long-random-token"} else _fail("WEB_OWNER_TOKEN is default/missing"))

    provider_keys = {
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
        "groq": settings.groq_api_key,
        "gemini": settings.gemini_api_key,
        "mock": "mock",
    }
    primary_key = provider_keys.get(settings.llm_primary_provider, "")
    fallback_key = provider_keys.get(settings.llm_fallback_provider, "")
    rows.append(_ok(f"primary provider configured: {settings.llm_primary_provider}") if primary_key else _fail(f"missing key for primary provider: {settings.llm_primary_provider}"))
    rows.append(_ok(f"fallback provider configured: {settings.llm_fallback_provider}") if fallback_key else _warn(f"missing key for fallback provider: {settings.llm_fallback_provider}"))
    if settings.llm_primary_provider == "mock":
        rows.append(_fail("LLM_PRIMARY_PROVIDER=mock is not suitable for content beta"))
    return rows


def _database_url_candidates() -> list[str]:
    settings = get_settings()
    urls = [settings.database_url]
    if "@db:" in settings.database_url:
        urls.append(settings.database_url.replace("@db:", "@localhost:", 1))
    return urls


def _connect_database():
    last_exc: SQLAlchemyError | None = None
    for url in _database_url_candidates():
        try:
            engine = create_engine(url, pool_pre_ping=True)
            conn = engine.connect()
            conn.execute(text("SELECT 1"))
            return engine, conn
        except SQLAlchemyError as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("DATABASE_URL is empty")


def check_db() -> tuple[str, str]:
    try:
        engine, conn = _connect_database()
    except SQLAlchemyError as exc:
        return _fail(f"database connection failed: {exc.__class__.__name__}")
    except RuntimeError as exc:
        return _fail(str(exc))
    try:
        url_note = " via localhost compose port" if "@localhost:" in str(engine.url) else ""
        return _ok(f"database connection works{url_note}")
    finally:
        conn.close()
        engine.dispose()


def check_schema() -> list[tuple[str, str]]:
    from app.db.models import Base

    try:
        engine, conn = _connect_database()
    except SQLAlchemyError as exc:
        return [_fail(f"schema check failed: database connection failed ({exc.__class__.__name__})")]
    except RuntimeError as exc:
        return [_fail(f"schema check failed: {exc}")]

    rows: list[tuple[str, str]] = []
    try:
        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        missing_tables = sorted(table.name for table in Base.metadata.sorted_tables if table.name not in table_names)
        if missing_tables:
            rows.append(_fail(f"missing tables: {', '.join(missing_tables)}"))

        missing_columns: list[str] = []
        for table in Base.metadata.sorted_tables:
            if table.name not in table_names:
                continue
            actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in actual_columns:
                    missing_columns.append(f"{table.name}.{column.name}")
        if missing_columns:
            rows.append(_fail(f"missing columns: {', '.join(sorted(missing_columns))}"))

        if not missing_tables and not missing_columns:
            rows.append(_ok("database schema matches application models"))
        return rows
    finally:
        conn.close()
        engine.dispose()


async def check_provider() -> tuple[str, str]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        router = build_llm_router()
        text_out = await router.generate(db, None, "Ответь одним словом: ok", purpose="answer")
        if text_out.strip():
            return _ok("primary/fallback provider generated a response")
        return _warn("provider returned an empty response")
    except Exception as exc:
        return _fail(f"provider smoke failed: {exc.__class__.__name__}")
    finally:
        db.close()


def print_rows(rows: list[tuple[str, str]]) -> int:
    failed = False
    for status, label in rows:
        print(f"[{status}] {label}")
        if status == "fail":
            failed = True
    return 1 if failed else 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="VetStudy AI beta preflight checks")
    parser.add_argument("--db", action="store_true", help="also check DATABASE_URL connectivity")
    parser.add_argument("--schema", action="store_true", help="also check required application tables and columns")
    parser.add_argument("--provider", action="store_true", help="also perform one real LLM generation")
    args = parser.parse_args()

    rows = check_env()
    if args.db:
        rows.append(check_db())
    if args.schema:
        rows.extend(check_schema())
    if args.provider:
        rows.append(await check_provider())
    return print_rows(rows)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
