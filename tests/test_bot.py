# tests/test_bot.py
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import bot
import data
import portfolio


@pytest.mark.asyncio
async def test_bot_commands_and_events():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author.id = "123456789"
    ctx.author.name = "TestAuthor"
    ctx.typing = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )

    await bot.ping(ctx)
    ctx.send.assert_called_with("Pong! 🏓")

    await bot.help_cmd(ctx)
    await bot.view_alert_threshold(ctx)

    await bot.set_alert_threshold(ctx, 3.5)
    assert bot.SPIKE_THRESHOLD_PCT == 3.5

    await bot.set_alert_threshold(ctx, -1.0)

    err1 = bot.commands.MissingRequiredArgument(bot.commands.Parameter("percentage", bot.commands.Parameter.POSITIONAL_ONLY))
    await bot.set_alert_threshold_error(ctx, err1)

    err2 = bot.commands.BadArgument()
    await bot.set_alert_threshold_error(ctx, err2)

    await bot.connect_account(ctx, "test_qa_user")
    assert portfolio.resolve_user_id("test_qa_user") == "123456789"

    with closing(data._connect()) as conn, conn:
        conn.execute("DELETE FROM holdings WHERE user_id = '123456789'")

    await bot.add_cmd(ctx, "AAPL", 500.0, 250.0)
    await bot.show_portfolio(ctx)

    await bot.check_ticker(ctx, "APC.DE")

    await bot.watch(ctx, "MSF.DE")
    await bot.watchlist(ctx)
    await bot.scan_watchlist(ctx)
    await bot.unwatch(ctx, "MSF.DE")

    await bot.remove_cmd(ctx, "AAPL")

    with patch.object(bot.minute_market_scanner, "is_running", return_value=False), \
         patch.object(bot.minute_market_scanner, "start") as mock_start:
        await bot.on_ready()
        mock_start.assert_called_once()

    mock_channel = AsyncMock()
    with patch.object(bot.bot, "get_channel", return_value=mock_channel), \
         patch("bot.LOG_CHANNEL_ID", 12345), \
         patch("bot.ALERT_CHANNEL_ID", 67890):
        bot.last_prices["APC.DE"] = 100.0
        with patch("data.get_finnhub_quote", return_value={"price": 110.0, "pct_change": 10.0}):
            await bot.minute_market_scanner()


@pytest.mark.asyncio
async def test_alert_spike_trigger_threshold():
    """Verify that minute_market_scanner triggers a Discord alert when price movement >= threshold."""
    bot.SPIKE_THRESHOLD_PCT = 0.1
    bot.last_prices["APC.DE"] = 100.0

    mock_log_channel = AsyncMock()
    mock_alert_channel = AsyncMock()

    def get_channel_side_effect(channel_id):
        if channel_id == 12345:
            return mock_log_channel
        if channel_id == 67890:
            return mock_alert_channel
        return None

    fake_quote = {
        "ticker": "APC.DE",
        "price": 105.0,
        "prev_close": 100.0,
        "pct_change": 5.0,
    }

    with patch("alerts.get_all_global_watchlists", return_value=["APC.DE"]), \
         patch("data.get_finnhub_quote", return_value=fake_quote), \
         patch.object(bot.bot, "get_channel", side_effect=get_channel_side_effect), \
         patch("bot.LOG_CHANNEL_ID", 12345), \
         patch("bot.ALERT_CHANNEL_ID", 67890):

        await bot.minute_market_scanner()

        mock_alert_channel.send.assert_called_once()
        called_embed = mock_alert_channel.send.call_args[1]["embed"]
        assert "Price Spike Alert!" in called_embed.title
        assert "APC.DE" in called_embed.description