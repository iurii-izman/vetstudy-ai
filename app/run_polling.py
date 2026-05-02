import asyncio

from aiogram.types import BotCommand

from app.media.jobs import start_worker, stop_worker
from app.observability import configure_logging
from app.telegram.bot import dp, get_bot

configure_logging()

BOT_COMMANDS = [
    BotCommand(command="start", description="Проверить, что бот доступен"),
    BotCommand(command="help", description="Список команд"),
    BotCommand(command="status", description="Диагностика бота и текущего topic"),
    BotCommand(command="topics", description="Показать привязку topic"),
    BotCommand(command="bind_topic", description="Привязать topic к предмету"),
    BotCommand(command="create_default_topics", description="Создать стандартные topics"),
    BotCommand(command="new", description="Начать новую сессию"),
    BotCommand(command="mode", description="Выбрать режим ответа"),
    BotCommand(command="summary", description="Сводка по topic"),
    BotCommand(command="search", description="Поиск по памяти"),
    BotCommand(command="cards", description="Сгенерировать карточки"),
    BotCommand(command="quiz", description="Сгенерировать тест"),
    BotCommand(command="review", description="Повторить карточки"),
    BotCommand(command="docs", description="Статус загруженных документов"),
    BotCommand(command="export", description="Экспорт Anki/Markdown"),
]


async def main():
    bot = get_bot()
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands(BOT_COMMANDS)
    start_worker()
    try:
        await dp.start_polling(bot)
    finally:
        await stop_worker()


if __name__ == "__main__":
    asyncio.run(main())
