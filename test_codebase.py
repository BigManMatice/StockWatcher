# test_codebase.py
import asyncio
import io
import os
import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import pytest

import alerts
import bot
import config
import data
import portfolio
import signals
import stockName
import cli
import main


# --- 1. STOCKNAME MODULE ---
def test_stock_name_mappings():
    assert stockName.get_mapped_ticker("AAPL") == "APC.DE"
    assert stockName.get_mapped_ticker("MSFT") == "MSF.DE"
    assert stockName.get_mapped_ticker("NVDA") == "NVD.DE"
    assert stockName.get_mapped_ticker("S&P500") == "CSPX.AS"
    assert stockName.get_mapped_ticker("TSLA") == "TSLA"

    assert stockName.get_display_name("AAPL") == "AAPL (APC.DE)"
    assert stockName.get_display_name("APC.DE") == "AAPL (APC.DE)"
    assert stockName.get_display_name("MSFT") == "MSFT (MSF.DE)"
    assert stockName.get_display_name("UNKNOWN") == "UNKNOWN"


# --- 2. CONFIG & DATA MODULE ---
def test_database_init_and_schema_migration():
    data.init_db()
    assert os.path.exists(config.DB_PATH)

    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS test_legacy_prices")
        conn.execute("CREATE TABLE test_legacy_prices (ticker TEXT, date TEXT, close REAL)")
        cursor = conn.execute("PRAGMA table_info(test_legacy_prices)")
        cols = [c[1] for c in cursor.fetchall()]
        assert "open" not in cols

    data.init_db()


def test_data_usd_eur_caching_and_fallbacks(monkeypatch):
    rate1 = data.get_usd_eur()
    assert rate1 > 0
    rate2 = data.get_usd_eur()
    assert rate1 == rate2

    with patch("yfinance.Ticker", side_effect=Exception("API Error")), \
         patch("requests.get", side_effect=Exception("FMP Error")):
        rate_fallback = data.get_usd_eur()
        assert rate_fallback > 0


def test_data_quotes_and_fallback(monkeypatch):
    quote = data.get_finnhub_quote("APC.DE")
    assert "price" in quote
    assert quote["price"] > 0

    with pytest.raises(data.DataError):
        data.get_finnhub_quote("INVALID_TICKER_XYZ_999")

    with pytest.raises(data.DataError):
        data._fetch_yfinance_quote("INVALID_TICKER_XYZ_999")

    with pytest.raises(data.DataError):
        data._fetch_fmp_quote("INVALID_TICKER_XYZ_999")


def test_data_get_daily():
    df = data.get_daily("APC.DE")
    assert not df.empty
    assert "close" in df.columns

    with pytest.raises(data.DataError):
        data.get_daily("NON_EXISTENT_TICKER_999")


# --- 3. SIGNALS & TECHNICAL INDICATORS ---
def test_technical_indicators_math():
    dates = pd.date_range(start="2025-01-01", periods=60, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(60)],
            "high": [105.0 + i for i in range(60)],
            "low": [95.0 + i for i in range(60)],
            "close": [102.0 + i for i in range(60)],
            "volume": [1000 + i * 10 for i in range(60)],
        },
        index=dates,
    )

    rsi = signals.calculate_rsi(df["close"])
    assert not rsi.empty

    macd = signals.calculate_macd(df["close"])
    assert macd["cross"] in ["bullish", "bearish"]

    bb = signals.calculate_bollinger_bands(df["close"])
    assert "middle" in bb
    assert "squeeze" in bb

    atr = signals.calculate_atr(df)
    assert atr > 0

    stoch = signals.calculate_stochastic(df)
    assert stoch["status"] in ["oversold", "overbought", "neutral"]

    obv = signals.calculate_obv(df)
    assert obv["trend"] in ["rising", "falling"]

    pivots = signals.calculate_pivot_points(df)
    assert "pivot" in pivots


def test_analyze_ticker_branches():
    res = signals.analyze_ticker("APC.DE")
    assert "verdict" in res
    assert res["verdict"] in ["BULLISH 🚀", "BEARISH 💥", "NEUTRAL ⚖️"]

    multi_dates = pd.date_range(start="2025-01-01", periods=60, freq="D")
    tuples = [("close", "APC.DE"), ("high", "APC.DE"), ("low", "APC.DE"), ("open", "APC.DE"), ("volume", "APC.DE")]
    cols = pd.MultiIndex.from_tuples(tuples)
    multi_df = pd.DataFrame(
        [[100.0 + i, 105.0 + i, 95.0 + i, 100.0 + i, 1000] for i in range(60)],
        index=multi_dates,
        columns=cols,
    )

    with patch("data.get_daily", return_value=multi_df):
        res_multi = signals.analyze_ticker("APC.DE")
        assert "verdict" in res_multi

    dates = pd.date_range(start="2025-01-01", periods=20, freq="D")
    short_df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "close": [102.0] * 20,
            "volume": [1000] * 20,
        },
        index=dates,
    )

    with patch("data.get_daily", return_value=short_df):
        res_short = signals.analyze_ticker("APC.DE")
        assert "Insufficient data" in res_short["signal"]

    with pytest.raises(RuntimeError):
        signals.analyze_ticker("INVALID_TICKER_XYZ_999")


# --- 4. PORTFOLIO MODULE ---
def test_portfolio_full_lifecycle():
    user = "test_qa_user"

    data.init_db()
    with closing(data._connect()) as conn, conn:
        conn.execute("DELETE FROM holdings WHERE user_id IN (?, '123456789')", (user,))

    portfolio.link_discord_account("123456789", "test_qa_user")
    assert portfolio.resolve_user_id("test_qa_user") == "123456789"

    portfolio.add_holding(user, "AAPL", total_paid=500.0, buy_price=250.0)
    portfolio.add_holding(user, "AAPL", total_paid=500.0, buy_price=250.0)

    holdings = portfolio.get_portfolio(user)
    assert len(holdings) == 1
    assert holdings[0]["shares"] == 4.0

    assert portfolio.remove_holding(user, "AAPL", shares=1.0) is True
    assert portfolio.get_portfolio(user)[0]["shares"] == 3.0

    assert portfolio.remove_holding(user, "AAPL") is True
    assert len(portfolio.get_portfolio(user)) == 0

    assert portfolio.remove_holding(user, "NON_EXISTENT") is False

    with pytest.raises(ValueError):
        portfolio.add_holding(user, "AAPL", total_paid=-100, buy_price=10)


# --- 5. ALERTS MODULE ---
def test_alerts_and_watchlist_scan():
    alerts.add_watchlist("test_qa_user", "APC.DE")
    assert "APC.DE" in alerts.get_watchlist("test_qa_user")

    buy_alerts, sell_alerts, errors = alerts.scan("test_qa_user")
    assert isinstance(buy_alerts, list)
    assert isinstance(sell_alerts, list)

    alerts.remove_watchlist("test_qa_user", "APC.DE")
    assert "APC.DE" not in alerts.get_watchlist("test_qa_user")

    with patch("data.get_usd_eur", side_effect=data.DataError("Mock USD/EUR failure")):
        b, s, errs = alerts.scan("test_qa_user")
        assert len(errs) > 0


# --- 6. DISCORD BOT COMMANDS & TASKS ---
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


# --- 7. CLI & TEXTUAL UI DASHBOARD ---
def test_cli_cache_and_helpers():
    cli.set_cached_user("test_cache_user")
    assert cli.get_cached_user() == "test_cache_user"


@pytest.mark.asyncio
async def test_cli_dashboard_app():
    app = cli.DashboardApp()
    async with app.run_test() as pilot:
        app.update_status_view()
        app.update_watchlist_view()

        app.execute_custom_command("!login new_user")
        app.execute_custom_command("!portfolio")
        app.execute_custom_command("!scan")
        app.execute_custom_command("!invalid")

        log_widget = app.query_one("#log_window", cli.Log)
        redirector = cli.LogRedirector(log_widget)
        redirector.write("Testing CLI log output\n")
        redirector.flush()


def test_cli_main_entrypoint(monkeypatch):
    with patch("sys.argv", ["cli.py", "cli-only"]), \
         patch("main.bot.run"):
        cli.main_cli()


# --- 8. MAIN ENTRYPOINT ---
def test_main_import_and_logging():
    assert main.bot is not None