import asyncio

from app.media.jobs import start_worker, stop_worker
from app.observability import configure_logging
from app.telegram.bot import dp, get_bot, setup_bot_commands

configure_logging()


async def main():
    bot = get_bot()
    await bot.delete_webhook(drop_pending_updates=False)
    await setup_bot_commands(bot)
    start_worker()
    try:
        await dp.start_polling(bot)
    finally:
        await stop_worker()


if __name__ == "__main__":
    asyncio.run(main())
