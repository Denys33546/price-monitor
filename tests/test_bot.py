import asyncio
from types import SimpleNamespace

import pytest
from aiogram.filters import CommandObject

from app import bot
from app.db import Database
from app.scraper import Product, ScraperError

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


class FakeMessage:
    """Minimal stand-in for aiogram's Message."""

    def __init__(self, chat_id=1):
        self.chat = SimpleNamespace(id=chat_id)
        self.answers = []
        self.documents = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)

    async def answer_document(self, document, **kwargs):
        self.documents.append(document)


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


def run(coro):
    return asyncio.run(coro)


def args(text):
    return CommandObject(command="x", args=text)


# ---------- parse_add_args ----------

def test_parse_add_url_only():
    assert bot.parse_add_args(URL) == (URL, None)


def test_parse_add_with_target():
    assert bot.parse_add_args(f"{URL} 40.5") == (URL, 40.5)
    assert bot.parse_add_args(f"{URL} £40,5") == (URL, 40.5)


@pytest.mark.parametrize("text", [None, "", "   ", f"{URL} 1 2"])
def test_parse_add_usage_errors(text):
    with pytest.raises(ValueError):
        bot.parse_add_args(text)


@pytest.mark.parametrize("url", [
    "http://localhost:8000/admin",
    "https://evil.com/",
    "http://books.toscrape.com@evil.com/",
    "ftp://books.toscrape.com/",
    "not a url",
])
def test_validate_url_rejects_unsafe(url):
    with pytest.raises(ValueError):
        bot.validate_url(url)


@pytest.mark.parametrize("target", ["abc", "0", "-5", "inf", "nan"])
def test_parse_add_bad_target(target):
    with pytest.raises(ValueError):
        bot.parse_add_args(f"{URL} {target}")


# ---------- formatting / csv ----------

def test_format_products_escapes_html(db):
    db.add_product(1, URL, "Tom & <Jerry>", 10.0, target_price=8.0)
    text = bot.format_products(db.list_products(1))
    assert "Tom &amp; &lt;Jerry&gt;" in text
    assert "£10.00" in text and "target £8.00" in text


def test_build_csv_contains_history_and_is_safe(db):
    pid = db.add_product(1, URL, "=HYPERLINK(1)", 10.0)
    db.record_price(pid, 9.0)
    text = bot.build_csv(db, db.list_products(1)).decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "product_id,title,url,checked_at,price"
    assert len(lines) == 3
    assert "'=HYPERLINK(1)" in lines[1]


# ---------- handlers ----------

def patch_fetch(monkeypatch, price=51.77, title="A Light in the Attic"):
    monkeypatch.setattr(bot, "fetch_product", lambda url: Product(url, title, price))


def test_add_success(db, monkeypatch):
    patch_fetch(monkeypatch)
    msg = FakeMessage()
    run(bot.cmd_add(msg, args(f"{URL} 40"), db))
    assert "Tracking" in msg.answers[0] and "£51.77" in msg.answers[0]
    assert db.list_products(1)[0].target_price == 40.0


def test_add_duplicate(db, monkeypatch):
    patch_fetch(monkeypatch)
    msg = FakeMessage()
    run(bot.cmd_add(msg, args(URL), db))
    run(bot.cmd_add(msg, args(URL), db))
    assert "already tracking" in msg.answers[-1]


def test_add_bad_link_does_not_fetch(db, monkeypatch):
    def must_not_be_called(url):
        raise AssertionError("fetch_product must not be called")

    monkeypatch.setattr(bot, "fetch_product", must_not_be_called)
    msg = FakeMessage()
    run(bot.cmd_add(msg, args("http://localhost/admin"), db))
    assert "Unsupported link" in msg.answers[0]


def test_add_scraper_error(db, monkeypatch):
    def broken(url):
        raise ScraperError("down")

    monkeypatch.setattr(bot, "fetch_product", broken)
    msg = FakeMessage()
    run(bot.cmd_add(msg, args(URL), db))
    assert "Could not read the price" in msg.answers[0]
    assert db.list_products(1) == []


def test_add_limit(db, monkeypatch):
    patch_fetch(monkeypatch)
    for i in range(bot.MAX_PRODUCTS_PER_USER):
        db.add_product(1, f"https://books.toscrape.com/{i}", "B", 1.0)
    msg = FakeMessage()
    run(bot.cmd_add(msg, args(URL), db))
    assert "up to" in msg.answers[0]


def test_list_empty_and_filled(db):
    msg = FakeMessage()
    run(bot.cmd_list(msg, db))
    assert "not tracking anything" in msg.answers[0]
    db.add_product(1, URL, "Book", 5.0)
    run(bot.cmd_list(msg, db))
    assert "Book" in msg.answers[1]


def test_list_shows_only_own_products(db):
    db.add_product(2, URL, "Other user's book", 5.0)
    msg = FakeMessage(chat_id=1)
    run(bot.cmd_list(msg, db))
    assert "not tracking anything" in msg.answers[0]


def test_remove(db):
    pid = db.add_product(1, URL, "Book", 5.0)
    msg = FakeMessage()
    run(bot.cmd_remove(msg, args("abc"), db))
    run(bot.cmd_remove(msg, args("999"), db))
    run(bot.cmd_remove(msg, args(str(pid)), db))
    assert msg.answers[0].startswith("Usage")
    assert msg.answers[1] == "Product not found."
    assert msg.answers[2] == "Removed."


def test_cannot_remove_other_users_product(db):
    pid = db.add_product(2, URL, "Book", 5.0)
    msg = FakeMessage(chat_id=1)
    run(bot.cmd_remove(msg, args(str(pid)), db))
    assert msg.answers[0] == "Product not found."
    assert len(db.list_products(2)) == 1


def test_export(db):
    msg = FakeMessage()
    run(bot.cmd_export(msg, db))
    assert msg.answers == ["Nothing to export yet."]
    db.add_product(1, URL, "Book", 5.0)
    run(bot.cmd_export(msg, db))
    assert len(msg.documents) == 1


def test_start_and_help_text():
    msg = FakeMessage()
    run(bot.cmd_start(msg))
    assert "/add" in msg.answers[0]


def test_all_handlers_registered():
    assert len(bot.router.message.handlers) == 5