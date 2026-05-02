from contextlib import asynccontextmanager

from fastapi import HTTPException
from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.models import Subject
from app.db.session import new_session
from app.errors import UserVisibleError
from app.media.jobs import start_worker, stop_worker
from app.observability import RequestContextMiddleware, configure_logging, safe_user_id
from app.telegram.bot import dp, get_bot
from app.web import router as web_router
import logging

settings = get_settings()
configure_logging()


def seed_subjects():
    db = new_session()
    try:
        subjects = [
            ("pharmacology", "Фармакология"),
            ("surgery", "Хирургия"),
            ("internal_medicine", "ВНБ"),
            ("anatomy", "Анатомия"),
            ("general", "Общее"),
        ]
        for slug, title in subjects:
            exists = db.query(Subject).filter(Subject.slug == slug).first()
            if not exists:
                db.add(Subject(slug=slug, title=title, system_prompt=title))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_subjects()
    if settings.redis_url:
        start_worker()
    if settings.telegram_mode == "webhook" and settings.webhook_url:
        bot = get_bot()
        await bot.set_webhook(f"{settings.webhook_url.rstrip('/')}{settings.webhook_path}")
    yield
    if settings.telegram_mode == "webhook":
        bot = get_bot()
        await bot.delete_webhook(drop_pending_updates=False)
    await stop_worker()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Telegram-Id"],
)
app.add_middleware(RequestContextMiddleware)
app.include_router(web_router)
logger = logging.getLogger("app.main")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    status = {"database": False, "redis": None}
    db = new_session()
    try:
        db.execute(text("SELECT 1"))
        status["database"] = True
    except SQLAlchemyError:
        status["database"] = False
    finally:
        db.close()
    if settings.redis_url:
        redis = redis_from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        try:
            pong = await redis.ping()
            status["redis"] = bool(pong)
        except Exception:
            status["redis"] = False
        finally:
            await redis.aclose()
    ok = status["database"] and (status["redis"] in (True, None))
    body = {"status": "ready" if ok else "not_ready", "checks": status}
    if not ok:
        raise HTTPException(status_code=503, detail=body)
    return body


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    tg_user_id = (
        data.get("message", {}).get("from", {}).get("id")
        or data.get("callback_query", {}).get("from", {}).get("id")
        or data.get("edited_message", {}).get("from", {}).get("id")
    )
    request.state.telegram_user_id = safe_user_id(tg_user_id, settings.user_id_hash_salt)
    update = Update.model_validate(data)
    bot = get_bot()
    await dp.feed_update(bot=bot, update=update)
    return JSONResponse({"ok": True})


@app.exception_handler(UserVisibleError)
async def handle_user_visible_error(_: Request, exc: UserVisibleError):
    logger.warning(
        "user_visible_error",
        extra={"event": "user_visible_error", "error_category": exc.category},
    )
    return JSONResponse(status_code=400, content={"error": exc.message, "category": exc.category})


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    logger.exception(
        "unexpected_error",
        extra={"event": "unexpected_error", "error_category": "unexpected_error"},
    )
    return JSONResponse(status_code=500, content={"error": "Внутренняя ошибка сервиса. Попробуйте позже.", "category": "unexpected_error"})
