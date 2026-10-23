import os
from pathlib import Path

from dotenv import load_dotenv

# ---- Flip this when you move the project ----
WINDOWS = True  # True = Windows (development), False = Linux Mint (24/7 server)
#YOURUSER = command whoami 
# ---------------------------------------------

if WINDOWS:
    BASE_DIR = Path(r"C:\Users\matic\Desktop\StockWatcher\StockWatcher")
else:
    BASE_DIR = Path("/home/YOURUSER/stockwatcher")  # change YOURUSER

if not BASE_DIR.is_dir():
    raise RuntimeError(
        f"BASE_DIR does not exist: {BASE_DIR}. Is the WINDOWS flag set correctly?"
    )

DB_PATH = BASE_DIR / "stockwatcher.db"
LOG_PATH = BASE_DIR / "stockwatcher.log"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
FMP_KEY = os.getenv("FMP_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

if not DISCORD_TOKEN or not ALPHAVANTAGE_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or ALPHAVANTAGE_KEY in .env")