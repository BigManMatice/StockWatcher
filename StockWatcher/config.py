import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

if not DISCORD_TOKEN or not ALPHAVANTAGE_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or ALPHAVANTAGE_KEY in .env")