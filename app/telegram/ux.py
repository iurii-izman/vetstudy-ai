from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.telegram.callbacks import callback_data


def topic_required_text(thread_id: int | None) -> str:
    return (
        f"Текущий thread id: {thread_id}\n"
        "Этот Telegram topic пока не привязан к учебной теме.\n"
        "Используйте: /bind_topic <slug_or_name>\n"
        "Быстрый старт: /create_default_topics"
    )


def provider_error_text() -> str:
    return "Провайдер временно недоступен. Следующий шаг: проверьте /status и повторите через 1-2 минуты."


def quota_error_text() -> str:
    return "Лимит запросов/бюджета исчерпан. Следующий шаг: переключитесь на /review или /today и попробуйте снова после обновления лимита."


def safety_error_text() -> str:
    return "Для безопасного ответа не хватает данных. Следующий шаг: укажите вид, вес, возраст, симптомы и точный препарат/ситуацию."


def minimal_next_questions(*, safety=None, evidence_payload: dict | None = None, limit: int = 3) -> list[str]:
    items: list[str] = []
    for question in list(getattr(safety, "clarifying_questions", []) or []):
        cleaned = str(question).strip()
        if cleaned:
            items.append(cleaned)
    for question in list((evidence_payload or {}).get("next_questions", []) or []):
        cleaned = str(question).strip()
        if cleaned:
            items.append(cleaned)
    if not items:
        items = [
            "Уточните вид, вес, возраст и ключевые симптомы.",
            "Уточните точный препарат/концентрацию/маршрут.",
        ]
    seen: set[str] = set()
    deduped: list[str] = []
    for question in items:
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(question)
    return deduped[:limit]


def guided_clarification_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⚖️ Вид/вес/возраст", callback_data=callback_data("clarify_quick", "patient")),
            InlineKeyboardButton(text="💊 Препарат/доза", callback_data=callback_data("clarify_quick", "drug")),
        ],
        [InlineKeyboardButton(text="🧪 Симптомы/таймлайн", callback_data=callback_data("clarify_quick", "timeline"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def why_payload_for_meta(meta: dict | None) -> dict:
    payload = dict(meta or {})
    safety_meta = dict(payload.get("safety") or {})
    evidence_meta = dict(payload.get("evidence") or {})
    return {
        "risk_intent": safety_meta.get("intent"),
        "risk_tags": list(safety_meta.get("risk_tags") or []),
        "needs_manual_check": bool(evidence_meta.get("needs_manual_check")),
        "manual_check_reasons": list(evidence_meta.get("manual_check_reasons") or []),
        "missing_data": list(evidence_meta.get("next_questions") or []),
        "verification_status": evidence_meta.get("verification_status") or evidence_meta.get("status"),
    }


def next_step_keyboard(context: str) -> InlineKeyboardMarkup:
    if context == "quota":
        rows = [
            [InlineKeyboardButton(text="🔁 Повторить /review", switch_inline_query_current_chat="/review")],
            [InlineKeyboardButton(text="📅 Открыть /today", switch_inline_query_current_chat="/today light")],
        ]
    elif context == "provider":
        rows = [
            [InlineKeyboardButton(text="📊 Проверить /status", switch_inline_query_current_chat="/status")],
            [InlineKeyboardButton(text="📅 Открыть /today", switch_inline_query_current_chat="/today standard")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="🧾 Добавить клин.данные", switch_inline_query_current_chat="вид= вес= возраст= симптомы= препарат=")],
            [InlineKeyboardButton(text="🩺 Учебный кейс /case", switch_inline_query_current_chat="/case basic")],
        ]
    if context == "learning":
        rows = [
            [InlineKeyboardButton(text="🩺 Перейти в /case", switch_inline_query_current_chat="/case basic")],
            [InlineKeyboardButton(text="🔁 Перейти в /review", switch_inline_query_current_chat="/review")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
