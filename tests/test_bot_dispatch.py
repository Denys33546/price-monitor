"""Runs real aiogram routing (command filter + dependency injection) without Telegram."""

import asyncio
import datetime
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, MessageEntity, Update, User

from app import bot as bot_module
from app.db import Database


def make_update(text: str) -> Update:
    command_length = len(text.split()[0])
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="Test"),
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=command_length)],
        ),
    )


def test_dispatcher_routes_command_and_injects_db():
    db = Database(":memory:")
    db.add_product(1, "https://books.toscrape.com/x", "Routed Book", 9.99)

    bot = Bot(token="123456:TEST")
    bot.session.make_request = AsyncMock(return_value=None)  # no real network
    dp = Dispatcher(db=db)
    dp.include_router(bot_module.router)

    asyncio.run(dp.feed_update(bot, make_update("/list")))

    method = bot.session.make_request.call_args.args[1]
    assert method.__class__.__name__ == "SendMessage"
    assert "Routed Book" in method.text
    db.close()
