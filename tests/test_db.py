import pytest

from app.db import Database, DuplicateProductError

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


@pytest.fixture()
def db():
    database = Database(":memory:")  # fresh in-memory DB for every test
    yield database
    database.close()


def test_add_and_list_product(db):
    product_id = db.add_product(chat_id=1, url=URL, title="A Light in the Attic", price=51.77)
    products = db.list_products(chat_id=1)
    assert len(products) == 1
    assert products[0].id == product_id
    assert products[0].title == "A Light in the Attic"
    assert products[0].last_price == 51.77
    assert products[0].target_price is None


def test_add_stores_first_price_in_history(db):
    product_id = db.add_product(1, URL, "Book", 51.77)
    history = db.get_history(product_id)
    assert [price for _, price in history] == [51.77]


def test_duplicate_product_for_same_user(db):
    db.add_product(1, URL, "Book", 51.77)
    with pytest.raises(DuplicateProductError):
        db.add_product(1, URL, "Book", 51.77)


def test_same_url_for_different_users_is_allowed(db):
    db.add_product(1, URL, "Book", 51.77)
    db.add_product(2, URL, "Book", 51.77)
    assert len(db.list_all_products()) == 2


def test_list_products_only_returns_own(db):
    db.add_product(1, URL, "Book", 51.77)
    assert db.list_products(chat_id=2) == []


def test_record_price_returns_previous_and_updates(db):
    product_id = db.add_product(1, URL, "Book", 51.77)
    previous = db.record_price(product_id, 45.00)
    assert previous == 51.77
    assert db.list_products(1)[0].last_price == 45.00
    assert [price for _, price in db.get_history(product_id)] == [51.77, 45.00]


def test_record_price_unknown_product(db):
    with pytest.raises(KeyError):
        db.record_price(999, 10.0)


def test_remove_product_only_by_owner(db):
    product_id = db.add_product(1, URL, "Book", 51.77)
    assert db.remove_product(chat_id=2, product_id=product_id) is False
    assert db.remove_product(chat_id=1, product_id=product_id) is True
    assert db.list_products(1) == []


def test_remove_product_deletes_history(db):
    product_id = db.add_product(1, URL, "Book", 51.77)
    db.remove_product(1, product_id)
    assert db.get_history(product_id) == []





def test_remove_all_only_for_given_chat(db):
    db.add_product(1, URL, "Book", 5.0)
    db.add_product(1, URL + "2", "Book 2", 5.0)
    db.add_product(2, URL, "Book", 5.0)
    assert db.remove_all(1) == 2
    assert db.list_products(1) == []
    assert len(db.list_products(2)) == 1