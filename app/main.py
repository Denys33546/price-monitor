"""Application entry point: Telegram bot + periodic price checks."""
import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot import router
from app.config import load_settings
from app.db import Database
from app.notifications import make_notifier
from app.scheduler import run_periodically

COMMANDS = [
    BotCommand(command="add", description="Track a product"),
    BotCommand(command="list", description="Show tracked products"),
    BotCommand(command="remove", description="Stop tracking a product"),
    BotCommand(command="export", description="Download price history (CSV)"),
    BotCommand(command="help", description="Help"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set. Put it in the .env file.")

    db = Database(settings.db_path)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(db=db)  # `db` is injected into handlers by parameter name
    dp.include_router(router)
    await bot.set_my_commands(COMMANDS)

    # price checks run in the background next to the bot
    checker = asyncio.create_task(
        run_periodically(db, settings.check_interval_minutes, make_notifier(bot, db))
    )
    try:
        await dp.start_polling(bot)
    finally:
        checker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await checker
        db.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):  # Ctrl+C is a normal way to stop
        asyncio.run(main())