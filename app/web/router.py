from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy import String as SQLString
from sqlalchemy import cast
from sqlalchemy.orm import Session

from app.config import get_settings
from app.analytics import ProductAnalyticsService
from app.db.models import Document, DocumentChunk, FeedbackEvent, Flashcard, MemoryItem, Message, ModelCall, Session as ChatSession, Subject, Topic, User
from app.db.repositories import ErrorEventRepo, FeedbackEventRepo, ModelCallRepo, ReviewEventRepo, UserRepo
from app.learning.service import LearningService
from app.db.session import get_db
from app.quotas import QuotaGuard
from app.web.document_cleanup import cleanup_document_files, document_storage_paths
from app.web.schemas import (
    FlashcardReviewRequest,
    LoginRequest,
    OnboardingRequest,
    SearchResponse,
    UpdateNoteRequest,
    UserProfileUpdateRequest,
    WebSettingsUpdateRequest,
)
from app.web.security import InMemoryRateLimiter, RedisBackedRateLimiter, issue_session_token, validate_session_token, verify_password

router = APIRouter(prefix="/api/web", tags=["web"])
_fallback_rate_limiter = InMemoryRateLimiter()
_rate_limiter = RedisBackedRateLimiter(redis_url=get_settings().redis_url, fallback=_fallback_rate_limiter)
SESSION_COOKIE = "vetstudy_session"


def _check_token(request: Request, authorization: str | None = Header(default=None)) -> str:
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


def _fallback_owner_telegram_id(settings) -> int:
    return int(settings.web_owner_telegram_id or 0)


def _owner_telegram_id_or_401(settings) -> int:
    owner_tg_id = _fallback_owner_telegram_id(settings)
    if owner_tg_id <= 0:
        raise HTTPException(status_code=401, detail="WEB_OWNER_TELEGRAM_ID is required for owner auth")
    return owner_tg_id


def _get_current_user(
    request: Request,
    x_user_telegram_id: int | None = Header(default=None, alias="X-User-Telegram-Id"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _check_token(request, authorization)
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
        telegram_user_id = _owner_telegram_id_or_401(settings)
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


def _require_admin(user: User):
    if user.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Admin role required")


def _require_owner(user: User):
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")


def _assert_quotas(db: Session, user: User):
    decision = QuotaGuard(get_settings()).check_user_and_global(db, user)
    if not decision.allowed:
        raise HTTPException(status_code=429, detail=decision.message or "Quota exceeded")


def _accessible_topics_query(user: User):
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


@router.post("/auth/login")
def web_login(payload: LoginRequest):
    settings = get_settings()
    if not _rate_limiter.allow(
        key="web-login",
        limit=settings.web_login_rate_limit_count,
        window_seconds=settings.web_login_rate_limit_window_seconds,
    ):
        raise HTTPException(status_code=429, detail="Login rate limit exceeded")
    valid = False
    if settings.web_owner_password_hash:
        valid = verify_password(payload.password, settings.web_owner_password_hash)
    if not valid:
        valid = payload.password == settings.web_owner_password
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid password")
    session = issue_session_token(
        secret=settings.web_session_secret,
        telegram_user_id=_owner_telegram_id_or_401(settings),
        role="owner",
        ttl_seconds=settings.web_session_ttl_seconds,
    )
    return {
        "access_token": session.token,
        "expires_at": session.expires_at.isoformat(),
        "token_type": "bearer",
        "telegram_user_id": _owner_telegram_id_or_401(settings),
    }


def _allow_admin_rate_limit(user: User) -> bool:
    settings = get_settings()
    return _rate_limiter.allow(
        key=f"web-admin:{user.telegram_user_id}",
        limit=settings.web_admin_rate_limit_count,
        window_seconds=settings.web_admin_rate_limit_window_seconds,
    )


@router.post("/auth/session")
def web_login_session(payload: LoginRequest, response: Response):
    body = web_login(payload)
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=body["access_token"],
        httponly=True,
        secure=settings.app_env == "prod",
        samesite="lax",
        max_age=settings.web_session_ttl_seconds,
    )
    return body


@router.post("/auth/refresh")
def web_refresh_session(request: Request, response: Response, authorization: str | None = Header(default=None)):
    settings = get_settings()
    token = _check_token(request, authorization)
    if token == settings.web_owner_token:
        raise HTTPException(status_code=400, detail="Static owner token is not rotatable")
    telegram_user_id, role, _ = validate_session_token(token, secret=settings.web_session_secret)
    rotated = issue_session_token(
        secret=settings.web_session_secret,
        telegram_user_id=telegram_user_id,
        role=role,
        ttl_seconds=settings.web_session_ttl_seconds,
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=rotated.token,
        httponly=True,
        secure=settings.app_env == "prod",
        samesite="lax",
        max_age=settings.web_session_ttl_seconds,
    )
    return {
        "access_token": rotated.token,
        "expires_at": rotated.expires_at.isoformat(),
        "token_type": "bearer",
        "telegram_user_id": telegram_user_id,
    }


@router.get("/me")
def me(user: User = Depends(_get_current_user)):
    profile = dict((user.settings or {}).get("profile") or {})
    return {
        "id": user.id,
        "telegram_user_id": user.telegram_user_id,
        "role": user.role,
        "language": user.language,
        "specialization": user.specialization,
        "onboarding_completed": user.onboarding_completed,
        "onboarding_subjects": user.onboarding_subjects,
        "quotas": {
            "messages_per_day": user.quota_messages_per_day,
            "cost_per_month_usd": float(user.quota_cost_per_month_usd),
            "premium_model_per_day": user.quota_premium_model_per_day,
        },
        "billing": {"plan": user.billing_plan, "customer_ref": user.billing_customer_ref},
        "profile": {
            "region": profile.get("region", "unspecified"),
            "species_focus": profile.get("species_focus", "dog_cat"),
        },
    }


@router.get("/profile")
def get_profile(user: User = Depends(_get_current_user)):
    profile = dict((user.settings or {}).get("profile") or {})
    region = str(profile.get("region", "unspecified")).lower()
    species_focus = str(profile.get("species_focus", "dog_cat")).lower()
    if region not in {"us", "eu", "local", "unspecified"}:
        region = "unspecified"
    if species_focus not in {"dog", "cat", "dog_cat"}:
        species_focus = "dog_cat"
    return {"region": region, "species_focus": species_focus}


@router.patch("/profile")
def update_profile(payload: UserProfileUpdateRequest, db: Session = Depends(get_db), user: User = Depends(_get_current_user)):
    region = payload.region.strip().lower()
    species_focus = payload.species_focus.strip().lower()
    if region not in {"us", "eu", "local", "unspecified"}:
        raise HTTPException(status_code=400, detail="Unsupported region")
    if species_focus not in {"dog", "cat", "dog_cat"}:
        raise HTTPException(status_code=400, detail="Unsupported species_focus")
    settings = dict(user.settings or {})
    settings["profile"] = {"region": region, "species_focus": species_focus}
    user.settings = settings
    db.commit()
    ProductAnalyticsService(db).track(user_id=user.id, event_name="profile_updated", properties=settings["profile"])
    return settings["profile"]


@router.post("/onboarding")
def onboarding(payload: OnboardingRequest, db: Session = Depends(get_db), user: User = Depends(_get_current_user)):
    UserRepo(db).complete_onboarding(
        user,
        language=payload.language,
        specialization=payload.specialization,
        subjects=payload.subjects,
    )
    return {"ok": True, "onboarding_completed": True}


@router.get("/subjects")
def list_subjects(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    _assert_quotas(db, user)
    rows = db.execute(select(Subject).order_by(Subject.title.asc())).scalars().all()
    return [{"id": r.id, "slug": r.slug, "title": r.title} for r in rows]


@router.get("/topics")
def list_topics(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(_accessible_topics_query(user)).scalars().all()
    return [
        {
            "id": r.id,
            "subject_id": r.subject_id,
            "parent_id": r.parent_id,
            "title": r.title,
            "summary": r.summary,
            "telegram_thread_id": r.telegram_thread_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/sessions")
def list_sessions(topic_id: UUID | None = None, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    query = select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc())
    if topic_id:
        query = query.where(ChatSession.topic_id == topic_id)
    rows = db.execute(query).scalars().all()
    return [
        {
            "id": row.id,
            "topic_id": row.topic_id,
            "title": row.title,
            "mode": row.mode,
            "summary": row.summary,
            "is_active": row.is_active,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/messages")
def list_messages(
    session_id: UUID | None = None,
    topic_id: UUID | None = None,
    limit: int = 100,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        select(Message)
        .join(ChatSession, ChatSession.id == Message.session_id)
        .where(ChatSession.user_id == user.id)
        .order_by(Message.created_at.desc())
        .limit(min(limit, 300))
    )
    if session_id:
        query = query.where(Message.session_id == session_id)
    elif topic_id:
        query = query.where(ChatSession.topic_id == topic_id)
    rows = list(db.execute(query).scalars().all())
    rows.reverse()
    return [{"id": row.id, "session_id": row.session_id, "role": row.role, "content": row.content, "created_at": row.created_at} for row in rows]


@router.get("/memory/search", response_model=list[SearchResponse])
def search_memory(
    q: str,
    topic_id: UUID | None = None,
    kind: str | None = None,
    tag: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 40,
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    query = select(MemoryItem).where(
        MemoryItem.user_id == user.id,
        or_(MemoryItem.content.ilike(f"%{q}%"), MemoryItem.title.ilike(f"%{q}%")),
    )
    if topic_id:
        query = query.where(MemoryItem.topic_id == topic_id)
    if kind:
        query = query.where(MemoryItem.kind == kind)
    if tag:
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.where(MemoryItem.tags.contains([tag]))
        else:
            query = query.where(cast(MemoryItem.tags, SQLString).ilike(f'%"{tag}"%'))
    if date_from:
        try:
            query = query.where(MemoryItem.created_at >= datetime.fromisoformat(date_from))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_from format") from exc
    if date_to:
        try:
            query = query.where(MemoryItem.created_at <= datetime.fromisoformat(date_to))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_to format") from exc
    query = query.order_by(MemoryItem.created_at.desc()).limit(min(limit, 100))
    rows = db.execute(query).scalars().all()
    return [
        SearchResponse(
            id=row.id,
            title=row.title,
            content=row.content,
            kind=row.kind,
            tags=row.tags,
            topic_id=row.topic_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/notes")
def list_notes(topic_id: UUID | None = None, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    query = select(MemoryItem).where(MemoryItem.user_id == user.id, MemoryItem.kind.in_(["note", "summary", "answer"]))
    if topic_id:
        query = query.where(MemoryItem.topic_id == topic_id)
    query = query.order_by(MemoryItem.created_at.desc())
    rows = db.execute(query).scalars().all()
    return [{"id": row.id, "topic_id": row.topic_id, "kind": row.kind, "title": row.title, "content": row.content, "tags": row.tags, "created_at": row.created_at} for row in rows]


@router.patch("/notes/{note_id}")
def update_note(note_id: UUID, payload: UpdateNoteRequest, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    row = db.execute(select(MemoryItem).where(MemoryItem.id == note_id, MemoryItem.user_id == user.id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Note not found")
    row.title = payload.title
    row.content = payload.content
    if payload.tags is not None:
        row.tags = payload.tags
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "title": row.title, "content": row.content, "tags": row.tags}


@router.get("/flashcards")
def list_flashcards(topic_id: UUID | None = None, due_only: bool = False, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    query = select(Flashcard).where(Flashcard.user_id == user.id)
    if topic_id:
        query = query.where(Flashcard.topic_id == topic_id)
    if due_only:
        query = query.where(or_(Flashcard.due_at.is_(None), Flashcard.due_at <= datetime.now(UTC)))
    query = query.order_by(Flashcard.created_at.asc())
    rows = db.execute(query).scalars().all()
    return [{"id": row.id, "topic_id": row.topic_id, "front": row.front, "back": row.back, "tags": row.tags, "due_at": row.due_at, "interval_days": row.interval_days, "ease": row.ease, "reps": row.reps, "lapses": row.lapses} for row in rows]


@router.post("/flashcards/{card_id}/review")
def review_flashcard(card_id: UUID, payload: FlashcardReviewRequest, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    card = db.execute(select(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id)).scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if payload.action not in {"again", "hard", "good", "easy"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
    updated, score = LearningService().apply_review(card=card, action=payload.action)
    db.add(updated)
    db.commit()
    db.refresh(updated)
    ReviewEventRepo(db).add(user_id=user.id, topic_id=updated.topic_id, flashcard_id=updated.id, event_type=payload.action, score=score, metadata_={})
    return {"id": updated.id, "due_at": updated.due_at, "interval_days": updated.interval_days, "ease": updated.ease}


@router.get("/stats")
def stats(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    topics_total = len(db.execute(_accessible_topics_query(user)).scalars().all())
    sessions_total = db.execute(select(func.count(ChatSession.id)).where(ChatSession.user_id == user.id)).scalar_one()
    messages_total = db.execute(select(func.count(Message.id)).join(ChatSession, ChatSession.id == Message.session_id).where(ChatSession.user_id == user.id)).scalar_one()
    notes_total = db.execute(select(func.count(MemoryItem.id)).where(MemoryItem.user_id == user.id, MemoryItem.kind.in_(["note", "summary", "answer"]))).scalar_one()
    flashcards_total = db.execute(select(func.count(Flashcard.id)).where(Flashcard.user_id == user.id)).scalar_one()
    due_flashcards = db.execute(select(func.count(Flashcard.id)).where(Flashcard.user_id == user.id, or_(Flashcard.due_at.is_(None), Flashcard.due_at <= datetime.now(UTC)))).scalar_one()
    return {"topics_total": topics_total, "sessions_total": sessions_total, "messages_total": messages_total, "notes_total": notes_total, "flashcards_total": flashcards_total, "due_flashcards": due_flashcards}


@router.get("/privacy/export")
def export_user_data(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    topics = db.execute(_accessible_topics_query(user)).scalars().all()
    sessions = db.execute(select(ChatSession).where(ChatSession.user_id == user.id)).scalars().all()
    messages = db.execute(select(Message).join(ChatSession, ChatSession.id == Message.session_id).where(ChatSession.user_id == user.id)).scalars().all()
    memory = db.execute(select(MemoryItem).where(MemoryItem.user_id == user.id)).scalars().all()
    cards = db.execute(select(Flashcard).where(Flashcard.user_id == user.id)).scalars().all()
    documents = db.execute(select(Document).where(Document.user_id == user.id)).scalars().all()
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.user_id == user.id)).scalars().all()
    return {
        "user": {"id": str(user.id), "telegram_user_id": user.telegram_user_id, "role": user.role, "language": user.language},
        "topics": [{"id": str(x.id), "title": x.title} for x in topics],
        "sessions": [{"id": str(x.id), "topic_id": str(x.topic_id) if x.topic_id else None} for x in sessions],
        "messages": [{"id": str(x.id), "session_id": str(x.session_id) if x.session_id else None, "content": x.content} for x in messages],
        "memory": [{"id": str(x.id), "kind": x.kind, "content": x.content} for x in memory],
        "documents": [{"id": str(x.id), "topic_id": str(x.topic_id) if x.topic_id else None, "filename": x.filename, "status": x.status, "job_id": x.job_id} for x in documents],
        "document_chunks": [{"id": str(x.id), "document_id": str(x.document_id), "topic_id": str(x.topic_id) if x.topic_id else None, "chunk_index": x.chunk_index, "snippet": x.snippet} for x in chunks],
        "flashcards": [{"id": str(x.id), "front": x.front, "back": x.back} for x in cards],
    }


@router.delete("/privacy/topic/{topic_id}")
def delete_topic(topic_id: UUID, user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    topic = db.execute(_accessible_topics_query(user).where(Topic.id == topic_id)).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    documents = db.execute(select(Document).where(Document.user_id == user.id, Document.topic_id == topic_id)).scalars().all()
    document_paths = document_storage_paths(documents)
    session_ids = [x.id for x in db.execute(select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.topic_id == topic_id)).scalars().all()]
    if session_ids:
        db.execute(Message.__table__.delete().where(Message.session_id.in_(session_ids)))
        db.execute(ChatSession.__table__.delete().where(ChatSession.id.in_(session_ids)))
    db.execute(MemoryItem.__table__.delete().where(MemoryItem.user_id == user.id, MemoryItem.topic_id == topic_id))
    db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.user_id == user.id, DocumentChunk.topic_id == topic_id))
    db.execute(Document.__table__.delete().where(Document.user_id == user.id, Document.topic_id == topic_id))
    db.execute(Flashcard.__table__.delete().where(Flashcard.user_id == user.id, Flashcard.topic_id == topic_id))
    if topic.user_id == user.id:
        db.delete(topic)
    db.commit()
    cleanup_document_files(document_paths)
    return {"ok": True}


@router.delete("/privacy/account")
def delete_account(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if user.role == "owner":
        raise HTTPException(status_code=400, detail="Owner account cannot be deleted via API")
    documents = db.execute(select(Document).where(Document.user_id == user.id)).scalars().all()
    document_paths = document_storage_paths(documents)
    topic_ids = [x.id for x in db.execute(select(Topic).where(Topic.user_id == user.id)).scalars().all()]
    session_ids = [x.id for x in db.execute(select(ChatSession).where(ChatSession.user_id == user.id)).scalars().all()]
    if session_ids:
        db.execute(Message.__table__.delete().where(Message.session_id.in_(session_ids)))
    db.execute(ChatSession.__table__.delete().where(ChatSession.user_id == user.id))
    db.execute(MemoryItem.__table__.delete().where(MemoryItem.user_id == user.id))
    db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.user_id == user.id))
    db.execute(Document.__table__.delete().where(Document.user_id == user.id))
    db.execute(Flashcard.__table__.delete().where(Flashcard.user_id == user.id))
    if topic_ids:
        db.execute(Topic.__table__.delete().where(Topic.id.in_(topic_ids)))
    db.execute(ModelCall.__table__.delete().where(ModelCall.user_id == user.id))
    db.delete(user)
    db.commit()
    cleanup_document_files(document_paths)
    return {"ok": True}


@router.get("/admin/users")
def admin_users(_: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = UserRepo(db).list_all()
    return [{"id": x.id, "telegram_user_id": x.telegram_user_id, "role": x.role, "language": x.language, "onboarding_completed": x.onboarding_completed} for x in rows]


@router.get("/admin/usage")
def admin_usage(_: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    calls, in_tokens, out_tokens, cost = ModelCallRepo(db).usage_all()
    return {"calls": calls, "input_tokens": int(in_tokens), "output_tokens": int(out_tokens), "cost_usd": float(cost)}


@router.get("/admin/costs")
def admin_costs(_: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = db.execute(
        select(
            ModelCall.user_id,
            ModelCall.provider,
            ModelCall.model,
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
        )
        .group_by(ModelCall.user_id, ModelCall.provider, ModelCall.model)
    ).all()
    return [{"user_id": uid, "provider": provider, "model": model, "calls": int(calls), "cost_usd": float(cost)} for uid, provider, model, calls, cost in rows]


@router.get("/admin/errors")
def admin_errors(_: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = ErrorEventRepo(db).list_recent(limit=200)
    return [{"id": x.id, "user_id": x.user_id, "scope": x.scope, "category": x.category, "details": x.details, "created_at": x.created_at} for x in rows]


@router.get("/admin/metrics/providers")
def admin_provider_metrics(_: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = db.execute(
        select(
            ModelCall.provider,
            ModelCall.model,
            func.count(ModelCall.id),
            func.coalesce(func.avg(ModelCall.latency_ms), 0),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
        ).group_by(ModelCall.provider, ModelCall.model)
    ).all()
    return [
        {
            "provider": provider,
            "model": model,
            "calls": int(calls),
            "latency_ms_avg": float(latency_avg),
            "cost_usd_total": float(cost),
        }
        for provider, model, calls, latency_avg, cost in rows
    ]


@router.get("/admin/alerts/unanswered")
def admin_unanswered_alerts(
    older_than_minutes: int = 20,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    now_ts = datetime.now(UTC)
    last_user_cte = (
        select(
            Message.session_id.label("session_id"),
            func.max(Message.created_at).label("last_user_created_at"),
        )
        .where(Message.role == "user")
        .group_by(Message.session_id)
        .cte("last_user")
    )
    last_assistant_cte = (
        select(
            Message.session_id.label("session_id"),
            func.max(Message.created_at).label("last_assistant_created_at"),
        )
        .where(Message.role == "assistant")
        .group_by(Message.session_id)
        .cte("last_assistant")
    )
    last_user_message_cte = (
        select(
            Message.session_id.label("session_id"),
            Message.id.label("message_id"),
            Message.content.label("content"),
            Message.created_at.label("created_at"),
        )
        .join(
            last_user_cte,
            (Message.session_id == last_user_cte.c.session_id)
            & (Message.created_at == last_user_cte.c.last_user_created_at),
        )
        .where(Message.role == "user")
        .cte("last_user_message")
    )

    rows = db.execute(
        select(
            ChatSession.id,
            ChatSession.user_id,
            last_user_message_cte.c.message_id,
            last_user_message_cte.c.content,
            last_user_message_cte.c.created_at,
            last_assistant_cte.c.last_assistant_created_at,
        )
        .join(last_user_message_cte, last_user_message_cte.c.session_id == ChatSession.id)
        .outerjoin(last_assistant_cte, last_assistant_cte.c.session_id == ChatSession.id)
        .where(
            or_(
                last_assistant_cte.c.last_assistant_created_at.is_(None),
                last_assistant_cte.c.last_assistant_created_at < last_user_message_cte.c.created_at,
            )
        )
    ).all()

    alerts: list[dict] = []
    for session_id, user_id, message_id, content, created_at, _ in rows:
        age_minutes = int((now_ts - created_at).total_seconds() / 60)
        if age_minutes < older_than_minutes:
            continue
        alerts.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "last_user_message_id": message_id,
                "age_minutes": age_minutes,
                "preview": (content or "")[:240],
            }
        )
    return alerts


@router.get("/admin/feedback")
def admin_feedback(status: str | None = None, _: str = Depends(_check_token), user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = FeedbackEventRepo(db).list_recent(limit=200, status=status)
    return [{"id": x.id, "user_id": x.user_id, "topic_id": x.topic_id, "message_id": x.message_id, "feedback_type": x.feedback_type, "status": x.status, "model": x.model, "details": x.details, "created_at": x.created_at} for x in rows]


@router.get("/admin/analytics/summary")
def admin_analytics_summary(
    days: int = 30,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    service = ProductAnalyticsService(db)
    return {
        "days": days,
        "activation_funnel": service.activation_funnel(days=days),
        "retention_lite": service.retention_lite(days=days),
        "dau_like": service.dau_like(days=min(max(days, 1), 60)),
        "content_gap_report": service.content_gap_report(days=days),
        "retrieval_quality": service.retrieval_quality(days=days),
        "behavior": service.behavior_summary(days=days),
    }


@router.get("/admin/analytics/retrieval-quality")
def admin_retrieval_quality(
    days: int = 30,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    return ProductAnalyticsService(db).retrieval_quality(days=days)


@router.patch("/admin/feedback/{feedback_id}")
def admin_feedback_update(
    feedback_id: UUID,
    payload: dict,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    feedback = db.execute(select(FeedbackEvent).where(FeedbackEvent.id == feedback_id)).scalar_one_or_none()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    status = str(payload.get("status", "")).strip().lower()
    if status and status not in {"new", "in_review", "resolved", "ignored"}:
        raise HTTPException(status_code=400, detail="Unsupported status")
    if status:
        feedback.status = status
    if "details" in payload:
        feedback.details = payload.get("details")
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {"id": feedback.id, "status": feedback.status, "details": feedback.details}


@router.get("/topics/graph")
def topics_graph(user: User = Depends(_get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(_accessible_topics_query(user)).scalars().all()
    nodes = [{"id": str(t.id), "title": t.title, "parent_id": str(t.parent_id) if t.parent_id else None, "subject_id": str(t.subject_id) if t.subject_id else None} for t in rows]
    edges = [{"source": str(t.parent_id), "target": str(t.id), "kind": "parent"} for t in rows if t.parent_id]
    return {"nodes": nodes, "edges": edges}


@router.get("/admin/model-settings")
def admin_model_settings(_: str = Depends(_check_token), user: User = Depends(_get_current_user)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    settings = get_settings()
    return {
        "primary_provider": settings.llm_primary_provider,
        "primary_model": settings.llm_primary_model,
        "fallback_provider": settings.llm_fallback_provider,
        "fallback_model": settings.llm_fallback_model,
        "max_request_tokens": settings.llm_max_request_tokens,
    }


@router.get("/admin/evidence/source-coverage")
def admin_evidence_source_coverage(_: str = Depends(_check_token), user: User = Depends(_get_current_user)):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    settings = get_settings()
    path = Path(settings.evidence_sources_path)
    if not path.exists():
        return {"total_sources": 0, "by_region": {}, "by_species": {}, "by_category": {}, "missing": True}
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_region: dict[str, int] = {}
    by_species: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in payload.get("sources", []):
        by_region[row.get("region", "unknown")] = by_region.get(row.get("region", "unknown"), 0) + 1
        by_species[row.get("species", "unknown")] = by_species.get(row.get("species", "unknown"), 0) + 1
        by_category[row.get("category", "unknown")] = by_category.get(row.get("category", "unknown"), 0) + 1
    return {
        "total_sources": len(payload.get("sources", [])),
        "by_region": by_region,
        "by_species": by_species,
        "by_category": by_category,
        "missing": False,
    }


@router.get("/admin/evidence/needs-check")
def admin_evidence_needs_check(
    limit: int = 100,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_admin(user)
    rows = db.execute(
        select(Message)
        .where(Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(min(limit, 300))
    ).scalars().all()
    out = []
    for row in rows:
        meta = row.metadata_ or {}
        evidence = meta.get("evidence") or {}
        if evidence.get("needs_manual_check") or evidence.get("status") in {"needs_manual_check", "partially_verified"}:
            out.append(
                {
                    "message_id": row.id,
                    "session_id": row.session_id,
                    "created_at": row.created_at,
                    "status": evidence.get("status", "needs_manual_check"),
                    "citations": evidence.get("citations", []),
                    "high_risk": bool(meta.get("high_risk")),
                    "preview": row.content[:280],
                }
            )
    return out


@router.patch("/admin/users/{target_user_id}/role")
def admin_set_role(
    target_user_id: UUID,
    payload: WebSettingsUpdateRequest,
    _: str = Depends(_check_token),
    user: User = Depends(_get_current_user),
    db: Session = Depends(get_db),
):
    if not _allow_admin_rate_limit(user):
        raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
    _require_owner(user)
    if payload.role not in {"owner", "admin", "user"}:
        raise HTTPException(status_code=400, detail="Unsupported role")
    target = UserRepo(db).get_by_id(target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.role = payload.role
    db.commit()
    return {"ok": True, "id": target.id, "role": target.role}
