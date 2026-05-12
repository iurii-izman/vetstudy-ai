from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.config import get_settings


def check_allow(message: Message) -> bool:
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


async def deny_if_not_allowed(message: Message) -> bool:
    if check_allow(message):
        return False
    user_id = getattr(getattr(message, "from_user", None), "id", "unknown")
    await message.answer(f"Доступ запрещен. Ваш Telegram ID: {user_id}. Передайте его владельцу beta для allowlist.")
    return True


async def deny_callback_if_not_allowed(query: CallbackQuery) -> bool:
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
