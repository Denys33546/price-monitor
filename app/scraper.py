"""Scraper for books.toscrape.com product pages."""
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "price-monitor/0.1 (learning project)"}
TIMEOUT = 10  # seconds


class ScraperError(Exception):
    """Raised when a page cannot be loaded or parsed."""


@dataclass(frozen=True)
class Product:
    url: str
    title: str
    price: float


def parse_price(text: str) -> float:
    """Convert a price string like '£51.77' to a float (51.77)."""
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    try:
        return float(cleaned)
    except ValueError:
        raise ScraperError(f"Cannot parse price from {text!r}") from None


def parse_product(html: str, url: str) -> Product:
    """Extract title and price from the HTML of a product page."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("h1")
    price_tag = soup.select_one("p.price_color")
    if title_tag is None or price_tag is None:
        raise ScraperError(f"Title or price not found on {url}")
    return Product(
        url=url,
        title=title_tag.get_text(strip=True),
        price=parse_price(price_tag.get_text(strip=True)),
    )


def fetch_product(url: str) -> Product:
    """Download a product page and return its title and price."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Cannot load {url}: {exc}") from exc
    # The site does not send a charset, so without this '£' becomes 'Â£'
    response.encoding = "utf-8"
    return parse_product(response.text, url)


if __name__ == "__main__":
    print(fetch_product(
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    ))