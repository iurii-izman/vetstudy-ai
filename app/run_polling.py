import asyncio

from app.observability import configure_logging
from app.telegram.bot import dp, get_bot, setup_bot_commands

configure_logging()


async def main():
    bot = get_bot()
    await bot.delete_webhook(drop_pending_updates=False)
    await setup_bot_commands(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
