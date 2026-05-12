from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.config import get_settings
from app.telegram.handlers import router

dp = Dispatcher()
dp.include_router(router)


BOT_COMMANDS = [
    BotCommand(command="start", description="Проверить, что бот доступен"),
    BotCommand(command="help", description="Список команд"),
    BotCommand(command="status", description="Диагностика бота и текущего topic"),
    BotCommand(command="topics", description="Показать привязку topic"),
    BotCommand(command="bind_topic", description="Привязать topic к предмету"),
    BotCommand(command="create_default_topics", description="Создать стандартные topics"),
    BotCommand(command="new", description="Начать новую сессию"),
    BotCommand(command="mode", description="Выбрать режим ответа"),
    BotCommand(command="evidence", description="Строгий режим доказательности"),
    BotCommand(command="profile", description="Настройки региона и профиля"),
    BotCommand(command="case", description="Виртуальные клинические кейсы"),
    BotCommand(command="case_answer", description="Отправить анализ кейса"),
    BotCommand(command="today", description="Дневной учебный маршрут"),
    BotCommand(command="plan_week", description="Персональный план на 7 дней"),
    BotCommand(command="cards", description="Сгенерировать карточки"),
    BotCommand(command="quiz", description="Сгенерировать тест"),
    BotCommand(command="review", description="Повторить карточки"),
    BotCommand(command="search", description="Поиск по памяти"),
    BotCommand(command="save", description="Сохранить последний ответ как заметку"),
    BotCommand(command="summary", description="Сводка по topic"),
    BotCommand(command="docs", description="Статус загруженных документов"),
    BotCommand(command="export", description="Экспорт Anki/Markdown"),
]

def get_bot() -> Bot:
    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram bot operations.")
    return Bot(token=token)

async def setup_bot_commands(bot: Bot):
    await bot.set_my_commands(BOT_COMMANDS)
