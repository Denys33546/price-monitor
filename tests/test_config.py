from app.config import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "15")
    monkeypatch.setenv("DB_PATH", "test.db")
    settings = load_settings()
    assert settings.bot_token == "abc"
    assert settings.check_interval_minutes == 15
    assert settings.db_path == "test.db"


def test_load_settings_defaults(monkeypatch):
    for name in ("BOT_TOKEN", "CHECK_INTERVAL_MINUTES", "DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert settings.check_interval_minutes == 60
    assert settings.db_path == "price_monitor.db"