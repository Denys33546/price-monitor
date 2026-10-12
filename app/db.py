"""SQLite storage for tracked products and their price history."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    url          TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    target_price REAL,
    last_price   REAL,
    created_at   TEXT    NOT NULL,
    UNIQUE (chat_id, url)
);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price      REAL    NOT NULL,
    checked_at TEXT    NOT NULL
);
"""


class DuplicateProductError(Exception):
    """The user already tracks this URL."""


@dataclass(frozen=True)
class TrackedProduct:
    id: int
    chat_id: int
    url: str
    title: str
    target_price: float | None
    last_price: float | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_product(row: sqlite3.Row) -> TrackedProduct:
    return TrackedProduct(
        id=row["id"],
        chat_id=row["chat_id"],
        url=row["url"],
        title=row["title"],
        target_price=row["target_price"],
        last_price=row["last_price"],
    )


class Database:
    def __init__(self, path: str = "price_monitor.db") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def add_product(
        self,
        chat_id: int,
        url: str,
        title: str,
        price: float,
        target_price: float | None = None,
    ) -> int:
        """Start tracking a product and store its first price. Returns the product id."""
        now = _now()
        try:
            with self.conn:  # one transaction: both inserts or none
                cur = self.conn.execute(
                    "INSERT INTO products "
                    "(chat_id, url, title, target_price, last_price, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (chat_id, url, title, target_price, price, now),
                )
                product_id = cur.lastrowid
                self.conn.execute(
                    "INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)",
                    (product_id, price, now),
                )
        except sqlite3.IntegrityError:
            raise DuplicateProductError(url) from None
        return product_id

    def list_products(self, chat_id: int) -> list[TrackedProduct]:
        rows = self.conn.execute(
            "SELECT * FROM products WHERE chat_id = ? ORDER BY id", (chat_id,)
        ).fetchall()
        return [_to_product(r) for r in rows]

    def list_all_products(self) -> list[TrackedProduct]:
        rows = self.conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [_to_product(r) for r in rows]

    def remove_product(self, chat_id: int, product_id: int) -> bool:
        """Delete a product owned by chat_id. Returns False if nothing was deleted."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM products WHERE id = ? AND chat_id = ?", (product_id, chat_id)
            )
        return cur.rowcount > 0

    def record_price(self, product_id: int, price: float) -> float | None:
        """Save a new price check. Returns the previous price (None if unknown)."""
        row = self.conn.execute(
            "SELECT last_price FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Product {product_id} not found")
        previous = row["last_price"]
        with self.conn:
            self.conn.execute(
                "INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)",
                (product_id, price, _now()),
            )
            self.conn.execute(
                "UPDATE products SET last_price = ? WHERE id = ?", (price, product_id)
            )
        return previous

    def get_history(self, product_id: int) -> list[tuple[str, float]]:
        """Return [(checked_at, price), ...] from oldest to newest."""
        rows = self.conn.execute(
            "SELECT checked_at, price FROM price_history WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
        return [(r["checked_at"], r["price"]) for r in rows]

    def remove_all(self, chat_id: int) -> int:
        """Delete every product of a chat (e.g. the user blocked the bot). Returns the count."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM products WHERE chat_id = ?", (chat_id,))
        return cur.rowcount
