# config.py
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "bot_database.db"
LOG_PATH = BASE_DIR / "stockwatcher.log"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
ALPHAVANTAGE_KEY: Optional[str] = os.getenv("ALPHAVANTAGE_KEY")
FINNHUB_KEY: Optional[str] = os.getenv("FINNHUB_KEY")
FMP_KEY: Optional[str] = os.getenv("FMP_KEY")

ALERT_CHANNEL_ID: int = int(os.getenv("ALERT_CHANNEL_ID", "0"))
LOG_CHANNEL_ID: int = int(os.getenv("LOG_CHANNEL_ID", "0"))

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env file.")