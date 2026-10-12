import asyncio

import pytest

from app.db import Database
from app.scheduler import check_all, check_all_async, check_product, run_periodically
from app.scraper import Product, ScraperError

URL = "http://example.com/book"


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


def fetcher(price):
    return lambda url: Product(url, "Book", price)


def test_check_product_detects_price_drop(db):
    product_id = db.add_product(1, URL, "Book", 50.0)
    product = db.list_products(1)[0]
    change = check_product(db, product, fetcher(40.0))
    assert change is not None
    assert (change.old_price, change.new_price) == (50.0, 40.0)
    assert db.list_products(1)[0].last_price == 40.0
    assert [p for _, p in db.get_history(product_id)] == [50.0, 40.0]


def test_check_product_no_change(db):
    db.add_product(1, URL, "Book", 50.0)
    product = db.list_products(1)[0]
    assert check_product(db, product, fetcher(50.0)) is None


def test_check_product_scraper_error_is_skipped(db):
    db.add_product(1, URL, "Book", 50.0)
    product = db.list_products(1)[0]

    def broken(url):
        raise ScraperError("site is down")

    assert check_product(db, product, broken) is None
    assert db.list_products(1)[0].last_price == 50.0


def test_check_product_removed_meanwhile(db):
    product_id = db.add_product(1, URL, "Book", 50.0)
    product = db.list_products(1)[0]
    db.remove_product(1, product_id)
    assert check_product(db, product, fetcher(40.0)) is None


def test_check_all_returns_only_changed(db):
    db.add_product(1, "http://example.com/a", "A", 50.0)
    db.add_product(1, "http://example.com/b", "B", 30.0)
    prices = {"http://example.com/a": 45.0, "http://example.com/b": 30.0}
    changes = check_all(db, lambda url: Product(url, "x", prices[url]), delay=0)
    assert len(changes) == 1
    assert changes[0].product.url == "http://example.com/a"


def test_run_periodically_calls_callback(db):
    db.add_product(1, URL, "Book", 50.0)
    received = []

    async def on_change(change):
        received.append(change)

    asyncio.run(run_periodically(db, 0, on_change, fetch=fetcher(40.0), delay=0, max_runs=2))
    assert len(received) == 1  # second run sees no further change
    assert received[0].new_price == 40.0


def test_run_periodically_survives_unexpected_errors(db):
    db.add_product(1, URL, "Book", 50.0)
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")  # not a ScraperError
        return Product(url, "Book", 40.0)

    received = []

    async def on_change(change):
        received.append(change)

    asyncio.run(run_periodically(db, 0, on_change, fetch=flaky, delay=0, max_runs=2))
    assert len(received) == 1


def test_check_all_waits_between_requests(db):
    db.add_product(1, "http://example.com/a", "A", 50.0)
    db.add_product(1, "http://example.com/b", "B", 50.0)
    assert check_all(db, fetcher(50.0), delay=0.001) == []


def test_check_all_async_skips_broken_pages(db):
    db.add_product(1, "http://example.com/a", "A", 50.0)
    db.add_product(1, "http://example.com/b", "B", 50.0)

    def fetch(url):
        if url.endswith("/a"):
            raise ScraperError("site is down")
        return Product(url, "B", 40.0)

    changes = asyncio.run(check_all_async(db, fetch, delay=0.001))
    assert [c.product.url for c in changes] == ["http://example.com/b"]
