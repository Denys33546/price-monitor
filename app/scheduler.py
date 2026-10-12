"""Periodic price checks."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.db import Database, TrackedProduct
from app.scraper import Product, ScraperError, fetch_product

logger = logging.getLogger(__name__)

Fetcher = Callable[[str], Product]


@dataclass(frozen=True)
class PriceChange:
    product: TrackedProduct
    old_price: float | None
    new_price: float


def record_new_price(
    db: Database, product: TrackedProduct, new_price: float
) -> PriceChange | None:
    """Save a fetched price. Returns a PriceChange only if it differs from the last one."""
    try:
        old_price = db.record_price(product.id, new_price)
    except KeyError:  # product was removed while we were fetching
        return None
    if old_price == new_price:
        return None
    return PriceChange(product=product, old_price=old_price, new_price=new_price)


def check_product(
    db: Database, product: TrackedProduct, fetch: Fetcher = fetch_product
) -> PriceChange | None:
    """Fetch the current price, save it and return a PriceChange if it differs."""
    try:
        scraped = fetch(product.url)
    except ScraperError as exc:
        logger.warning("Skipping %s: %s", product.url, exc)
        return None
    return record_new_price(db, product, scraped.price)


def check_all(
    db: Database, fetch: Fetcher = fetch_product, delay: float = 1.0
) -> list[PriceChange]:
    """Check every tracked product. `delay` seconds between requests keeps us polite."""
    changes: list[PriceChange] = []
    for index, product in enumerate(db.list_all_products()):
        if index and delay:
            time.sleep(delay)
        change = check_product(db, product, fetch)
        if change is not None:
            changes.append(change)
    return changes


async def check_all_async(
    db: Database, fetch: Fetcher = fetch_product, delay: float = 1.0
) -> list[PriceChange]:
    """Same as check_all, but does not block the event loop.

    Only the network call runs in a worker thread; the SQLite connection is
    used from the main thread only (SQLite connections are not thread-safe).
    """
    changes: list[PriceChange] = []
    for index, product in enumerate(db.list_all_products()):
        if index and delay:
            await asyncio.sleep(delay)
        try:
            scraped = await asyncio.to_thread(fetch, product.url)
        except ScraperError as exc:
            logger.warning("Skipping %s: %s", product.url, exc)
            continue
        change = record_new_price(db, product, scraped.price)
        if change is not None:
            changes.append(change)
    return changes


async def run_periodically(
    db: Database,
    interval_minutes: float,
    on_change: Callable[[PriceChange], Awaitable[None]],
    fetch: Fetcher = fetch_product,
    delay: float = 1.0,
    max_runs: int | None = None,
) -> None:
    """Check all products every `interval_minutes` and report each price change."""
    runs = 0
    while max_runs is None or runs < max_runs:
        try:
            changes = await check_all_async(db, fetch, delay)
            logger.info("Price check finished: %d change(s)", len(changes))
            for change in changes:
                await on_change(change)
        except Exception:  # one bad run must not stop the schedule
            logger.exception("Price check run failed")
        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        await asyncio.sleep(interval_minutes * 60)