"""Telegram bot: commands for managing tracked products."""
import asyncio
import csv
import html
import io
import logging
import math
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, BufferedInputFile, Message

from app.config import load_settings
from app.db import Database, DuplicateProductError, TrackedProduct
from app.scraper import ScraperError, fetch_product

logger = logging.getLogger(__name__)
router = Router()

# Only these sites may be fetched. Never fetch arbitrary user-supplied URLs:
# that would let anyone make your server request internal addresses (SSRF).
ALLOWED_HOSTS = {"books.toscrape.com"}
MAX_PRODUCTS_PER_USER = 20
CURRENCY = "£"

ADD_USAGE = "Usage: /add URL [target price]"
HELP_TEXT = (
    "<b>Price Monitor</b>\n"
    "I watch product prices and tell you when they change.\n\n"
    "/add URL [target price] - start tracking a product\n"
    "/list - show tracked products\n"
    "/remove ID - stop tracking a product\n"
    "/export - download price history as CSV\n"
    "/help - show this message\n\n"
    f"Supported sites: {', '.join(sorted(ALLOWED_HOSTS))}"
)


# ---------- pure helpers (easy to test) ----------

def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Unsupported link. Supported sites: " + ", ".join(sorted(ALLOWED_HOSTS)))
    return url


def parse_add_args(args: str | None) -> tuple[str, float | None]:
    """'URL' or 'URL 40' -> (url, target_price)."""
    parts = (args or "").split()
    if not parts or len(parts) > 2:
        raise ValueError(ADD_USAGE)
    url = validate_url(parts[0])
    target = None
    if len(parts) == 2:
        try:
            target = float(parts[1].lstrip(CURRENCY).replace(",", "."))
        except ValueError:
            raise ValueError("Target price must be a number, for example 40 or 39.99") from None
        if not math.isfinite(target) or target <= 0:
            raise ValueError("Target price must be a positive number.")
    return url, target


def format_price(value: float | None) -> str:
    return "-" if value is None else f"{CURRENCY}{value:.2f}"


def format_products(products: list[TrackedProduct]) -> str:
    lines = []
    for p in products:
        target = f" (target {format_price(p.target_price)})" if p.target_price is not None else ""
        lines.append(f"<b>{p.id}</b>. {html.escape(p.title)} - {format_price(p.last_price)}{target}")
    return "\n".join(lines)


def _safe_cell(value: str) -> str:
    """Stop spreadsheet apps from treating text as a formula (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def build_csv(db: Database, products: list[TrackedProduct]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["product_id", "title", "url", "checked_at", "price"])
    for p in products:
        for checked_at, price in db.get_history(p.id):
            writer.writerow([p.id, _safe_cell(p.title), _safe_cell(p.url), checked_at, price])
    return buffer.getvalue().encode("utf-8-sig")  # BOM: Excel shows £ correctly


# ---------- handlers ----------

@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, db: Database) -> None:
    try:
        url, target = parse_add_args(command.args)
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return

    chat_id = message.chat.id
    if len(db.list_products(chat_id)) >= MAX_PRODUCTS_PER_USER:
        await message.answer(
            f"You can track up to {MAX_PRODUCTS_PER_USER} products. Remove one with /remove ID."
        )
        return

    try:
        # network call runs in a worker thread so the bot stays responsive
        scraped = await asyncio.to_thread(fetch_product, url)
    except ScraperError as exc:
        logger.warning("Cannot add %s: %s", url, exc)
        await message.answer("Could not read the price from that page. Check the link and try again.")
        return

    try:
        product_id = db.add_product(chat_id, url, scraped.title, scraped.price, target)
    except DuplicateProductError:
        await message.answer("You are already tracking this product.")
        return

    text = (
        f"Tracking <b>{html.escape(scraped.title)}</b>\n"
        f"Current price: {format_price(scraped.price)}\n"
        f"ID: {product_id}"
    )
    if target is not None:
        text += f"\nTarget price: {format_price(target)}"
    await message.answer(text)


@router.message(Command("list"))
async def cmd_list(message: Message, db: Database) -> None:
    products = db.list_products(message.chat.id)
    if not products:
        await message.answer("You are not tracking anything yet. Add a product with /add URL")
        return
    await message.answer(format_products(products))


@router.message(Command("remove"))
async def cmd_remove(message: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Usage: /remove ID (see /list)")
        return
    if db.remove_product(message.chat.id, int(arg)):
        await message.answer("Removed.")
    else:
        await message.answer("Product not found.")


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database) -> None:
    products = db.list_products(message.chat.id)
    if not products:
        await message.answer("Nothing to export yet.")
        return
    data = build_csv(db, products)
    await message.answer_document(BufferedInputFile(data, filename="price_history.csv"))


# ---------- entry point ----------

async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set. Put it in the .env file.")

    db = Database(settings.db_path)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(db=db)  # `db` is injected into handlers by parameter name
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="add", description="Track a product"),
        BotCommand(command="list", description="Show tracked products"),
        BotCommand(command="remove", description="Stop tracking a product"),
        BotCommand(command="export", description="Download price history (CSV)"),
        BotCommand(command="help", description="Help"),
    ])
    try:
        await dp.start_polling(bot)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())