import logging
from logging.handlers import RotatingFileHandler

import config
from bot import bot
import warnings

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

bot.run(config.DISCORD_TOKEN, log_handler=None)