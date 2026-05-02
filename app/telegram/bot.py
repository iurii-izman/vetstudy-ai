from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.telegram.handlers import router

dp = Dispatcher()
dp.include_router(router)


def get_bot() -> Bot:
    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram bot operations.")
    return Bot(token=token)
