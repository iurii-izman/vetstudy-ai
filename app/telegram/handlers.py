import asyncio
from datetime import UTC, datetime
import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
from app.config import get_settings

from app.analytics import ProductAnalyticsService
from app.db.models import Flashcard
from app.db.repositories import DocumentChunkRepo, DocumentRepo, ErrorEventRepo, FeedbackEventRepo, FlashcardRepo, MemoryRepo, MessageRepo, ReviewEventRepo, SessionRepo, SubjectRepo, TopicRepo, UserRepo
from app.db.services import ChatDBService
from app.db.session import new_session
from app.learning.service import LearningService
from app.media.extractors import chunk_text, extract_document_text
from app.media.jobs import DocumentIndexJob, enqueue_document_index
from app.media.storage import download_telegram_file
from app.media.types import FileTooLargeError, UnsupportedMediaError
from app.memory.service import MemoryService
from app.evidence import EvidenceService
from app.errors import is_retryable_db_error, map_pipeline_error
from app.quotas import QuotaGuard
from sqlalchemy.exc import SQLAlchemyError
from app.services import llm_router, prompt_manager, safety_gate
from app.telegram.callbacks import parse_callback_data as _parse_callback_data
from app.telegram.callbacks import callback_data as _signed_callback_data
from app.telegram.ui import build_ai_reply_keyboard, build_main_menu_reply_keyboard, build_review_keyboard
from app.telegram.formatting import TELEGRAM_HTML_PARSE_MODE, format_ai_answer_for_telegram, split_for_telegram, strip_telegram_html
from app.telegram.onboarding import ONBOARDING_STEPS, REGION_VALUES, RESPONSE_DENSITY_VALUES, SPECIES_VALUES
from app.telegram.onboarding import apply_response_density as _apply_response_density
from app.telegram.onboarding import complete_onboarding_step as _complete_onboarding_step
from app.telegram.onboarding import infer_journey_state as _infer_journey_state
from app.telegram.onboarding import next_journey_step as _next_journey_step
from app.telegram.onboarding import onboarding_state as _onboarding_state
from app.telegram.onboarding import save_onboarding_state as _save_onboarding_state
from app.telegram.onboarding import set_journey_state as _set_journey_state
from app.telegram.onboarding import user_profile as _user_profile
from app.telegram.ux import guided_clarification_keyboard as _guided_clarification_keyboard
from app.telegram.ux import minimal_next_questions as _minimal_next_questions
from app.telegram.ux import next_step_keyboard as _next_step_keyboard
from app.telegram.ux import provider_error_text as _provider_error_text
from app.telegram.ux import quota_error_text as _quota_error_text
from app.telegram.ux import safety_error_text as _safety_error_text
from app.telegram.ux import topic_required_text as _topic_required_text
from app.telegram.ux import why_payload_for_meta as _why_payload_for_meta

router = Router()
logger = logging.getLogger("app.telegram.handlers")

MODES = {"short", "practical", "deep", "exam", "protocol", "cards", "quiz", "evidence"}
CASE_LEVELS = ("basic", "intermediate", "advanced")
DEFAULT_SUBJECTS = [
    ("pharmacology", "Фармакология", "Фокус на препаратах, дозах, противопоказаниях и рисках."),
    ("surgery", "Хирургия", "Фокус на хирургической тактике и послеоперационном ведении."),
    ("internal_medicine", "ВНБ", "Фокус на диагностике, дифференциалах и плане лечения."),
    ("anatomy", "Анатомия", "Фокус на структурной логике, ориентирах и экзаменационных связях."),
    ("general", "Общее", "Общие вопросы, кросс-темы и быстрые уточнения."),
]


def _check_allow(message: Message) -> bool:
    from app.config import get_settings

    settings = get_settings()
    allowed_ids = settings.allowed_user_ids
    allowed_usernames = getattr(settings, "allowed_usernames", set())
    if not allowed_ids and not allowed_usernames:
        return True
    user = message.from_user
    if not user:
        return False
    if user.id in allowed_ids:
        return True
    username = (getattr(user, "username", "") or "").lstrip("@").lower()
    return bool(username and username in allowed_usernames)


async def _deny_if_not_allowed(message: Message) -> bool:
    if _check_allow(message):
        return False
    user_id = getattr(getattr(message, "from_user", None), "id", "unknown")
    await message.answer(f"Доступ запрещен. Ваш Telegram ID: {user_id}. Передайте его владельцу beta для allowlist.")
    return True


async def _deny_callback_if_not_allowed(query: CallbackQuery) -> bool:
    settings = get_settings()
    allowed_ids = settings.allowed_user_ids
    allowed_usernames = getattr(settings, "allowed_usernames", set())
    username = (getattr(query.from_user, "username", "") or "").lstrip("@").lower()
    if not allowed_ids and not allowed_usernames:
        return False
    if query.from_user.id in allowed_ids or (username and username in allowed_usernames):
        return False
    await query.answer("Доступ запрещен.", show_alert=True)
    if query.message:
        await query.message.answer(f"Доступ запрещен. Ваш Telegram ID: {query.from_user.id}. Передайте его владельцу beta для allowlist.")
    return True


def _update_document_status(
    db,
    *,
    telegram_user_id: int,
    display_name: str | None,
    filename: str,
    status: str,
    job_id: str | None = None,
    chunks: int | None = None,
    error: str | None = None,
) -> None:
    row = UserRepo(db).get_or_create(telegram_user_id, display_name)
    docs = list((row.settings or {}).get("documents", []))
    for item in reversed(docs):
        same_job = item.get("job_id") == job_id if job_id else item.get("filename") == filename
        if same_job and item.get("status") == "queued":
            item["status"] = status
            if chunks is not None:
                item["chunks"] = chunks
            if error:
                item["error"] = error
            break
    row.settings = {**(row.settings or {}), "documents": docs}


def _document_job_is_queued(
    db,
    *,
    telegram_user_id: int,
    display_name: str | None,
    filename: str,
    job_id: str | None = None,
) -> bool:
    row = UserRepo(db).get_or_create(telegram_user_id, display_name)
    docs = list((row.settings or {}).get("documents", []))
    for item in reversed(docs):
        same_job = item.get("job_id") == job_id if job_id else item.get("filename") == filename
        if same_job:
            return item.get("status") == "queued"
    return False


async def _index_document_job(
    *,
    stored_path: Path,
    original_name: str,
    user_id: UUID,
    topic_id: UUID,
    telegram_user_id: int,
    display_name: str | None,
    job_id: str | None = None,
    retry_count: int = 0,
) -> None:
    db = new_session()
    try:
        doc_repo = DocumentRepo(db)
        user = UserRepo(db).get_or_create(telegram_user_id, display_name)
        doc = doc_repo.get_by_job_id(job_id or "") if hasattr(db, "execute") else None
        if doc and doc.status in {"indexed", "failed"}:
            return
        if not doc and not _document_job_is_queued(db, telegram_user_id=telegram_user_id, display_name=display_name, filename=original_name, job_id=job_id):
            return
        text = extract_document_text(stored_path, original_name)
        chunks = chunk_text(text)
        if not doc and hasattr(db, "execute"):
            doc = doc_repo.create_or_get(user_id=user.id, topic_id=topic_id, filename=original_name, size_bytes=stored_path.stat().st_size, job_id=job_id or str(uuid4()))
        mem = MemoryRepo(db)
        chunk_repo = DocumentChunkRepo(db)
        vectors = await llm_router.embed(db, user_id, chunks) if chunks else []
        for i, ch in enumerate(chunks):
            chunk_hash = hashlib.sha256(ch.encode("utf-8")).hexdigest()
            snippet = " ".join(ch.split())[:240]
            if doc and hasattr(db, "execute"):
                chunk_repo.add_or_get(
                    document_id=doc.id,
                    user_id=user_id,
                    topic_id=topic_id,
                    source_message_id=None,
                    chunk_index=i,
                    chunk_hash=chunk_hash,
                    content=ch,
                    snippet=snippet,
                    tags=["document", f"doc:{original_name}"],
                    embedding=vectors[i] if i < len(vectors) else None,
                    metadata_={"document_title": original_name, "job_id": job_id},
                )
            mem.add(
                user_id=user_id,
                topic_id=topic_id,
                source_message_id=None,
                kind="document_chunk",
                title=f"{original_name} chunk {i+1}",
                content=ch,
                tags=["document", f"doc:{original_name}"],
                embedding=vectors[i] if i < len(vectors) else None,
            )
        nudge_text = _build_document_learning_nudge(filename=original_name, chunks=chunks)
        settings = dict(user.settings or {})
        settings["last_document_learning_nudge"] = {
            "job_id": job_id,
            "filename": original_name,
            "topic_id": str(topic_id),
            "text": nudge_text,
            "created_at": datetime.now(UTC).isoformat(),
        }
        user.settings = settings
        if doc and hasattr(db, "execute"):
            doc_repo.update_status(document=doc, status="indexed", chunks=len(chunks))
        _update_document_status(
            db,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            filename=original_name,
            status="indexed",
            job_id=job_id,
            chunks=len(chunks),
        )
        db.commit()
    except UnsupportedMediaError as exc:
        doc = DocumentRepo(db).get_by_job_id(job_id or "") if hasattr(db, "execute") else None
        if doc:
            DocumentRepo(db).update_status(document=doc, status="failed", error=str(exc) or "unsupported_media")
        _update_document_status(
            db,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            filename=original_name,
            status="failed",
            job_id=job_id,
            error=str(exc) or "unsupported_media",
        )
        ErrorEventRepo(db).add(
            user_id=user_id,
            scope="media",
            category="document_index_failed",
            details={"filename": original_name, "error": str(exc), "kind": exc.__class__.__name__},
        )
    except Exception as exc:
        doc = DocumentRepo(db).get_by_job_id(job_id or "") if hasattr(db, "execute") else None
        if doc:
            DocumentRepo(db).update_status(document=doc, status="failed", error=exc.__class__.__name__)
        _update_document_status(
            db,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            filename=original_name,
            status="failed",
            job_id=job_id,
            error=exc.__class__.__name__,
        )
        ErrorEventRepo(db).add(
            user_id=user_id,
            scope="media",
            category="document_index_failed",
            details={"filename": original_name, "error": str(exc), "kind": exc.__class__.__name__},
        )
        raise
    finally:
        db.close()


async def _try_ingest_answer(memory: MemoryService, *, db, user_id, topic_id, source_message_id, answer: str, title: str, kind: str) -> None:
    try:
        await memory.ingest_assistant_answer(
            db=db,
            user_id=user_id,
            topic_id=topic_id,
            source_message_id=source_message_id,
            answer=answer,
            title=title,
            kind=kind,
        )
    except Exception:
        logger.exception(
            "memory_ingest_failed",
            extra={"event": "memory_ingest_failed", "error_category": "memory_error"},
        )


def _build_ai_reply_keyboard() -> InlineKeyboardMarkup:
    return build_ai_reply_keyboard()


def _build_review_keyboard(card_id: str) -> InlineKeyboardMarkup:
    return build_review_keyboard(card_id)


def _build_main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return build_main_menu_reply_keyboard()


def _callback_data(action: str, payload: str = "") -> str:
    return _signed_callback_data(action, payload)


def parse_callback_data(data: str):
    return _parse_callback_data(data)


def _build_document_learning_nudge(*, filename: str, chunks: list[str]) -> str:
    lines = [
        f"Документ `{filename}` проиндексирован.",
        "Рекомендация: 3 ключевые карточки + 1 мини-кейс.",
        "",
        "Карточки:",
    ]
    for idx, chunk in enumerate(chunks[:3], start=1):
        snippet = " ".join(chunk.split())[:170]
        lines.append(f"{idx}. Что важно по теме #{idx}? -> {snippet} [chunk:{idx}]")
    seed = " ".join((chunks[0] if chunks else "").split())[:180] or "Клинический фрагмент из документа."
    lines.extend(
        [
            "",
            f"Мини-кейс: пациент с похожим профилем из `{filename}`. Разберите triage и первый шаг диагностики. Основа: {seed} [chunk:1]",
            "Действия: /cards doc | /quiz | /save",
        ]
    )
    return "\n".join(lines)


async def _send_typing(message: Message) -> None:
    sender = getattr(getattr(message, "bot", None), "send_chat_action", None)
    if not sender:
        return
    kwargs = {"chat_id": message.chat.id, "action": "typing"}
    if message.message_thread_id is not None:
        kwargs["message_thread_id"] = message.message_thread_id
    try:
        await sender(**kwargs)
    except Exception:
        logger.debug("send_typing_failed", exc_info=True)


async def _answer_telegram_html(message: Message, text: str, **kwargs) -> None:
    try:
        await message.answer(text, parse_mode=TELEGRAM_HTML_PARSE_MODE, **kwargs)
    except TelegramBadRequest:
        logger.warning("telegram_html_render_failed", exc_info=True)
        await message.answer(strip_telegram_html(text), **kwargs)


async def _send_ai_answer(message: Message, answer: str, *, with_keyboard: bool = True) -> None:
    chunks = split_for_telegram(answer)
    for idx, chunk in enumerate(chunks):
        reply_markup = _build_ai_reply_keyboard() if with_keyboard and idx == len(chunks) - 1 else None
        await _answer_telegram_html(
            message,
            format_ai_answer_for_telegram(chunk),
            reply_markup=reply_markup,
        )


async def _run_text_pipeline(message: Message, user, topic, text: str, *, metadata: dict | None = None):
    for attempt in range(2):
        db = new_session()
        try:
            await _send_typing(message)
            quota = QuotaGuard(get_settings()).check_user_and_global(db, user)
            if not quota.allowed:
                ProductAnalyticsService(db).track(
                    user_id=user.id,
                    topic_id=topic.id,
                    event_name="journey_drop_detected",
                    properties={"reason": "quota_block", "stage": _infer_journey_state(user)},
                )
                await message.answer(quota.message or _quota_error_text(), reply_markup=_next_step_keyboard("quota"))
                return
            chat_db = ChatDBService(db)
            preferred_mode = (user.settings or {}).get("mode", "practical")
            evidence = EvidenceService()
            session = chat_db.get_or_create_active_session(user.id, topic.id, mode=preferred_mode)
            profile = _user_profile(user)
            analytics = ProductAnalyticsService(db)
            chat_db.save_user_message(session.id, text, message.message_id)
            analytics.track(
                user_id=user.id,
                topic_id=topic.id,
                session_id=session.id,
                event_name="activation_first_question",
                properties={"topic_title": getattr(topic, "title", "unknown"), "mode": session.mode},
            )
            safety = safety_gate.check(text)
            if not safety.allowed:
                warn = safety.warning or _safety_error_text()
                next_questions = _minimal_next_questions(safety=safety)
                warn = f"{warn}\n\n" + "\n".join(f"- {q}" for q in next_questions)
                analytics.track(
                    user_id=user.id,
                    topic_id=topic.id,
                    session_id=session.id,
                    event_name="safety_clarification_required",
                    properties={"risk_tags": getattr(safety, "risk_tags", [])},
                )
                analytics.track(
                    user_id=user.id,
                    topic_id=topic.id,
                    event_name="journey_drop_detected",
                    properties={"reason": "safety_block", "stage": _infer_journey_state(user)},
                )
                await message.answer(warn, reply_markup=_guided_clarification_keyboard())
                return
            memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
            search_results = await memory.search(db=db, user_id=user.id, query=text, current_topic_id=topic.id, top_k=5, cross_topic=True)
            memory_chunks = [
                f"[source={item.source_title or 'memory'} doc={item.document_id or '-'} chunk={item.chunk_id or item.memory_id or '-'}] {item.snippet}"
                for item in search_results
            ]
            subject = SubjectRepo(db).get_by_id(topic.subject_id)
            history_rows = MessageRepo(db).recent_for_session(session.id, limit=6)
            high_risk = evidence.is_high_risk(text, getattr(safety, "risk_tags", []))
            analytics.track(
                user_id=user.id,
                topic_id=topic.id,
                session_id=session.id,
                event_name="retrieval_context_built",
                properties={
                    "results": len(search_results),
                    "memory_hits": sum(1 for item in search_results if item.memory_id),
                    "document_hits": sum(1 for item in search_results if item.chunk_id),
                    "high_risk": high_risk,
                },
            )
            if high_risk:
                analytics.track(
                    user_id=user.id,
                    topic_id=topic.id,
                    session_id=session.id,
                    event_name="high_risk_query",
                    properties={"risk_tags": getattr(safety, "risk_tags", [])},
                )
            effective_mode = "evidence" if (session.mode == "evidence" or high_risk) else session.mode
            preferred_sources = evidence.preferred_sources(region=profile["region"], species_focus=profile["species_focus"])
            prompt = prompt_manager.build(
                mode=effective_mode,
                subject=subject.slug if subject else "general",
                user_message=text,
                memory_chunks=memory_chunks,
                session_history=[f"{row.role}: {row.content[:200]}" for row in history_rows],
                region=profile["region"],
                species_focus=profile["species_focus"],
                evidence_preference=", ".join(preferred_sources) if preferred_sources else None,
                safety_warning=safety.warning,
            )
            prompt += "\n\nEVIDENCE_POLICY:\n- Используй только факты, подтверждённые блоком RETRIEVED_MEMORY.\n- Не делай уверенных утверждений, если в памяти нет подтверждения.\n- Для каждого клинического тезиса добавляй ссылку вида [doc/chunk]."
            answer = await llm_router.generate(
                db,
                user.id,
                prompt,
                purpose="answer",
                metadata={
                    **(metadata or {}),
                    "safety": {
                        "intent": getattr(safety, "intent", None),
                        "risk_tags": list(getattr(safety, "risk_tags", []) or []),
                    },
                },
            )
            rendered_answer = answer
            evidence_payload = None
            if effective_mode == "evidence":
                evidence_resp = evidence.build_response(query=text, llm_answer=answer, retrieved=search_results, high_risk=high_risk)
                rendered_answer = evidence.render_markdown(evidence_resp)
                evidence_payload = {
                    "status": evidence_resp.status,
                    "verification_status": evidence_resp.verification_status,
                    "citations": evidence_resp.citations,
                    "trust_indicators": evidence_resp.trust_indicators,
                    "needs_manual_check": evidence_resp.needs_manual_check,
                    "manual_check_reasons": evidence_resp.manual_check_reasons,
                    "next_questions": evidence_resp.next_questions,
                }
            followup_questions = _minimal_next_questions(safety=safety, evidence_payload=evidence_payload)
            rendered_answer = _apply_response_density(rendered_answer, profile["response_density"])
            assistant_msg = chat_db.save_assistant_message(
                session.id,
                rendered_answer,
                metadata={
                    **(metadata or {}),
                    "topic_id": str(topic.id),
                    "effective_mode": effective_mode,
                    "high_risk": high_risk,
                    "evidence": evidence_payload,
                    "why_trace": {
                        "risk_intent": getattr(safety, "intent", None),
                        "risk_tags": list(getattr(safety, "risk_tags", []) or []),
                        "needs_manual_check": bool((evidence_payload or {}).get("needs_manual_check")),
                        "manual_check_reasons": list((evidence_payload or {}).get("manual_check_reasons", []) or []),
                        "missing_data": followup_questions,
                    },
                },
            )
            analytics.track(
                user_id=user.id,
                topic_id=topic.id,
                session_id=session.id,
                event_name="activation_first_answer",
                properties={"effective_mode": effective_mode, "high_risk": high_risk},
            )
            _set_journey_state(user=user, state="activation", reason="first_answer_generated", analytics=analytics, topic_id=topic.id)
            if (metadata or {}).get("source_type") == "voice":
                analytics.track(
                    user_id=user.id,
                    topic_id=topic.id,
                    session_id=session.id,
                    event_name="voice_summary_generated",
                    properties={"response_density": profile["response_density"]},
                )
            needs_followup = bool((evidence_payload or {}).get("status") in {"needs_manual_check", "partially_verified"})
            await _send_ai_answer(message, rendered_answer)
            if needs_followup and followup_questions:
                guidance = "Чтобы повысить уверенность ответа, уточните:\n" + "\n".join(f"- {q}" for q in followup_questions)
                await message.answer(guidance, reply_markup=_guided_clarification_keyboard())
            await _try_ingest_answer(
                memory,
                db=db,
                user_id=user.id,
                topic_id=topic.id,
                source_message_id=assistant_msg.id,
                answer=rendered_answer,
                title="Ответ",
                kind="answer",
            )
            return
        except SQLAlchemyError as exc:
            db.rollback()
            if is_retryable_db_error(exc) and attempt == 0:
                logger.warning("db_error_retrying_once", extra={"event": "telegram_pipeline_db_retry", "error_category": "db_error"})
                await asyncio.sleep(2)
                continue
            ProductAnalyticsService(db).track(user_id=user.id, topic_id=topic.id, event_name="error_event", properties={"kind": "db"})
            ErrorEventRepo(db).add(
                user_id=user.id,
                scope="telegram",
                category="telegram_pipeline_db_error",
                details={"topic_id": str(topic.id), "message_id": message.message_id},
            )
            logger.exception("db_error_in_pipeline", extra={"event": "telegram_pipeline_error", "error_category": "db_error"})
            await message.answer(map_pipeline_error(exc).user_message)
            return
        except RuntimeError:
            ProductAnalyticsService(db).track(user_id=user.id, topic_id=topic.id, event_name="error_event", properties={"kind": "provider"})
            ProductAnalyticsService(db).track(
                user_id=user.id,
                topic_id=topic.id,
                event_name="journey_drop_detected",
                properties={"reason": "provider_error", "stage": _infer_journey_state(user)},
            )
            ErrorEventRepo(db).add(
                user_id=user.id,
                scope="telegram",
                category="telegram_pipeline_provider_error",
                details={"topic_id": str(topic.id), "message_id": message.message_id},
            )
            logger.exception("provider_runtime_error", extra={"event": "telegram_pipeline_error", "error_category": "provider_error"})
            await message.answer(_provider_error_text(), reply_markup=_next_step_keyboard("provider"))
            return
        except Exception as exc:
            mapped = map_pipeline_error(exc)
            if mapped.category == "quota_error":
                ProductAnalyticsService(db).track(
                    user_id=user.id,
                    topic_id=topic.id,
                    event_name="journey_drop_detected",
                    properties={"reason": "quota_error", "stage": _infer_journey_state(user)},
                )
                await message.answer(_quota_error_text(), reply_markup=_next_step_keyboard("quota"))
                return
            ErrorEventRepo(db).add(
                user_id=user.id,
                scope="telegram",
                category="telegram_pipeline_unexpected_error",
                details={"topic_id": str(topic.id), "message_id": message.message_id, "error": str(exc)},
            )
            ProductAnalyticsService(db).track(user_id=user.id, topic_id=topic.id, event_name="error_event", properties={"kind": "unexpected"})
            logger.exception("pipeline_failed", extra={"event": "telegram_pipeline_error", "error_category": "telegram_error"})
            await message.answer(
                "Временная ошибка обработки. Следующий шаг: повторите запрос или используйте /today для продолжения обучения.",
                reply_markup=_next_step_keyboard("provider"),
            )
            return
        finally:
            db.close()


@router.message(Command("start"))
async def cmd_start(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    first_step = {"command": "/create_default_topics", "fallback": "/bind_topic pharmacology", "goal": "получить первый учебный маршрут"}
    try:
        try:
            user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
            analytics = ProductAnalyticsService(db)
            ProductAnalyticsService(db).track(user_id=user.id, event_name="activation_start")
            onboarding = _onboarding_state(user)
            if not onboarding:
                onboarding = {"completed_steps": [], "is_completed": False}
                _save_onboarding_state(user, onboarding)
                analytics.track(user_id=user.id, event_name="onboarding_started", properties={"steps_total": len(ONBOARDING_STEPS)})
                db.commit()
            first_step = _next_journey_step(user=user, context="start")
        except Exception:
            logger.debug("activation_start_track_failed", exc_info=True)
    finally:
        db.close()
    await message.answer(
        "VetStudy AI готов. First value за 10 минут:\n"
        "1) /today standard\n"
        "2) /case basic\n"
        "3) /review\n\n"
        "Онбординг (3 шага):\n"
        "1) Привяжи учебный topic: /create_default_topics или /bind_topic <slug_or_name>\n"
        "2) Открой персональный маршрут: /today\n"
        "3) Запусти клинический кейс: /case basic\n\n"
        f"CTA: {first_step['command']}\n"
        f"Fallback: {first_step['fallback']}\n"
        f"Цель: {first_step['goal']}.",
        reply_markup=_next_step_keyboard("first_value"),
    )
    await message.answer(
        "One-tap сценарий: нажми кнопку ниже и закрой today+case+review без переключения контекста.",
        reply_markup=_build_main_menu_reply_keyboard(),
    )


@router.message(F.text == "📅 На сегодня")
async def text_today(message: Message):
    await cmd_today(message)


@router.message(F.text == "🩺 Кейсы")
async def text_case(message: Message):
    await cmd_case(message, CommandObject(command="/case", args=""))


@router.message(F.text == "🧠 Карточки")
async def text_review(message: Message):
    await cmd_review(message)


@router.message(F.text == "➕ Создать")
async def text_cards(message: Message):
    await cmd_cards(message, CommandObject(command="/cards", args=""))


@router.message(F.text == "📚 Темы")
async def text_topics(message: Message):
    await cmd_topics(message)


@router.message(F.text == "⚙️ Профиль")
async def text_profile(message: Message):
    await cmd_profile(message, CommandObject(command="/profile", args=""))


@router.message(Command("help"))
async def cmd_help(message: Message):
    if await _deny_if_not_allowed(message):
        return
    await message.answer(
        "Онбординг:\n/start\n/status\n/topics\n/create_default_topics\n/bind_topic <slug_or_name>\n\n"
        "Сессия:\n/new\n/mode\n/evidence\n/why\n/save\n/search\n/summary\n/profile\n\n"
        "Обучение:\n/today [light|standard|intensive]\n/plan_week\n/cards\n/review\n/quiz\n/export\n\n"
        "Отчет:\n/weekly\n\n"
        "Клинические кейсы:\n/case — выбрать виртуальный кейс\n/case_answer — отправить анализ на оценку\n\n"
        "Система:\n/docs\n/help",
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    raw = (command.args or "").strip().lower()
    db = new_session()
    try:
        user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
        current = _user_profile(user)
        if not raw:
            await message.answer(
                "Профиль:\n"
                f"- region: {current['region']}\n"
                f"- species_focus: {current['species_focus']}\n\n"
                f"- response_density: {current['response_density']}\n\n"
                "Изменить: /profile region=<us|eu|local|unspecified> species=<dog|cat|dog_cat> density=<quick|balanced|deep>"
            )
            return
        updates = dict(current)
        for part in raw.split():
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            value = value.strip().lower()
            if key == "region" and value in REGION_VALUES:
                updates["region"] = value
            if key == "species" and value in SPECIES_VALUES:
                updates["species_focus"] = value
            if key == "density" and value in RESPONSE_DENSITY_VALUES:
                updates["response_density"] = value
        settings = dict(user.settings or {})
        settings["profile"] = updates
        user.settings = settings
        db.commit()
        ProductAnalyticsService(db).track(user_id=user.id, event_name="profile_updated", properties=updates)
        await message.answer(
            "Профиль обновлен: "
            f"region={updates['region']}, species_focus={updates['species_focus']}, response_density={updates['response_density']}"
        )
    finally:
        db.close()


@router.message(Command("status"))
async def cmd_status(message: Message):
    if await _deny_if_not_allowed(message):
        return
    settings = get_settings()
    bot_name = "unknown"
    can_manage_topics = "unknown"
    try:
        me = await message.bot.get_me()
        bot_name = f"@{me.username}" if getattr(me, "username", None) else str(getattr(me, "id", "unknown"))
        member = await message.bot.get_chat_member(message.chat.id, me.id)
        can_manage_topics = "yes" if bool(getattr(member, "can_manage_topics", False)) else "no"
    except Exception:
        logger.debug("status_bot_permissions_check_failed", exc_info=True)

    db = new_session()
    try:
        user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = TopicRepo(db).get_by_chat_thread(message.chat.id, message.message_thread_id)
        docs = list((user.settings or {}).get("documents", []))
        mode = (user.settings or {}).get("mode", "practical")
        topic_text = f"{topic.title} (bound)" if topic and topic.subject_id else "not bound"
        lines = [
            "VetStudy AI status",
            f"bot: {bot_name}",
            f"chat_id: {message.chat.id}",
            f"thread_id: {message.message_thread_id}",
            f"topic: {topic_text}",
            f"mode: {mode}",
            f"can_manage_topics: {can_manage_topics}",
            f"llm: {settings.llm_primary_provider}/{settings.llm_primary_model} -> fallback {settings.llm_fallback_provider}/{settings.llm_fallback_model}",
            f"embeddings: {settings.llm_embeddings_provider}/{settings.llm_embeddings_model}",
            f"redis_jobs: {'on' if settings.redis_url else 'off'}",
            f"docs: {len(docs)} total",
            f"ocr: {'on' if settings.multimodal_ocr_enabled else 'off'}, vision: {'on' if settings.multimodal_vision_enabled else 'off'}",
        ]
        if not topic or not topic.subject_id:
            lines.append("next: /bind_topic <slug_or_name> or /create_default_topics")
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(Command("docs"))
async def cmd_docs(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
        docs = (user.settings or {}).get("documents", [])
        table_docs = DocumentRepo(db).list_by_user(user.id, limit=20)
        if not docs:
            docs = []
        lines = ["Загруженные документы:"]
        for row in table_docs:
            lines.append(f"- {row.filename} | status={row.status} | size={row.size_bytes} bytes")
        for item in docs[-20:]:
            lines.append(f"- {item.get('filename')} | status={item.get('status')} | size={item.get('size_bytes')} bytes")
        nudge = (user.settings or {}).get("last_document_learning_nudge") or {}
        if nudge.get("text"):
            lines.extend(["", "Proactive learning:", str(nudge.get("text"))])
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="document_learning_nudge_viewed",
                properties={"job_id": nudge.get("job_id"), "filename": nudge.get("filename")},
            )
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(Command("topics"))
async def cmd_topics(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        topics = TopicRepo(db).list_by_chat(message.chat.id)
        current = TopicRepo(db).get_by_chat_thread(message.chat.id, message.message_thread_id)
        lines = [f"Текущий thread id: {message.message_thread_id}", ""]
        if topics:
            lines.append("Темы в БД:")
            for item in topics:
                bound = "привязан" if item.subject_id else "не привязан"
                lines.append(f"- {item.title} | thread={item.telegram_thread_id} | {bound}")
        else:
            lines.append("Для этого чата темы в БД пока отсутствуют.")
        lines.append("")
        if not current or not current.subject_id:
            lines.append("Текущий topic не привязан. Используйте: /bind_topic <slug_or_name>")
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(Command("bind_topic"))
async def cmd_bind_topic(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    value = (command.args or "").strip()
    if not value:
        await message.answer("Использование: /bind_topic <slug_or_name>")
        return
    db = new_session()
    try:
        user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
        subject = SubjectRepo(db).get_by_slug_or_title(value)
        if not subject:
            await message.answer(
                "Тема не найдена в subjects. Проверьте slug/title или создайте subject в БД.",
            )
            return
        topic = TopicRepo(db).bind_subject(chat_id=message.chat.id, thread_id=message.message_thread_id, subject=subject)
        ProductAnalyticsService(db).track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="activation_topic_bound",
            properties={"subject": subject.slug},
        )
        _complete_onboarding_step(user=user, step="bind_topic", analytics=ProductAnalyticsService(db), topic_id=topic.id)
        db.commit()
        await message.answer(
            f"Привязано: '{topic.title}' (slug={subject.slug}) к thread id {message.message_thread_id}.",
        )
    finally:
        db.close()


async def _bot_can_manage_topics(message: Message) -> bool:
    me = await message.bot.get_me()
    member = await message.bot.get_chat_member(message.chat.id, me.id)
    return bool(getattr(member, "can_manage_topics", False))


@router.message(Command("create_default_topics"))
async def cmd_create_default_topics(message: Message):
    if await _deny_if_not_allowed(message):
        return
    try:
        can_manage = await _bot_can_manage_topics(message)
    except Exception:
        can_manage = False
    if not can_manage:
        await message.answer(
            "Недостаточно прав.\n"
            "Выдайте боту админ-права в группе и включите `can_manage_topics`, затем повторите /create_default_topics.",
        )
        return

    db = new_session()
    try:
        user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
        subject_repo = SubjectRepo(db)
        topic_repo = TopicRepo(db)
        created = []
        for slug, title, system_prompt in DEFAULT_SUBJECTS:
            subject = subject_repo.get_or_create(slug=slug, title=title, system_prompt=system_prompt)
            existing = next((t for t in topic_repo.list_by_chat(message.chat.id) if t.subject_id == subject.id and t.telegram_thread_id), None)
            if existing:
                continue
            forum_topic = await message.bot.create_forum_topic(chat_id=message.chat.id, name=title)
            topic = topic_repo.bind_subject(chat_id=message.chat.id, thread_id=forum_topic.message_thread_id, subject=subject)
            ProductAnalyticsService(db).track(
                user_id=user.id,
                topic_id=topic.id,
                event_name="activation_topic_bound",
                properties={"subject": subject.slug, "created_default": True},
            )
            created.append(f"{title} (thread={forum_topic.message_thread_id})")
        if created:
            await message.answer("Созданы темы:\n" + "\n".join(f"- {x}" for x in created))
        else:
            await message.answer("Темы уже существуют, новых не создано.")
    finally:
        db.close()


@router.message(Command("new"))
async def cmd_new(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session = SessionRepo(db).new_active(user.id, topic.id)
        ProductAnalyticsService(db).track(user_id=user.id, topic_id=topic.id, session_id=session.id, event_name="session_new")
        await message.answer(f"Новая сессия создана: {session.id}")
    finally:
        db.close()


@router.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    mode = (command.args or "").strip()
    if not mode:
        await message.answer("Режимы: short|practical|deep|exam|protocol|cards|quiz|evidence")
        return
    if mode not in MODES:
        await message.answer("Использование: /mode short|practical|deep|exam|protocol|cards|quiz|evidence")
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session_repo = SessionRepo(db)
        session = session_repo.get_active(user.id, topic.id) or session_repo.new_active(user.id, topic.id, mode=mode)
        session.mode = mode
        UserRepo(db).set_mode_preference(user, mode)
        db.commit()
        await message.answer(f"Режим переключен: {mode}")
    finally:
        db.close()


@router.message(Command("evidence"))
async def cmd_evidence(message: Message):
    await cmd_mode(message, CommandObject(command="/mode", args="evidence"))


@router.message(Command("why"))
async def cmd_why(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session = SessionRepo(db).get_active(user.id, topic.id)
        if not session:
            await message.answer("Нет активной сессии. Сначала задайте вопрос.")
            return
        last = MessageRepo(db).last_assistant(session.id)
        if not last:
            await message.answer("Пока нет ответа для explain-режима.")
            return
        meta = dict(last.metadata_ or {})
        trace = dict(meta.get("why_trace") or _why_payload_for_meta(meta))
        risk_tags = list(trace.get("risk_tags") or [])
        reasons = list(trace.get("manual_check_reasons") or [])
        missing_data = list(trace.get("missing_data") or [])
        lines = [
            "Explain (/why) для последнего ответа:",
            f"- risk intent: {trace.get('risk_intent') or 'unknown'}",
            f"- risk tags: {', '.join(risk_tags) if risk_tags else 'none'}",
        ]
        needs_manual = bool(trace.get("needs_manual_check"))
        lines.append(f"- needs_manual_check: {'yes' if needs_manual else 'no'}")
        if reasons:
            lines.append("- почему needs_manual_check:")
            lines.extend([f"  • {item}" for item in reasons[:3]])
        if missing_data:
            lines.append("- каких данных не хватило:")
            lines.extend([f"  • {item}" for item in missing_data[:3]])
        learning_ctx = dict(((user.settings or {}).get("learning") or {}))
        route_ctx = dict(learning_ctx.get("last_route") or {})
        if route_ctx:
            lines.append("- personalization:")
            lines.append(f"  • difficulty: {route_ctx.get('difficulty_band', 'medium')}")
            lines.append(f"  • progression: {route_ctx.get('progression_mode', 'controlled_progression')}")
            lines.append(f"  • why: {route_ctx.get('why_personalization', 'n/a')}")
        lines.append("Без внутренних системных промптов и секретов.")
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(Command("summary"))
async def cmd_summary(message: Message):
    if await _deny_if_not_allowed(message):
        return
    mode = ((message.text or "").split(maxsplit=1)[1].strip().lower() if " " in (message.text or "") else "topic")
    if mode not in {"topic", "current", "session"}:
        mode = "topic"
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = TopicRepo(db).get_by_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
        content = await memory.summarize_topic(
            db=db,
            user_id=user.id,
            topic_id=topic.id,
            mode="session" if mode in {"current", "session"} else "topic",
        )
        await _answer_telegram_html(message, format_ai_answer_for_telegram(content))
    finally:
        db.close()


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    query = (command.args or "").strip()
    if not query:
        await message.answer("Использование: /search текст")
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = TopicRepo(db).get_by_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
        results = await memory.search(
            db=db,
            user_id=user.id,
            query=query,
            current_topic_id=topic.id,
            top_k=5,
            cross_topic=True,
        )
        ProductAnalyticsService(db).track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="search_performed",
            properties={"query": query[:120], "results": len(results), "topic_title": topic.title},
        )
        if not results:
            text = "Ничего не найдено."
            reply_markup = None
        else:
            lines = []
            keyboard_rows = []
            settings = dict(getattr(user, "settings", {}) or {})
            selected = settings.get("selected_memory_id", "")
            for i, item in enumerate(results[:7], 1):
                date = item.created_at.strftime("%Y-%m-%d")
                memory_id = getattr(item, "memory_id", "")
                mark = " ✅" if selected and selected == memory_id else ""
                lines.append(f"{i}. [{item.topic_title}] {date} — {item.snippet}{mark}")
                if memory_id:
                    keyboard_rows.append([InlineKeyboardButton(text=f"Выбрать {i}", callback_data=_callback_data("pick", memory_id))])
            text = "\n".join(lines[: max(3, min(7, len(lines)))])
            reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows[:7]) if keyboard_rows else None
        await message.answer(text, reply_markup=reply_markup)
    finally:
        db.close()


@router.message(Command("save"))
async def cmd_save(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    title = (command.args or "").strip() or "Заметка"
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session = SessionRepo(db).get_active(user.id, topic.id)
        if not session:
            await message.answer("Нет активной сессии.")
            return
        last = MessageRepo(db).last_assistant(session.id)
        if not last:
            await message.answer("Нет ответа для сохранения.")
            return
        MemoryRepo(db).add(user_id=user.id, topic_id=topic.id, source_message_id=last.id, kind="note", title=title, content=last.content)
        await message.answer("Сохранено.")
    finally:
        db.close()


@router.message(Command("cards"))
async def cmd_cards(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    source = (command.args or "").strip().lower()
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session = SessionRepo(db).get_active(user.id, topic.id)
        memory_repo = MemoryRepo(db)
        source_message_id = None
        tags = ["cards"]
        text = ""
        if source == "summary":
            summary_item = memory_repo.latest_by_kind(topic_id=topic.id, kind="summary")
            text = summary_item.content if summary_item else (topic.summary or "")
            source_message_id = summary_item.source_message_id if summary_item else None
            tags.append("summary")
        elif source == "search":
            selected_id = (user.settings or {}).get("selected_memory_id")
            selected = memory_repo.get(UUID(selected_id)) if selected_id else None
            if not selected:
                await message.answer("Сначала выберите результат из /search.")
                return
            text = selected.content
            source_message_id = selected.source_message_id
            tags.extend(selected.tags or [])
            tags.append("search")
        elif source in {"doc", "document"}:
            nudge = (user.settings or {}).get("last_document_learning_nudge") or {}
            text = str(nudge.get("text") or "")
            tags.extend(["document", "document_recap"])
            source_message_id = None
            source = "document"
            if not text:
                await message.answer("Нет готового document recap. Сначала дождитесь индексации и откройте /docs.")
                return
        else:
            if not session:
                await message.answer("Нет активной сессии.")
                return
            last = MessageRepo(db).last_assistant(session.id)
            if not last:
                await message.answer("Нет ответа для генерации карточек.")
                return
            text = last.content
            source_message_id = last.id
            tags.append("answer")

        if not text.strip():
            await message.answer("Нет данных для генерации карточек.")
            return
        learning = LearningService()
        payload_cards = await learning.generate_cards_structured(
            llm_router=llm_router,
            db=db,
            user_id=user.id,
            text=text,
            count=6,
            tags=sorted(set(tags)),
            source_message_id=str(source_message_id) if source_message_id else None,
        )
        cards = [
            Flashcard(
                user_id=user.id,
                topic_id=topic.id,
                source_message_id=source_message_id,
                front=item["front"],
                back=item["back"],
                card_type=item.get("card_type", "fact"),
                needs_manual_check=item.get("needs_manual_check", False),
                tags=sorted(set([*item.get("tags", []), f"difficulty:{item.get('difficulty', 'medium')}"])),
                due_at=datetime.now(UTC),
                ease=2.5,
                interval_days=1,
            )
            for item in payload_cards
        ]
        if not cards:
            await message.answer("Не удалось собрать валидные карточки из ответа модели.")
            return
        FlashcardRepo(db).add_many(cards)
        ProductAnalyticsService(db).track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="cards_created",
            properties={"count": len(cards), "source": source or "answer"},
        )
        if source == "document":
            ProductAnalyticsService(db).track(
                user_id=user.id,
                topic_id=topic.id,
                event_name="document_to_cards_converted",
                properties={"count": len(cards)},
            )
        ProductAnalyticsService(db).track(user_id=user.id, topic_id=topic.id, event_name="activation_first_cards")
        preview = "\n\n".join(f"Q: {c.front}\nA: {c.back}" for c in cards[:5])
        await message.answer(f"Сгенерировано карточек: {len(cards)}\n\n{preview}")
    finally:
        db.close()


@router.message(Command("quiz"))
async def cmd_quiz(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        session = SessionRepo(db).get_active(user.id, topic.id)
        if not session:
            await message.answer("Нет активной сессии.")
            return
        last = MessageRepo(db).last_assistant(session.id)
        if not last:
            await message.answer("Нет ответа для генерации quiz.")
            return
        items = await LearningService().generate_quiz_structured(llm_router=llm_router, db=db, user_id=user.id, text=last.content, count=7)
        lines = ["Тест:"]
        for item in items:
            lines.append(item.question)
            lines.extend(item.options)
            lines.append(f"Ответ: {item.correct_answer}")
            lines.append(f"Пояснение: {item.explanation}")
            lines.append("")
        await message.answer("\n".join(lines).strip())
    finally:
        db.close()


@router.message(Command("review"))
async def cmd_review(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        due_cards = FlashcardRepo(db).list_due(user_id=user.id, topic_id=topic.id, now=datetime.now(UTC), limit=10)
        if not due_cards:
            await message.answer("Сейчас нет карточек к повторению.")
            return
        card = due_cards[0]
        hint = "\n\n💡 Подсказка: разбить карточку." if "leech" in (card.tags or []) else ""
        await message.answer(
            f"Карточка:\n{card.front}\n\nОтвет скрыт. Нажмите «Показать ответ».{hint}",
            reply_markup=_build_review_keyboard(str(card.id)),
        )
    finally:
        db.close()


@router.message(Command("today"))
async def cmd_today(message: Message, command: CommandObject | None = None):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        requested_mode = ((command.args or "").strip().lower() if command else "") or "standard"
        route = LearningService().build_daily_route(db=db, user_id=user.id, topic_id=topic.id, mode=requested_mode)
        streak_days, relaunch_days = LearningService().compute_streak(db=db, user_id=user.id)
        analytics = ProductAnalyticsService(db)
        analytics.track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="learning_route_opened",
            properties={
                "mode": route.mode,
                "plan_minutes": route.plan_minutes,
                "used_fallback": route.used_fallback,
                "due_count": route.due_count,
                "weak_topics_count": len(route.weak_topics),
                "zero_result_searches": route.zero_result_searches,
                "negative_feedback_count": route.negative_feedback_count,
                "high_risk_block_count": route.high_risk_block_count,
                "streak_days": streak_days,
                "difficulty_band": route.difficulty_band,
                "progression_mode": route.progression_mode,
                "recovery_mode": route.recovery_mode,
                "why_personalization": route.why_personalization,
            },
        )
        settings = dict(user.settings or {})
        learning = dict(settings.get("learning") or {})
        learning["last_route"] = {
            "difficulty_band": route.difficulty_band,
            "progression_mode": route.progression_mode,
            "recovery_mode": route.recovery_mode,
            "why_personalization": route.why_personalization,
        }
        settings["learning"] = learning
        user.settings = settings
        db.commit()
        if streak_days in {3, 7, 14, 30}:
            analytics.track(user_id=user.id, topic_id=topic.id, event_name="streak_milestone_reached", properties={"days": streak_days})
        if relaunch_days > 0:
            analytics.track(user_id=user.id, topic_id=topic.id, event_name="learning_relaunched", properties={"after_days": relaunch_days})
            analytics.track(
                user_id=user.id,
                topic_id=topic.id,
                event_name="journey_recovered",
                properties={"after_days": relaunch_days, "from": "dropout"},
            )
        if relaunch_days >= 3:
            analytics.track(user_id=user.id, topic_id=topic.id, event_name="return_after_dropout_nudge", properties={"dropout_days": relaunch_days})
        _complete_onboarding_step(user=user, step="today_route", analytics=analytics, topic_id=topic.id)
        if route.due_count >= 2 and route.high_risk_block_count == 0:
            _set_journey_state(user=user, state="habit", reason="stable_daily_route", analytics=analytics, topic_id=topic.id)
        else:
            _set_journey_state(user=user, state="activation", reason="daily_route_opened", analytics=analytics, topic_id=topic.id)
        journey_next = _next_journey_step(user=user, context="today")
        lines = [
            f"Маршрут на {route.plan_minutes} минут ({route.mode}):",
            f"1) Мини-кейс: {route.mini_case}",
            f"2) Препарат/риск: {route.drug_risk}",
            f"3) Повтор: карточки к сроку {route.due_count}",
            "4) Повтори 3 карточки:",
        ]
        for idx, card_front in enumerate(route.review_cards[:3], start=1):
            lines.append(f"   {idx}. {card_front}")
        if route.weak_topics:
            lines.append(f"Слабые темы: {', '.join(route.weak_topics)}")
        if route.zero_result_searches > 0:
            lines.append(f"Zero-result поисков за 7 дней: {route.zero_result_searches}")
        if route.negative_feedback_count > 0:
            lines.append(f"Негативный feedback за 7 дней: {route.negative_feedback_count}")
        if route.high_risk_block_count > 0:
            lines.append(f"High-risk блокировок за 7 дней: {route.high_risk_block_count}")
        lines.append(f"Streak: {streak_days} дн.")
        lines.append(f"Difficulty: {route.difficulty_band} | Progression: {route.progression_mode}")
        lines.append(f"5) Reflection: {route.reflection_question}")
        lines.append(f"Следующий шаг ({journey_next['state']}): {journey_next['command']} -> цель: {journey_next['goal']}")
        if relaunch_days > 0:
            lines.append(f"Возврат после паузы: {relaunch_days} дн. Отличный рестарт, продолжай в комфортном темпе.")
        if relaunch_days >= 3:
            lines.append("Мягкий сценарий возврата: начни с /today light, затем закрой 2 карточки через /review.")
        if route.high_risk_block_count >= 3:
            lines.append("Много high-risk блокировок: переключаемся на безопасный тренировочный кейс /case basic.")
        await message.answer("\n".join(lines), reply_markup=_next_step_keyboard("learning"))
    finally:
        db.close()


@router.message(Command("plan_week"))
async def cmd_plan_week(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        plan = LearningService().build_week_plan(db=db, user_id=user.id, topic_id=topic.id)
        ProductAnalyticsService(db).track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="weekly_plan_opened",
            properties={
                "days": len(plan.days),
                "overdue_count": plan.overdue_count,
                "streak_days": plan.streak_days,
                "weak_topics_count": len(plan.weak_topics),
                "workload_budget": plan.workload_budget,
                "total_density": plan.total_density,
                "why_plan": plan.why_plan,
            },
        )
        lines = [
            "Персональный план на 7 дней:",
            f"Streak: {plan.streak_days} дн., overdue карточек: {plan.overdue_count}",
            f"Cognitive load: density {plan.total_density}/{plan.workload_budget}",
            f"Why this plan: {plan.why_plan}",
        ]
        for day in plan.days:
            lines.append(
                f"День {day.day_index} [{day.mode}] {day.focus}: {day.mini_case} | /case x1, /review x{day.review_target}, /quiz x{day.quiz_target}"
            )
        await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🩺 Начать /case", switch_inline_query_current_chat="/case basic")],
            [InlineKeyboardButton(text="🔁 Начать /review", switch_inline_query_current_chat="/review")],
            [InlineKeyboardButton(text="🧪 Начать /quiz", switch_inline_query_current_chat="/quiz 3")],
        ]))
    finally:
        db.close()


@router.message(Command("weekly"))
async def cmd_weekly(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        recap = LearningService().build_weekly_recap(db=db, user_id=user.id)
        ProductAnalyticsService(db).track(
            user_id=user.id,
            event_name="weekly_recap_opened",
            properties={
                "cards_created": recap.cards_created,
                "cards_reviewed": recap.cards_reviewed,
                "high_risk_queries": recap.high_risk_queries,
                "questions_asked": recap.questions_asked,
            },
        )
        lines = [
            "Weekly recap (7 дней):",
            f"- Cards created: {recap.cards_created}",
            f"- Review done: {recap.cards_reviewed}",
            f"- High-risk questions: {recap.high_risk_queries}",
            f"- Questions asked: {recap.questions_asked}",
        ]
        if recap.weak_topics:
            lines.append(f"- Weak topics: {', '.join(recap.weak_topics)}")
        await message.answer("\n".join(lines))
    finally:
        db.close()


# ──────────────────────────────────────────────
# /case  –  virtual clinical case training flow
# ──────────────────────────────────────────────
from app.cases import CASES, CASE_EDUCATIONAL_DISCLAIMER, get_case_by_id  # noqa: E402


def _case_select_keyboard(level: str | None = None) -> InlineKeyboardMarkup:
    items = _cases_for_level(level) if level in CASE_LEVELS else CASES
    rows = [
        [InlineKeyboardButton(text=c["title"], callback_data=_callback_data("case_select", c["id"]))]
        for c in items
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _case_level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Basic", callback_data=_callback_data("case_level", "basic"))],
            [InlineKeyboardButton(text="Intermediate", callback_data=_callback_data("case_level", "intermediate"))],
            [InlineKeyboardButton(text="Advanced", callback_data=_callback_data("case_level", "advanced"))],
        ]
    )


def _case_answer_keyboard(case_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Отправить анализ", callback_data=_callback_data("case_submit", case_id))],
            [InlineKeyboardButton(text="🔄 Другой кейс", callback_data=_callback_data("case_list", ""))],
        ]
    )


def _get_user_case_id(user) -> str | None:
    return (user.settings or {}).get("active_case_id")


def _get_case_level(user) -> str:
    settings = dict(user.settings or {})
    level = str(settings.get("case_level", "basic")).lower()
    if level not in CASE_LEVELS:
        return "basic"
    return level


def _set_case_level(user, level: str) -> None:
    settings = dict(user.settings or {})
    settings["case_level"] = level if level in CASE_LEVELS else "basic"
    user.settings = settings


def _case_level_for_case(case_id: str) -> str:
    if case_id in {"vomiting_dog", "nsaid_risk_dog", "bloody_diarrhea_puppy", "seizure_dog"}:
        return "basic"
    if case_id in {"dyspnea_cat", "pyometra_suspicion", "blocked_cat"}:
        return "intermediate"
    return "advanced"


def _cases_for_level(level: str) -> list[dict]:
    return [item for item in CASES if _case_level_for_case(item["id"]) == level] or CASES


def _apply_case_progression(user, submitted_level: str) -> tuple[str, dict]:
    settings = dict(user.settings or {})
    progress = dict(settings.get("case_progress") or {})
    completed = dict(progress.get("completed") or {})
    completed[submitted_level] = int(completed.get(submitted_level, 0) or 0) + 1
    next_level = _get_case_level(user)
    if submitted_level == "basic" and completed.get("basic", 0) >= 2:
        next_level = "intermediate"
    elif submitted_level == "intermediate" and completed.get("intermediate", 0) >= 2:
        next_level = "advanced"
    progress["completed"] = completed
    progress["updated_at"] = datetime.now(UTC).isoformat()
    settings["case_progress"] = progress
    settings["case_level"] = next_level
    user.settings = settings
    return next_level, progress


def _set_user_case_id(user, case_id: str | None) -> None:
    settings = dict(user.settings or {})
    if case_id is None:
        settings.pop("active_case_id", None)
        settings.pop("active_case_answer", None)
    else:
        settings["active_case_id"] = case_id
    user.settings = settings


@router.message(Command("case"))
async def cmd_case(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        user = UserRepo(db).get_or_create(
            message.from_user.id,
            message.from_user.full_name if message.from_user else None,
        )
        args = (command.args or "").strip().lower()
        if args in CASE_LEVELS:
            _set_case_level(user, args)
            db.commit()
            ProductAnalyticsService(db).track(user_id=user.id, event_name="case_difficulty_selected", properties={"level": args, "source": "command"})
            await message.answer(f"Уровень кейсов: {args}. Выбирай кейс:", reply_markup=_case_select_keyboard(args))
            return
        if args:
            # Direct selection by id
            case = get_case_by_id(args)
            if not case:
                await message.answer(f"Кейс '{args}' не найден. Используй /case без аргументов для списка.")
                return
            _set_user_case_id(user, case["id"])
            db.commit()
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="case_started",
                properties={"case_id": case["id"], "case_title": case["title"], "difficulty": _case_level_for_case(case["id"]), "selected_level": _get_case_level(user)},
            )
            _complete_onboarding_step(user=user, step="first_case", analytics=ProductAnalyticsService(db))
            text = (
                f"<b>{case['title']}</b>\n\n"
                f"{case['description']}"
                f"{CASE_EDUCATIONAL_DISCLAIMER}\n\n"
                "📝 Напиши свой анализ кейса в следующем сообщении, затем отправь /case_answer."
            )
            await _answer_telegram_html(message, text, reply_markup=_case_answer_keyboard(case["id"]))
        else:
            await message.answer(
                f"Выбери уровень и кейс (текущий уровень: {_get_case_level(user)}):",
                reply_markup=_case_level_keyboard(),
            )
    finally:
        db.close()


@router.message(Command("case_answer"))
async def cmd_case_answer(message: Message):
    """Submit the student's analysis of the current case for Socratic evaluation."""
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        user = UserRepo(db).get_or_create(
            message.from_user.id,
            message.from_user.full_name if message.from_user else None,
        )
        case_id = _get_user_case_id(user)
        if not case_id:
            await message.answer(
                "Нет активного кейса. Выбери кейс через /case сначала."
            )
            return
        case = get_case_by_id(case_id)
        if not case:
            _set_user_case_id(user, None)
            db.commit()
            await message.answer("Активный кейс не найден. Выбери кейс через /case.")
            return
        # Get the student's answer from the message text (strip the command prefix)
        raw = (message.text or "").strip()
        student_answer = raw.removeprefix("/case_answer").strip()
        if not student_answer:
            await message.answer(
                "Напиши свой анализ после команды, например:\n"
                "<code>/case_answer Я запрошу ОАК, биохимию, рентген. Мои дифференциалы: ...</code>",
                parse_mode=TELEGRAM_HTML_PARSE_MODE,
            )
            return

        await _send_typing(message)
        quota = QuotaGuard(get_settings()).check_user_and_global(db, user)
        if not quota.allowed:
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="journey_drop_detected",
                properties={"reason": "case_quota_block", "stage": _infer_journey_state(user)},
            )
            await message.answer(_quota_error_text(), reply_markup=_next_step_keyboard("quota"))
            return

        prompt = prompt_manager.build_case_eval(
            case_title=case["title"],
            case_description=case["description"],
            rubric=case["rubric"],
            student_answer=student_answer,
        )
        ProductAnalyticsService(db).track(
            user_id=user.id,
            event_name="case_submitted",
            properties={"case_id": case_id, "answer_len": len(student_answer), "difficulty": _case_level_for_case(case_id), "selected_level": _get_case_level(user)},
        )
        answer = await llm_router.generate(db, user.id, prompt, purpose="case_eval")
        next_level, progress = _apply_case_progression(user, _case_level_for_case(case_id))
        ProductAnalyticsService(db).track(
            user_id=user.id,
            event_name="case_progression_updated",
            properties={"submitted_level": _case_level_for_case(case_id), "next_level": next_level, "completed": progress.get("completed", {})},
        )

        # Save to session if possible
        topic = TopicRepo(db).get_by_chat_thread(message.chat.id, message.message_thread_id)
        if topic and topic.subject_id:
            chat_db = ChatDBService(db)
            session = SessionRepo(db).get_active(user.id, topic.id) or SessionRepo(db).new_active(user.id, topic.id, mode="practical")
            chat_db.save_user_message(session.id, f"/case_answer {student_answer}", message.message_id)
            assistant_msg = chat_db.save_assistant_message(session.id, answer, metadata={"case_id": case_id, "topic_id": str(topic.id)})
            memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
            await _try_ingest_answer(
                memory,
                db=db,
                user_id=user.id,
                topic_id=topic.id,
                source_message_id=assistant_msg.id,
                answer=answer,
                title=f"Разбор: {case['title']}",
                kind="answer",
            )

        # Clear active case after submission
        _set_user_case_id(user, None)
        db.commit()

        fb_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="👍", callback_data=_callback_data("case_fb", "up")),
                    InlineKeyboardButton(text="👎", callback_data=_callback_data("case_fb", "down")),
                ],
                [
                    InlineKeyboardButton(text="🔄 Ещё кейс", callback_data=_callback_data("case_list", "")),
                    InlineKeyboardButton(text="🧠 Сделать карточки", callback_data=_callback_data("cards")),
                ],
            ]
        )
        await _send_ai_answer(message, answer, with_keyboard=False)
        if message.answers:  # type: ignore[attr-defined]
            pass
        try:
            await message.answer(
                "⚠️ <i>Это учебная обратная связь, а не клиническое заключение. "
                f"Для реального животного — очная консультация ветеринара.</i>\nСледующий уровень: <b>{next_level}</b>",
                parse_mode=TELEGRAM_HTML_PARSE_MODE,
                reply_markup=fb_keyboard,
            )
        except Exception:
            pass
    except RuntimeError:
        ErrorEventRepo(db).add(
            user_id=user.id,
            scope="telegram",
            category="case_eval_provider_error",
            details={"case_id": case_id},
        )
        ProductAnalyticsService(db).track(
            user_id=user.id,
            event_name="journey_drop_detected",
            properties={"reason": "case_provider_error", "stage": _infer_journey_state(user)},
        )
        await message.answer(_provider_error_text(), reply_markup=_next_step_keyboard("provider"))
    except Exception as exc:
        mapped = map_pipeline_error(exc)
        if mapped.category == "quota_error":
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="journey_drop_detected",
                properties={"reason": "case_quota_error", "stage": _infer_journey_state(user)},
            )
            await message.answer(_quota_error_text(), reply_markup=_next_step_keyboard("quota"))
        else:
            ErrorEventRepo(db).add(
                user_id=user.id,
                scope="telegram",
                category="case_eval_unexpected_error",
                details={"case_id": case_id, "error": str(exc)},
            )
            await message.answer("Временная ошибка кейса. Следующий шаг: сократите ответ до ключевых пунктов и повторите /case_answer.")
    finally:
        db.close()



@router.message(Command("export"))
async def cmd_export(message: Message, command: CommandObject):
    if await _deny_if_not_allowed(message):
        return
    export_type = (command.args or "").strip().lower()
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        learning = LearningService()
        cards = FlashcardRepo(db).by_user(user.id, limit=1000)
        if export_type == "anki":
            content = learning.export_anki_csv(cards)
            file = BufferedInputFile(content.encode("utf-8"), filename="vetstudy_cards.csv")
            await message.answer_document(file, caption="Anki CSV export")
            return
        if export_type == "markdown":
            notes = MemoryRepo(db).by_topic(topic.id, limit=200)
            saved_notes = [x.content for x in notes if x.kind == "note"]
            summary_item = MemoryRepo(db).latest_by_kind(topic_id=topic.id, kind="summary")
            markdown = learning.export_markdown(
                topic_title=topic.title,
                topic_summary=(summary_item.content if summary_item else topic.summary or ""),
                saved_notes=saved_notes,
                cards=[x for x in cards if x.topic_id == topic.id],
            )
            file = BufferedInputFile(markdown.encode("utf-8"), filename="vetstudy_topic_export.md")
            await message.answer_document(file, caption="Markdown export")
            return
        await message.answer("Использование: /export anki или /export markdown")
    finally:
        db.close()


@router.callback_query(F.data.startswith("vx:"))
async def on_ai_action(query: CallbackQuery):
    parsed = parse_callback_data(query.data or "")
    if not parsed:
        await query.answer("Неизвестное действие.", show_alert=False)
        return
    if await _deny_callback_if_not_allowed(query):
        return
    await query.answer()
    if parsed.action == "pick":
        db = new_session()
        try:
            chat_db = ChatDBService(db)
            user = chat_db.ensure_user(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            settings = dict(user.settings or {})
            picked = MemoryRepo(db).get(UUID(parsed.payload))
            if not picked or picked.user_id != user.id:
                if query.message:
                    await query.message.answer("Нельзя выбрать чужой или несуществующий фрагмент.")
                return
            settings["selected_memory_id"] = parsed.payload
            user.settings = settings
            db.commit()
        finally:
            db.close()
        if query.message:
            await query.message.answer("Результат поиска выбран для /cards search.")
        return
    if parsed.action in {"review_again", "review_hard", "review_good", "review_easy", "review_reveal"}:
        db = new_session()
        try:
            chat_db = ChatDBService(db)
            user = chat_db.ensure_user(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            card = FlashcardRepo(db).get(UUID(parsed.payload))
            if not card or card.user_id != user.id:
                if query.message:
                    await query.message.answer("Карточка не найдена или недоступна.")
                return
            if parsed.action == "review_reveal":
                ReviewEventRepo(db).add(user_id=user.id, topic_id=card.topic_id, flashcard_id=card.id, event_type="reveal", score=None, metadata_={})
                ProductAnalyticsService(db).track(user_id=user.id, topic_id=card.topic_id, event_name="cards_review_reveal")
                if query.message:
                    await query.message.answer(f"Ответ:\n{card.back}", reply_markup=_build_review_keyboard(str(card.id)))
                return
            action = {"review_again": "again", "review_hard": "hard", "review_good": "good", "review_easy": "easy"}[parsed.action]
            updated, score = LearningService().apply_review(card=card, action=action)
            updated = FlashcardRepo(db).save(updated)
            ReviewEventRepo(db).add(user_id=user.id, topic_id=card.topic_id, flashcard_id=card.id, event_type=action, score=score, metadata_={"due_at": updated.due_at.isoformat() if updated.due_at else None})
            ProductAnalyticsService(db).track(
                user_id=user.id,
                topic_id=card.topic_id,
                event_name="cards_reviewed",
                properties={"action": action, "score": score},
            )
            ProductAnalyticsService(db).track(user_id=user.id, topic_id=card.topic_id, event_name="activation_first_review")
            if query.message:
                await query.message.answer(
                    f"Ок. Следующий повтор: {updated.due_at.date().isoformat()} (interval={updated.interval_days}, ease={float(updated.ease):.2f})",
                )
        finally:
            db.close()
        return
    # ── Case callbacks ──────────────────────────────────────────────────────
    if parsed.action == "case_select":
        case_id = parsed.payload
        case = get_case_by_id(case_id)
        if not case:
            if query.message:
                await query.message.answer("Кейс не найден.")
            return
        db = new_session()
        try:
            user = UserRepo(db).get_or_create(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            _set_user_case_id(user, case["id"])
            db.commit()
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="case_started",
                properties={"case_id": case["id"], "case_title": case["title"], "difficulty": _case_level_for_case(case["id"]), "selected_level": _get_case_level(user)},
            )
            _complete_onboarding_step(user=user, step="first_case", analytics=ProductAnalyticsService(db))
        finally:
            db.close()
        if query.message:
            text = (
                f"<b>{case['title']}</b>\n\n"
                f"{case['description']}"
                f"{CASE_EDUCATIONAL_DISCLAIMER}\n\n"
                "📝 Напиши свой анализ кейса, затем отправь /case_answer."
            )
            try:
                await query.message.edit_text(text, parse_mode=TELEGRAM_HTML_PARSE_MODE,
                                              reply_markup=_case_answer_keyboard(case["id"]))
            except Exception:
                await query.message.answer(text, parse_mode=TELEGRAM_HTML_PARSE_MODE,
                                           reply_markup=_case_answer_keyboard(case["id"]))
        return
    if parsed.action == "case_level":
        level = parsed.payload if parsed.payload in CASE_LEVELS else "basic"
        db = new_session()
        try:
            user = UserRepo(db).get_or_create(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            _set_case_level(user, level)
            db.commit()
            ProductAnalyticsService(db).track(user_id=user.id, event_name="case_difficulty_selected", properties={"level": level, "source": "callback"})
        finally:
            db.close()
        if query.message:
            await query.message.answer(f"Уровень: {level}. Выбери кейс:", reply_markup=_case_select_keyboard(level))
        return
    if parsed.action == "case_list":
        if query.message:
            level = "basic"
            db = new_session()
            try:
                user = UserRepo(db).get_or_create(
                    query.from_user.id,
                    query.from_user.full_name if query.from_user else None,
                )
                level = _get_case_level(user)
            finally:
                db.close()
            try:
                await query.message.edit_text(f"Выбери учебный кейс ({level}):", reply_markup=_case_select_keyboard(level))
            except Exception:
                await query.message.answer(f"Выбери учебный кейс ({level}):", reply_markup=_case_select_keyboard(level))
        return
    if parsed.action == "case_fb":
        db = new_session()
        try:
            user = UserRepo(db).get_or_create(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            ProductAnalyticsService(db).track(
                user_id=user.id,
                event_name="case_feedback",
                properties={"sentiment": parsed.payload},  # "up" or "down"
            )
        finally:
            db.close()
        if query.message:
            await query.message.answer("Спасибо за обратную связь! Используй /case для следующего кейса.")
        return
    if parsed.action == "clarify_quick":
        if not query.message:
            return
        templates = {
            "patient": "Заполни: вид= ; вес_кг= ; возраст= ; пол/стерилизация= .",
            "drug": "Заполни: препарат= ; концентрация= ; маршрут= ; частота= ; источник(label/SPC/formulary)= .",
            "timeline": "Заполни: ключевые симптомы= ; длительность= ; динамика= ; red_flags= .",
        }
        text = templates.get(parsed.payload, "Добавьте минимальные клинические данные: вид, вес, возраст, симптомы, препарат.")
        await query.message.answer(text)
        return
    # ── General feedback ────────────────────────────────────────────────────
    if parsed.action in {"fb_up", "fb_down", "fb_error"}:
        if not query.message:
            return
        db = new_session()
        try:
            chat_db = ChatDBService(db)
            user = chat_db.ensure_user(query.from_user.id, query.from_user.full_name if query.from_user else None)
            topic = chat_db.get_topic_for_chat_thread(query.message.chat.id, query.message.message_thread_id)
            session = SessionRepo(db).get_active(user.id, topic.id) if topic else None
            last = MessageRepo(db).last_assistant(session.id) if session else None
            FeedbackEventRepo(db).add(
                user_id=user.id,
                topic_id=(topic.id if topic else None),
                message_id=(last.id if last else None),
                source_message_id=(last.id if last else None),
                model=((last.metadata_ or {}).get("model") if last else None),
                feedback_type={"fb_up": "up", "fb_down": "down", "fb_error": "error"}[parsed.action],
                details=None,
                status="new",
                metadata_={
                    "provider": (last.metadata_ or {}).get("provider") if last else None,
                    "mode": (last.metadata_ or {}).get("effective_mode") if last else None,
                },
            )
            ProductAnalyticsService(db).track(
                user_id=user.id,
                topic_id=(topic.id if topic else None),
                event_name="feedback_submitted",
                properties={"type": {"fb_up": "up", "fb_down": "down", "fb_error": "error"}[parsed.action]},
            )
            await query.message.answer("Спасибо, feedback сохранен.")
        finally:
            db.close()
        return
    if parsed.action in {"save", "cards", "test", "related", "short", "deeper"}:
        if not query.message:
            return
        db = new_session()
        try:
            chat_db = ChatDBService(db)
            user = chat_db.ensure_user(
                query.from_user.id,
                query.from_user.full_name if query.from_user else None,
            )
            topic = chat_db.get_topic_for_chat_thread(query.message.chat.id, query.message.message_thread_id)
            if not topic or not topic.subject_id:
                await query.message.answer(_topic_required_text(query.message.message_thread_id))
                return
            session = SessionRepo(db).get_active(user.id, topic.id)
            if not session:
                await query.message.answer("Нет активной сессии.")
                return
            last = MessageRepo(db).last_assistant(session.id)
            if not last:
                await query.message.answer("Нет последнего ответа для действия.")
                return

            if parsed.action == "save":
                MemoryRepo(db).add(user_id=user.id, topic_id=topic.id, source_message_id=last.id, kind="note", title="Сохранено из кнопки", content=last.content)
                await query.message.answer("Сохранено.")
                return

            if parsed.action == "cards":
                raw_cards = await LearningService().generate_cards_structured(
                    llm_router=llm_router,
                    db=db,
                    user_id=user.id,
                    text=last.content,
                    count=6,
                    tags=["cards", "answer"],
                    source_message_id=str(last.id),
                )
                cards = [Flashcard(user_id=user.id, topic_id=topic.id, source_message_id=last.id, front=x["front"], back=x["back"], card_type=x.get("card_type", "fact"), needs_manual_check=x.get("needs_manual_check", False), tags=x.get("tags", []), due_at=datetime.now(UTC), ease=2.5, interval_days=1) for x in raw_cards]
                if not cards:
                    await query.message.answer("Не удалось собрать валидные карточки.")
                    return
                FlashcardRepo(db).add_many(cards)
                ProductAnalyticsService(db).track(
                    user_id=user.id,
                    topic_id=topic.id,
                    event_name="cards_created",
                    properties={"count": len(cards), "source": "inline"},
                )
                await query.message.answer(f"Сгенерировано карточек: {len(cards)}")
                return

            if parsed.action == "test":
                items = await LearningService().generate_quiz_structured(llm_router=llm_router, db=db, user_id=user.id, text=last.content, count=5)
                lines = ["Тест:"]
                for item in items:
                    lines.append(item.question)
                    lines.extend(item.options)
                    lines.append(f"Ответ: {item.correct_answer}")
                    lines.append(f"Пояснение: {item.explanation}")
                    lines.append("")
                await query.message.answer("\n".join(lines).strip())
                return

            if parsed.action == "related":
                memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
                topics = await memory.related_topics(db=db, user_id=user.id, current_topic_id=topic.id, top_k=5)
                if not topics:
                    await query.message.answer("Связанные темы пока не найдены.")
                    return
                lines = ["Связанные темы:"]
                for item in topics:
                    thread = f"thread={item.telegram_thread_id}" if item.telegram_thread_id else "без thread"
                    lines.append(f"- {item.title} ({thread})")
                await query.message.answer("\n".join(lines))
                return

            mode = "short" if parsed.action == "short" else "deep"
            subject = SubjectRepo(db).get_by_id(topic.subject_id)
            history_rows = MessageRepo(db).recent_for_session(session.id, limit=6)
            prompt = prompt_manager.build(
                mode=mode,
                subject=subject.slug if subject else "general",
                user_message=f"Переработай последний ответ в режиме {mode}:\n\n{last.content}",
                memory_chunks=[],
                session_history=[f"{row.role}: {row.content[:200]}" for row in history_rows],
                safety_warning=None,
            )
            answer = await llm_router.generate(db, user.id, prompt, purpose="answer", metadata={"inline_action": parsed.action})
            assistant_msg = chat_db.save_assistant_message(session.id, answer, metadata={"topic_id": str(topic.id), "inline_action": parsed.action})
            memory = MemoryService(MemoryRepo(db), topic_repo=TopicRepo(db), embedder=llm_router, chunk_repo=DocumentChunkRepo(db))
            await _send_ai_answer(query.message, answer)
            await _try_ingest_answer(
                memory,
                db=db,
                user_id=user.id,
                topic_id=topic.id,
                source_message_id=assistant_msg.id,
                answer=answer,
                title=f"Inline {parsed.action}",
                kind="answer",
            )
        finally:
            db.close()
        return
    if query.message:
        await query.message.answer("Действие не распознано.")


@router.message(F.text)
async def on_text(message: Message):
    if await _deny_if_not_allowed(message):
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
    finally:
        db.close()
    await _run_text_pipeline(message, user, topic, message.text or "")


@router.message(F.voice | F.audio)
async def on_voice(message: Message):
    if await _deny_if_not_allowed(message):
        return
    settings = get_settings()
    media = message.voice or message.audio
    if not media:
        return
    try:
        stored = await download_telegram_file(
            bot=message.bot,
            telegram_file_id=media.file_id,
            file_name=getattr(media, "file_name", None) or "voice.ogg",
            size_bytes=getattr(media, "file_size", 0) or 0,
            max_size_bytes=settings.max_voice_file_size_bytes,
            content_type="audio/ogg",
        )
    except FileTooLargeError:
        await message.answer("Аудио слишком большое. Отправьте файл поменьше.")
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        transcript = await llm_router.transcribe(db, user.id, Path(stored.path).read_bytes(), stored.original_name)
    finally:
        db.close()
    if not transcript:
        await message.answer("Не удалось распознать аудио: провайдер transcription не настроен или временно недоступен.")
        return
    await message.answer(f"Транскрипт: {transcript}")
    await message.answer(
        "Structured summary:\n"
        f"- source: voice ({stored.original_name})\n"
        f"- key point: {transcript[:180]}\n"
        "- next action: уточни клинический контекст или перейди к тренировке\n"
        "Actions: /cards | /quiz | /save"
    )
    db = new_session()
    try:
        ProductAnalyticsService(db).track(
            user_id=user.id,
            topic_id=topic.id,
            event_name="voice_summary_offered",
            properties={"file_name": stored.original_name},
        )
    finally:
        db.close()
    await _run_text_pipeline(message, user, topic, transcript, metadata={"source_type": "voice", "file_name": stored.original_name})


@router.message(F.photo | F.document)
async def on_image_or_document(message: Message):
    if await _deny_if_not_allowed(message):
        return
    settings = get_settings()
    doc = message.document
    is_photo = bool(message.photo)
    is_image_doc = bool(doc and (doc.mime_type or "").startswith("image/"))
    if not (is_photo or doc):
        return
    if is_photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        size = photo.file_size or 0
        filename = "photo.jpg"
        max_size = settings.max_image_file_size_bytes
    else:
        file_id = doc.file_id
        size = doc.file_size or 0
        filename = doc.file_name or "upload.bin"
        max_size = settings.max_image_file_size_bytes if is_image_doc else settings.max_document_file_size_bytes
    try:
        stored = await download_telegram_file(bot=message.bot, telegram_file_id=file_id, file_name=filename, size_bytes=size, max_size_bytes=max_size, content_type="application/octet-stream")
    except FileTooLargeError:
        await message.answer("Файл слишком большой для обработки.")
        return

    if is_photo or is_image_doc:
        db = new_session()
        try:
            user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
            data = Path(stored.path).read_bytes()
            ocr_text = await llm_router.ocr(db, user.id, data, stored.original_name) if settings.multimodal_ocr_enabled else ""
            vision_text = await llm_router.vision_describe(db, user.id, data, stored.original_name) if settings.multimodal_vision_enabled else ""
        finally:
            db.close()
        warn = "Внимание: OCR и анализ фото могут содержать ошибки."
        parts = [warn]
        if ocr_text:
            parts.append(f"OCR: {ocr_text[:800]}")
        if vision_text:
            parts.append(f"Vision: {vision_text[:800]}")
        if not ocr_text and not vision_text:
            parts.append("Невозможно обработать изображение: OCR/Vision провайдеры отключены или недоступны.")
        else:
            parts.append(
                "Structured summary:\n"
                f"- source: image ({stored.original_name})\n"
                f"- extracted: {(ocr_text or vision_text)[:180]}\n"
                "- next action: проверь контекст и выбери учебный формат\n"
                "Actions: /cards | /quiz | /save"
            )
        await message.answer("\n\n".join(parts))
        if ocr_text or vision_text:
            db = new_session()
            try:
                user = UserRepo(db).get_or_create(message.from_user.id, message.from_user.full_name if message.from_user else None)
                ProductAnalyticsService(db).track(
                    user_id=user.id,
                    event_name="voice_or_image_summary_offered",
                    properties={"source_type": "photo" if is_photo else "image_document"},
                )
            finally:
                db.close()
        return

    allowed_ext = {".pdf", ".docx", ".txt", ".md"}
    if Path(stored.original_name).suffix.lower() not in allowed_ext:
        await message.answer("Неподдерживаемый документ. Разрешены: PDF/DOCX/TXT/MD.")
        return
    db = new_session()
    try:
        chat_db = ChatDBService(db)
        user = chat_db.ensure_user(message.from_user.id, message.from_user.full_name if message.from_user else None)
        topic = chat_db.get_topic_for_chat_thread(message.chat.id, message.message_thread_id)
        if not topic or not topic.subject_id:
            await message.answer(_topic_required_text(message.message_thread_id))
            return
        user_id = user.id
        topic_id = topic.id
        telegram_user_id = message.from_user.id
        display_name = message.from_user.full_name if message.from_user else None
        job_id = str(uuid4())
        DocumentRepo(db).create_or_get(
            user_id=user.id,
            topic_id=topic.id,
            filename=stored.original_name,
            size_bytes=stored.size_bytes,
            job_id=job_id,
            metadata={"source": "telegram_upload", "stored_path": str(stored.path)},
        )
        docs = list((user.settings or {}).get("documents", []))
        docs.append({"job_id": job_id, "filename": stored.original_name, "size_bytes": stored.size_bytes, "status": "queued", "topic_id": str(topic.id)})
        user.settings = {**(user.settings or {}), "documents": docs[-100:]}  # backward-compatible shadow copy
        db.commit()
    finally:
        db.close()

    try:
        await enqueue_document_index(
            DocumentIndexJob(
                job_id=job_id,
                stored_path=str(stored.path),
                original_name=stored.original_name,
                user_id=str(user_id),
                topic_id=str(topic_id),
                telegram_user_id=telegram_user_id,
                display_name=display_name,
            )
        )
    except Exception as exc:
        logger.exception("document_enqueue_failed", extra={"event": "document_enqueue_failed", "error_category": "media_error"})
        db = new_session()
        try:
            _update_document_status(
                db,
                telegram_user_id=telegram_user_id,
                display_name=display_name,
                filename=stored.original_name,
                status="failed",
                job_id=job_id,
                error=exc.__class__.__name__,
            )
            ErrorEventRepo(db).add(
                user_id=user_id,
                scope="media",
                category="document_index_failed",
                details={"filename": stored.original_name, "error": str(exc), "kind": exc.__class__.__name__, "stage": "enqueue"},
            )
        finally:
            db.close()
        await message.answer("Не удалось поставить документ в очередь. Попробуйте позже.")
        return

    await message.answer("Документ принят. Индексация поставлена в очередь.")
