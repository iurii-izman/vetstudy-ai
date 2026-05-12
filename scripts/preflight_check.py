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


def _secret_ready(value: str, *, min_len: int = 16) -> bool:
    normalized = (value or "").strip().lower()
    if len(normalized) < min_len:
        return False
    if normalized in {"change-me", "vetstudy-owner", "vetstudy-local-token"}:
        return False
    if "change-me" in normalized:
        return False
    return not any(marker in normalized for marker in ("replace-with", "example", "placeholder", "long-random"))


def check_env() -> list[tuple[str, str]]:
    settings = get_settings()
    rows: list[tuple[str, str]] = []
    rows.append(_ok("APP_ENV=prod") if settings.app_env == "prod" else _warn(f"APP_ENV={settings.app_env}"))
    rows.append(_ok("DEBUG=false") if settings.debug is False else _fail("DEBUG must be false for beta/prod"))
    rows.append(_ok("TELEGRAM_BOT_TOKEN is set") if bool(settings.telegram_bot_token) else _fail("TELEGRAM_BOT_TOKEN is missing"))
    rows.append(_ok("DATABASE_URL is set") if bool(settings.database_url) else _fail("DATABASE_URL is missing"))
    rows.append(_ok("USER_ID_HASH_SALT is non-default") if _secret_ready(settings.user_id_hash_salt) else _fail("USER_ID_HASH_SALT is missing/default"))
    allowlist_present = bool(settings.allowed_user_ids or settings.allowed_usernames)
    rows.append(_ok("Telegram allowlist has entries") if allowlist_present else _fail("Telegram allowlist is empty"))
    rows.append(_ok("WEB_OWNER_TELEGRAM_ID is set") if settings.web_owner_telegram_id else _warn("WEB_OWNER_TELEGRAM_ID not set; web falls back to first allowlist id"))
    password_ready = bool(settings.web_owner_password_hash) or _secret_ready(settings.web_owner_password, min_len=12)
    rows.append(_ok("WEB_OWNER_PASSWORD_HASH/password is configured") if password_ready else _fail("WEB_OWNER_PASSWORD_HASH/password is default/missing"))
    rows.append(_warn("WEB_OWNER_PASSWORD_HASH is preferred over plain password") if not settings.web_owner_password_hash else _ok("WEB_OWNER_PASSWORD_HASH is set"))
    rows.append(_ok("WEB_OWNER_TOKEN is non-default") if _secret_ready(settings.web_owner_token) else _fail("WEB_OWNER_TOKEN is default/missing"))
    rows.append(_ok("WEB_SESSION_SECRET is non-default") if _secret_ready(settings.web_session_secret) else _fail("WEB_SESSION_SECRET is default/missing"))

    provider_keys = {
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
        "groq": settings.groq_api_key,
        "gemini": settings.gemini_api_key,
        "mock": "mock",
    }
    known_providers = {"openai", "openrouter", "groq", "gemini", "mock"}
    primary_provider = settings.llm_primary_provider.strip().lower()
    fallback_provider = settings.llm_fallback_provider.strip().lower()
    embeddings_provider = settings.llm_embeddings_provider.strip().lower()
    primary_key = provider_keys.get(primary_provider, "")
    fallback_key = provider_keys.get(fallback_provider, "")
    embeddings_key = provider_keys.get(embeddings_provider, "")

    if primary_provider not in known_providers:
        rows.append(_fail(f"unknown primary provider: {settings.llm_primary_provider} (allowed: {', '.join(sorted(known_providers))})"))
    else:
        rows.append(
            _ok(f"primary provider configured: {primary_provider}")
            if primary_key
            else _fail(f"missing key for primary provider: {primary_provider}")
        )
    if fallback_provider not in known_providers:
        rows.append(_fail(f"unknown fallback provider: {settings.llm_fallback_provider} (allowed: {', '.join(sorted(known_providers))})"))
    else:
        rows.append(
            _ok(f"fallback provider configured: {fallback_provider}")
            if fallback_key
            else _warn(f"missing key for fallback provider: {fallback_provider}")
        )

    if primary_provider == "mock":
        rows.append(_fail("LLM_PRIMARY_PROVIDER=mock is not suitable for content beta"))

    if embeddings_provider not in known_providers:
        rows.append(_fail(f"unknown embeddings provider: {settings.llm_embeddings_provider} (allowed: {', '.join(sorted(known_providers))})"))
    elif settings.app_env == "prod":
        if embeddings_provider == "mock":
            rows.append(_fail("APP_ENV=prod requires LLM_EMBEDDINGS_PROVIDER to be non-mock (openai|openrouter|groq|gemini)"))
        elif not settings.llm_embeddings_model.strip():
            rows.append(_fail("APP_ENV=prod requires LLM_EMBEDDINGS_MODEL to be set for the selected embeddings provider"))
        elif not embeddings_key:
            rows.append(_fail(f"APP_ENV=prod missing API key for embeddings provider: {embeddings_provider}"))
        else:
            rows.append(_ok(f"embeddings provider configured for prod: {embeddings_provider}/{settings.llm_embeddings_model}"))
    else:
        if embeddings_provider == "mock":
            rows.append(_warn("embeddings provider is mock (allowed outside APP_ENV=prod)"))
        elif not embeddings_key:
            rows.append(_warn(f"missing key for embeddings provider: {embeddings_provider}"))
        else:
            rows.append(_ok(f"embeddings provider configured: {embeddings_provider}"))
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
