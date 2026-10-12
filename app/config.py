"""Application settings loaded from environment variables / .env file."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    check_interval_minutes: int
    db_path: str


def load_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        check_interval_minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", "60")),
        db_path=os.getenv("DB_PATH", "price_monitor.db"),
    )
