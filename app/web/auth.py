from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Flashcard, MemoryItem, Session as ChatSession, Topic, User
from app.db.repositories import UserRepo
from app.db.session import get_db
from app.quotas import QuotaGuard
from app.web.security import InMemoryRateLimiter, RedisBackedRateLimiter, validate_session_token

SESSION_COOKIE = "vetstudy_session"
_fallback_rate_limiter = InMemoryRateLimiter()
_rate_limiter = RedisBackedRateLimiter(redis_url=get_settings().redis_url, fallback=_fallback_rate_limiter)


def check_token(request: Request, authorization: str | None = Header(default=None)) -> str:
    settings = get_settings()
    bearer_token = ""
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization.replace("Bearer ", "", 1).strip()
    if bearer_token and bearer_token == settings.web_owner_token:
        return bearer_token
    cookie_token = request.cookies.get(SESSION_COOKIE)
    token = bearer_token or cookie_token
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    try:
        validate_session_token(token, secret=settings.web_session_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc
    return token


def owner_telegram_id_or_401(settings) -> int:
    owner_tg_id = int(settings.web_owner_telegram_id or 0)
    if owner_tg_id <= 0:
        raise HTTPException(status_code=401, detail="WEB_OWNER_TELEGRAM_ID is required for owner auth")
    return owner_tg_id


def get_current_user(
    request: Request,
    x_user_telegram_id: int | None = Header(default=None, alias="X-User-Telegram-Id"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = check_token(request, authorization)
    settings = get_settings()
    if x_user_telegram_id is not None and x_user_telegram_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid Telegram user id")
    token_tg_user: int | None = None
    token_role: str | None = None
    is_static_owner_token = token == settings.web_owner_token
    if not is_static_owner_token:
        token_tg_user, token_role, _ = validate_session_token(token, secret=settings.web_session_secret)
        if x_user_telegram_id is not None and x_user_telegram_id != token_tg_user:
            raise HTTPException(status_code=403, detail="Session token user mismatch")
    owner_fallback = is_static_owner_token and x_user_telegram_id is None
    if owner_fallback:
        telegram_user_id = owner_telegram_id_or_401(settings)
    else:
        telegram_user_id = x_user_telegram_id if is_static_owner_token and x_user_telegram_id is not None else token_tg_user
    if not telegram_user_id:
        raise HTTPException(status_code=401, detail="Unable to resolve authenticated user")
    role = token_role or ("owner" if owner_fallback else "user")
    user = UserRepo(db).get_or_create(
        telegram_user_id=telegram_user_id,
        display_name=f"user-{telegram_user_id}",
        role=role,
    )
    if owner_fallback and user.role != "owner":
        user.role = "owner"
        db.commit()
        db.refresh(user)
    return user


def require_admin(user: User):
    if user.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Admin role required")


def require_owner(user: User):
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")


def assert_quotas(db: Session, user: User):
    decision = QuotaGuard(get_settings()).check_user_and_global(db, user)
    if not decision.allowed:
        raise HTTPException(status_code=429, detail=decision.message or "Quota exceeded")


def accessible_topics_query(user: User):
    session_topics = select(ChatSession.topic_id).where(ChatSession.user_id == user.id, ChatSession.topic_id.is_not(None))
    memory_topics = select(MemoryItem.topic_id).where(MemoryItem.user_id == user.id, MemoryItem.topic_id.is_not(None))
    flashcard_topics = select(Flashcard.topic_id).where(Flashcard.user_id == user.id, Flashcard.topic_id.is_not(None))
    predicates = [
        Topic.user_id == user.id,
        Topic.id.in_(session_topics),
        Topic.id.in_(memory_topics),
        Topic.id.in_(flashcard_topics),
    ]
    if user.role in {"owner", "admin"}:
        predicates.append(Topic.user_id.is_(None))
    return (
        select(Topic)
        .where(or_(*predicates))
        .order_by(Topic.created_at.asc())
    )


def allow_admin_rate_limit(user: User) -> bool:
    settings = get_settings()
    return _rate_limiter.allow(
        key=f"web-admin:{user.telegram_user_id}",
        limit=settings.web_admin_rate_limit_count,
        window_seconds=settings.web_admin_rate_limit_window_seconds,
    )
