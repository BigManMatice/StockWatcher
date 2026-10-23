import asyncio
from datetime import datetime
import discord
from discord.ext import commands, tasks
import alerts
import config
import data
import portfolio

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


@tasks.loop(minutes=1)
async def minute_market_scanner():
    # Only run Monday through Friday
    if datetime.now().weekday() >= 5:
        return

    watchlist = alerts.get_watchlist()
    if not watchlist:
        return

    log_channel = bot.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
    alert_channel = bot.get_channel(ALERT_CHANNEL_ID) if ALERT_CHANNEL_ID else None

    for ticker in watchlist:
        try:
            # Fetch quote and log to local SQLite database
            quote = await asyncio.to_thread(data.get_finnhub_quote, ticker)
            pct = quote["pct_change"]
            price_usd = quote["price"]

            eur_rate = await asyncio.to_thread(data.get_usd_eur)
            price_eur = price_usd * eur_rate

            current_alert_type = None
            if pct >= EXTREME_ALERT_THRESHOLD_PCT:
                current_alert_type = "PEAK"
            elif pct <= -EXTREME_ALERT_THRESHOLD_PCT:
                current_alert_type = "DROP"

            # A. EXTREME MOVEMENT -> Alert Channel (Sends ping ONCE per state change)
            if current_alert_type:
                if alerted_state.get(ticker) != current_alert_type:
                    alerted_state[ticker] = current_alert_type

                    icon = "🚀 **SPIKE / PEAK ALERT**" if current_alert_type == "PEAK" else "🚨 🔻 **CRASH ALERT**"
                    color = discord.Color.green() if current_alert_type == "PEAK" else discord.Color.red()

                    embed = discord.Embed(
                        title=f"{icon}: {ticker}",
                        description="Significant intraday movement detected!",
                        color=color,
                    )
                    embed.add_field(name="Current Price", value=f"{price_eur:.2f} € ({price_usd:.2f} USD)", inline=True)
                    embed.add_field(name="Intraday Change", value=f"{pct:+.2f}%", inline=True)

                    if alert_channel:
                        await alert_channel.send(content="@here Extreme move detected!", embed=embed)

            else:
                if ticker in alerted_state:
                    del alerted_state[ticker]

            # B. MINOR MOVEMENT -> Log Channel
            if abs(pct) >= MINOR_LOG_THRESHOLD_PCT:
                if log_channel:
                    time_str = datetime.now().strftime("%H:%M")
                    icon = "📈" if pct > 0 else "📉"
                    await log_channel.send(
                        f"`[{time_str}]` {icon} **{ticker}**: "
                        f"{price_eur:.2f} € ({price_usd:.2f} USD) | {pct:+.2f}%"
                    )

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")


@minute_market_scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()


# --- BOT EVENTS ---


@bot.event
async def on_ready():
    if not minute_market_scanner.is_running():
        minute_market_scanner.start()
    print(f"Logged in as {bot.user}")


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


@bot.command()
async def scan(ctx):
    """Run manual signal check across watchlist."""
    async with ctx.typing():
        buy_alerts, sell_alerts, errors = await asyncio.to_thread(alerts.scan)

    if not buy_alerts and not sell_alerts and not errors:
        await ctx.send("No signals triggered.")
        return

    msg = []
    for b in buy_alerts:
        msg.append(f"🟢 **BUY SIGNAL**: {b['ticker']} at {b['price']:.2f} €")
    for s in sell_alerts:
        msg.append(f"🔴 **SELL SIGNAL**: {s['ticker']} at {s['price']:.2f} €")
    for err_ticker, err_msg in errors:
        msg.append(f"⚠️ Error checking **{err_ticker}**: {err_msg[:100]}")

    await ctx.send("\n".join(msg))


# --- RUN BOT ---

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)