import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher

from app import main as main_module
from app.config import Settings


def test_main_requires_bot_token(monkeypatch):
    monkeypatch.setattr(main_module, "load_settings", lambda: Settings("", 60, ":memory:"))
    with pytest.raises(SystemExit):
        asyncio.run(main_module.main())


def test_main_starts_polling_and_background_checks(monkeypatch):
    monkeypatch.setattr(
        main_module, "load_settings", lambda: Settings("123456:TEST", 15, ":memory:")
    )
    monkeypatch.setattr(Bot, "set_my_commands", AsyncMock())
    monkeypatch.setattr(Dispatcher, "include_router", lambda self, router: None)

    async def fake_start_polling(*args, **kwargs):
        await asyncio.sleep(0)  # give the background task a chance to start

    start_polling = AsyncMock(side_effect=fake_start_polling)
    monkeypatch.setattr(Dispatcher, "start_polling", start_polling)

    started = {}

    async def fake_run_periodically(db, interval_minutes, on_change):
        started["interval"] = interval_minutes
        await asyncio.sleep(3600)  # endless loop; main() must cancel it on shutdown

    monkeypatch.setattr(main_module, "run_periodically", fake_run_periodically)

    asyncio.run(main_module.main())

    start_polling.assert_awaited_once()
    assert started["interval"] == 15
