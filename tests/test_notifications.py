import asyncio

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.methods import SendMessage

from app.db import Database
from app.notifications import format_alert, make_notifier, should_notify
from app.scheduler import PriceChange, run_periodically
from app.scraper import Product


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


def make_change(db, old, new, target=None, title="Book", chat_id=1):
    url = f"https://books.toscrape.com/{old}-{new}-{target}-{chat_id}"
    db.add_product(chat_id, url, title, old, target_price=target)
    product = db.list_products(chat_id)[-1]
    return PriceChange(product=product, old_price=old, new_price=new)


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        if self.error:
            raise self.error
        self.sent.append((chat_id, text))


def api_error(cls):
    return cls(method=SendMessage(chat_id=1, text="x"), message="boom")


# ---------- should_notify ----------

def test_notify_on_any_drop_without_target(db):
    assert should_notify(make_change(db, 50.0, 49.0)) is True


def test_no_notify_on_price_increase(db):
    assert should_notify(make_change(db, 50.0, 60.0)) is False


def test_no_notify_when_drop_is_still_above_target(db):
    assert should_notify(make_change(db, 50.0, 45.0, target=40.0)) is False


def test_notify_when_target_reached(db):
    assert should_notify(make_change(db, 50.0, 39.0, target=40.0)) is True


def test_notify_when_price_equals_target(db):
    assert should_notify(make_change(db, 50.0, 40.0, target=40.0)) is True


def test_no_notify_without_previous_price(db):
    change = make_change(db, 50.0, 40.0)
    assert should_notify(PriceChange(change.product, None, 40.0)) is False


# ---------- format_alert ----------

def test_format_alert_content(db):
    text = format_alert(make_change(db, 50.0, 40.0, target=42.0, title="Tom & <Jerry>"))
    assert "Price drop!" in text
    assert "Tom &amp; &lt;Jerry&gt;" in text
    assert "£50.00 → £40.00 (-20.0%)" in text
    assert "target price £42.00 is reached" in text
    assert "https://books.toscrape.com/" in text


def test_format_alert_has_no_raw_angle_brackets_in_text(db):
    text = format_alert(make_change(db, 50.0, 40.0))
    body = text.replace("<b>", "").replace("</b>", "")
    assert "<" not in body and ">" not in body  # Telegram HTML mode needs them escaped


# ---------- notifier ----------

def test_notifier_sends_alert(db):
    bot = FakeBot()
    change = make_change(db, 50.0, 40.0, chat_id=7)
    asyncio.run(make_notifier(bot, db)(change))
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 7
    assert "Price drop!" in bot.sent[0][1]


def test_notifier_stays_silent_without_drop(db):
    bot = FakeBot()
    asyncio.run(make_notifier(bot, db)(make_change(db, 50.0, 55.0)))
    assert bot.sent == []


def test_notifier_removes_products_of_user_who_blocked_bot(db):
    change = make_change(db, 50.0, 40.0, chat_id=1)
    make_change(db, 20.0, 10.0, chat_id=1)
    make_change(db, 30.0, 20.0, chat_id=2)
    bot = FakeBot(error=api_error(TelegramForbiddenError))
    asyncio.run(make_notifier(bot, db)(change))
    assert db.list_products(1) == []
    assert len(db.list_products(2)) == 1


def test_notifier_survives_other_telegram_errors(db):
    change = make_change(db, 50.0, 40.0)
    bot = FakeBot(error=api_error(TelegramAPIError))
    asyncio.run(make_notifier(bot, db)(change))  # must not raise
    assert len(db.list_products(1)) == 1


# ---------- scheduler + notifier together ----------

def test_full_flow_price_check_to_telegram_message(db):
    db.add_product(5, "https://books.toscrape.com/x", "Flow Book", 99.0, target_price=45.0)
    bot = FakeBot()
    notifier = make_notifier(bot, db)

    def fetch(url):
        return Product(url, "Flow Book", 39.99)

    asyncio.run(run_periodically(db, 0, notifier, fetch=fetch, delay=0, max_runs=1))
    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == 5
    assert "£99.00 → £39.99" in text


def test_remove_all_helper_is_used_via_db(db):
    db.add_product(1, "https://books.toscrape.com/a", "A", 1.0)
    db.add_product(1, "https://books.toscrape.com/b", "B", 1.0)
    assert db.remove_all(1) == 2
    assert db.remove_all(1) == 0