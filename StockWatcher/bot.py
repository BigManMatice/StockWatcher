import asyncio
from datetime import datetime
import discord
from discord.ext import commands, tasks
import alerts
import config
import data
import portfolio
import signals
from stockName import get_display_name, get_mapped_ticker

# 1. Bot Initialization
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# 2. Channel IDs loaded dynamically from .env via config.py
# (Falls back to int conversion from config, defaults to None if missing)
LOG_CHANNEL_ID = getattr(config, "LOG_CHANNEL_ID", None)
ALERT_CHANNEL_ID = getattr(config, "ALERT_CHANNEL_ID", None)

if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
if ALERT_CHANNEL_ID:
    ALERT_CHANNEL_ID = int(ALERT_CHANNEL_ID)

MINOR_LOG_THRESHOLD_PCT = 1.0
EXTREME_ALERT_THRESHOLD_PCT = 3.0

# In-memory tracking to avoid repeating the same extreme alert every minute
alerted_state = {}


# --- BACKGROUND 1-MINUTE MARKET SCANNER ---

import asyncio
import traceback
import discord
from discord.ext import commands, tasks

import config
import data
from stockName import get_display_name

LOG_CHANNEL_ID = getattr(config, "LOG_CHANNEL_ID", None)


@tasks.loop(minutes=1)
async def minute_market_scanner():
    try:
        if not LOG_CHANNEL_ID:
            return

        channel = bot.get_channel(LOG_CHANNEL_ID)
        if not channel:
            try:
                channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception as e:
                print(f"[Logger Warning] Could not find channel: {e}")
                return

        # Fetch watchlist items (replace with DB lookup if needed)
        watchlist_items = ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]

        embed = discord.Embed(
            title="📈 Watchlist Live Status",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        for ticker in watchlist_items:
            display_name = get_display_name(ticker)
            try:
                quote = await asyncio.to_thread(data.get_finnhub_quote, ticker)
                price = quote["price"]
                pct = quote["pct_change"]
                icon = "🟢" if pct >= 0 else "🔴"

                # inline=False forces each stock onto its own clean, full-width row
                embed.add_field(
                    name=f"{icon} {display_name}",
                    value=f"**€{price:.2f}** · ({pct:+.2f}%)",
                    inline=False
                )
            except Exception as e:
                embed.add_field(
                    name=f"⚠️ {display_name}",
                    value=f"Error: {e}",
                    inline=False
                )

        await channel.send(embed=embed)
        print("[Logger Status] Watchlist minute update sent.")

    except Exception as outer_err:
        print(f"[Logger Outer Error]: {outer_err}")


@minute_market_scanner.error
async def minute_market_scanner_error(error):
    print(f"[Task Error] Unhandled exception in loop: {error}")
    traceback.print_exc()


@minute_market_scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    if not minute_market_scanner.is_running():
        minute_market_scanner.start()




# --- BOT COMMANDS ---


@bot.command(name="help")
async def help_cmd(ctx):
    """Show all commands"""
    embed = discord.Embed(title="📈 StockWatcher Commands", color=discord.Color.green())
    embed.add_field(
        name="Portfolio",
        value=(
            "`!add AAPL 500 172.30` add position (total paid in €, price per share in €)\n"
            "`!remove AAPL` remove whole position\n"
            "`!remove AAPL 2` remove 2 shares\n"
            "`!portfolio` show total value and P/L in €"
        ),
        inline=False,
    )
    embed.add_field(
        name="Signals",
        value="`!check TSLA` show price & indicators for a ticker",
        inline=False,
    )
    embed.add_field(
        name="Watchlist & Alerts",
        value=(
            "`!watch MSFT` add ticker to active scanner\n"
            "`!unwatch MSFT` remove ticker from active scanner\n"
            "`!watchlist` show monitored tickers\n"
            "`!scan` run signal scan manually"
        ),
        inline=False,
    )
    embed.add_field(name="Other", value="`!ping` check if bot is online", inline=False)
    embed.set_footer(text="Signals are prompts to look closer, not financial advice.")
    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx):
    """Check if bot is online."""
    await ctx.send("Pong! 🏓")


@bot.command()
async def add(ctx, ticker: str, amount_eur: float, price_eur: float):
    """!add AAPL 75 309.12  (total paid in €, price per share in €)"""
    if amount_eur <= 0 or price_eur <= 0:
        await ctx.send("❌ Amount and price must be positive.")
        return

    # Shares = Total EUR Paid / EUR Price Per Share
    shares = amount_eur / price_eur

    await asyncio.to_thread(portfolio.add_holding, ticker, shares, price_eur)
    await ctx.send(
        f"✅ Added **{ticker.upper()}**: {amount_eur:.2f} € paid at {price_eur:.2f} €/share "
        f"= {shares:.4f} shares"
    )


@bot.command()
async def remove(ctx, ticker: str, shares: float = None):
    """!remove AAPL or !remove AAPL 2"""
    removed = await asyncio.to_thread(portfolio.remove_holding, ticker, shares)
    if not removed:
        await ctx.send(f"❌ You don't hold any **{ticker.upper()}**.")
    elif shares is None:
        await ctx.send(f"✅ Removed whole position for **{ticker.upper()}**.")
    else:
        await ctx.send(f"✅ Removed {shares} shares from **{ticker.upper()}**.")


# Map European ticker symbols to clean display names in Discord
DISPLAY_NAMES = {
    "APC.DE": "AAPL",
    "APC.LS": "AAPL",
    "CSPX.AS": "S&P500",
    "SXR8.DE": "S&P500",
    "SXR8.LS": "S&P500",
}

from stockName import get_display_name

@bot.command(name="portfolio")
async def show_portfolio(ctx):
    async with ctx.typing():
        items = await asyncio.to_thread(portfolio.get_portfolio)

    if not items:
        await ctx.send("Your portfolio is empty.")
        return

    embed = discord.Embed(title="📊 Portfolio (EUR)")
    total_value = total_cost = 0.0

    for it in items:
        # Translates DB ticker (e.g. 'APC.DE' or 'AAPL') into 'AAPL (APC.DE)'
        display_label = get_display_name(it["ticker"])

        if it["price"] is None:
            embed.add_field(
                name=f"⚠️ {display_label}", value=it["error"][:200], inline=False
            )
            continue

        total_value += it["value"]
        total_cost += it["cost"]
        icon = "🟢" if it["pl"] >= 0 else "🔴"

        embed.add_field(
            name=f"{icon} {display_label}   {it['pl']:+.2f} € ({it['pl_pct']:+.2f}%)",
            value=(
                f"{it['shares']:.4f} shares\n"
                f"Bought at {it['buy_price']:.2f} € → now {it['price']:.2f} €\n"
                f"Value **{it['value']:.2f} €** (paid {it['cost']:.2f} €)"
            ),
            inline=False,
        )

    if total_cost > 0:
        pl = total_value - total_cost
        embed.color = (
            discord.Color.green() if pl >= 0 else discord.Color.red()
        )
        embed.add_field(
            name="Total",
            value=(
                f"Value **{total_value:.2f} €** · paid {total_cost:.2f} €\n"
                f"Profit/loss **{pl:+.2f} €** ({pl / total_cost * 100:+.2f}%)"
            ),
            inline=False,
        )

    await ctx.send(embed=embed)


@bot.command()
async def watch(ctx, ticker: str):
    """Add a stock to the watchlist scanner."""
    await asyncio.to_thread(alerts.add_watchlist, ticker)
    await ctx.send(f"✅ Added **{ticker.upper()}** to watchlist.")


@bot.command()
async def unwatch(ctx, ticker: str):
    """Remove a stock from the watchlist scanner."""
    await asyncio.to_thread(alerts.remove_watchlist, ticker)
    await ctx.send(f"✅ Removed **{ticker.upper()}** from watchlist.")


@bot.command()
async def watchlist(ctx):
    """Display all watched stocks."""
    tickers = await asyncio.to_thread(alerts.get_watchlist)
    if not tickers:
        await ctx.send("Watchlist is empty. Add stocks with `!watch TICKER`.")
    else:
        await ctx.send(f"📋 **Watchlist**: {', '.join(tickers)}")


@bot.command(name="scan")
async def scan_watchlist(ctx):
    """Scans all tickers in the watchlist for technical signals."""
    watchlist_items = ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"] # or fetch from DB

    async with ctx.typing():
        embed = discord.Embed(title="🔍 Technical Signal Scan (EUR)")

        for ticker in watchlist_items:
            try:
                res = signals.analyze_ticker(ticker)
                embed.add_field(
                    name=f"{res['display_name']} — €{res['price']:.2f} ({res['pct_change']:+.2f}%)",
                    value=f"**Signal:** {res['signal']}",
                    inline=False
                )
            except Exception as e:
                embed.add_field(
                    name=f"⚠️ {get_display_name(ticker)}",
                    value=f"Error scanning: {e}",
                    inline=False
                )

        await ctx.send(embed=embed)


# --- RUN BOT ---

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)