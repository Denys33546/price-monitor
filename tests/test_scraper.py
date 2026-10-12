import pytest
import requests

from app import scraper
from app.scraper import Product, ScraperError, fetch_product, parse_price, parse_product

SAMPLE_HTML = """
<html><body>
  <h1>A Light in the Attic</h1>
  <p class="price_color">£51.77</p>
</body></html>
"""


def test_parse_price_with_pound_sign():
    assert parse_price("£51.77") == 51.77


def test_parse_price_whole_number():
    assert parse_price("£5.00") == 5.0


def test_parse_price_invalid_text():
    with pytest.raises(ScraperError):
        parse_price("free")


def test_parse_product_extracts_title_and_price():
    product = parse_product(SAMPLE_HTML, "http://example.com/book")
    assert product == Product("http://example.com/book", "A Light in the Attic", 51.77)


def test_parse_product_missing_elements():
    with pytest.raises(ScraperError):
        parse_product("<html><body><p>nothing here</p></body></html>", "http://example.com")


class FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status = status
        self.encoding = None

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")


def test_fetch_product_success(monkeypatch):
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **kw: FakeResponse(SAMPLE_HTML))
    product = fetch_product("http://example.com/book")
    assert product.title == "A Light in the Attic"
    assert product.price == 51.77


def test_fetch_product_http_error(monkeypatch):
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **kw: FakeResponse("", status=404))
    with pytest.raises(ScraperError):
        fetch_product("http://example.com/missing")


def test_fetch_product_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(scraper.requests, "get", boom)
    with pytest.raises(ScraperError):
        fetch_product("http://example.com/book")
