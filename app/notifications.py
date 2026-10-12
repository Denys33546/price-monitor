"""Price-drop alerts sent through Telegram."""

import html
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from app.bot import format_price
from app.db import Database
from app.scheduler import PriceChange

logger = logging.getLogger(__name__)


def should_notify(change: PriceChange) -> bool:
    """Alert on a price drop; if the user set a target, only once it is reached."""
    if change.old_price is None or change.new_price >= change.old_price:
        return False
    target = change.product.target_price
    return target is None or change.new_price <= target


def format_alert(change: PriceChange) -> str:
    """Build the HTML message for a price drop (old_price must not be None)."""
    product = change.product
    old, new = change.old_price, change.new_price
    drop_percent = (old - new) / old * 100
    lines = [
        "<b>Price drop!</b>",
        html.escape(product.title),
        f"{format_price(old)} → {format_price(new)} (-{drop_percent:.1f}%)",
    ]
    if product.target_price is not None:
        lines.append(f"Your target price {format_price(product.target_price)} is reached")
    lines.append(html.escape(product.url))
    return "\n".join(lines)


def make_notifier(bot: Bot, db: Database) -> Callable[[PriceChange], Awaitable[None]]:
    """Return the callback that the scheduler calls for every price change."""

    async def notify(change: PriceChange) -> None:
        if not should_notify(change):
            return
        chat_id = change.product.chat_id
        try:
            await bot.send_message(chat_id, format_alert(change))
        except TelegramForbiddenError:
            # The user blocked the bot: stop checking prices nobody will read.
            removed = db.remove_all(chat_id)
            logger.info("Chat %s blocked the bot, removed %s product(s)", chat_id, removed)
        except TelegramAPIError:
            logger.exception("Could not send alert to chat %s", chat_id)

    return notify
