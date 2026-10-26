import logging
from logging.handlers import RotatingFileHandler
import warnings

import config
from bot import bot

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*inplace keyword.*")

handler = RotatingFileHandler(
    config.LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[handler, logging.StreamHandler()],
)

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN, log_handler=None)