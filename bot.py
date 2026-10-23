import asyncio
from datetime import datetime
import traceback
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

# 2. Channel IDs loaded dynamically from config.py
LOG_CHANNEL_ID = getattr(config, "LOG_CHANNEL_ID", None)
ALERT_CHANNEL_ID = getattr(config, "ALERT_CHANNEL_ID", None)

if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
if ALERT_CHANNEL_ID:
    ALERT_CHANNEL_ID = int(ALERT_CHANNEL_ID)

# Dynamic threshold variable (default 2.0%)
SPIKE_THRESHOLD_PCT = 2.0

# In-memory tracking for previous prices
last_prices = {}


# --- COMMANDS TO CHANGE & VIEW THRESHOLD ---

@bot.command(name="setalert")
@commands.has_permissions(administrator=True)
async def set_alert_threshold(ctx, percentage: float):
    """Dynamically set the price spike alert percentage threshold."""
    global SPIKE_THRESHOLD_PCT
    if percentage <= 0:
        await ctx.send("⚠️ Threshold percentage must be greater than 0.")
        return

    SPIKE_THRESHOLD_PCT = percentage
    embed = discord.Embed(
        title="⚙️ Alert Threshold Updated",
        description=f"Price spike alerts will now trigger on moves of **±{SPIKE_THRESHOLD_PCT}%** or higher.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    await ctx.send(embed=embed)

@set_alert_threshold.error
async def set_alert_threshold_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Please specify a percentage. Example: `!setalert 1.5`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Please provide a valid number. Example: `!setalert 2.5`")


@bot.command(name="threshold")
async def view_alert_threshold(ctx):
    """Display the current alert threshold percentage."""
    embed = discord.Embed(
        title="📊 Current Alert Settings",
        description=f"Spike Alert Threshold: **±{SPIKE_THRESHOLD_PCT}%**",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)


# --- BACKGROUND 1-MINUTE MARKET SCANNER ---

@tasks.loop(minutes=1)
async def minute_market_scanner():
    try:
        if not LOG_CHANNEL_ID:
            return

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            try:
                log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception as e:
                print(f"[Logger Warning] Could not find log channel: {e}")
                return

        alert_channel = None
        if ALERT_CHANNEL_ID:
            try:
                alert_channel = bot.get_channel(ALERT_CHANNEL_ID) or await bot.fetch_channel(ALERT_CHANNEL_ID)
            except Exception as e:
                print(f"[Alert Warning] Could not find alert channel: {e}")

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

                # Check for rapid minute-by-minute price spikes
                if ticker in last_prices and alert_channel:
                    prev_price = last_prices[ticker]
                    spike_pct = ((price - prev_price) / prev_price) * 100

                    if abs(spike_pct) >= SPIKE_THRESHOLD_PCT:
                        alert_icon = "🚀" if spike_pct > 0 else "💥"
                        alert_embed = discord.Embed(
                            title=f"{alert_icon} Price Spike Alert! (Threshold: ±{SPIKE_THRESHOLD_PCT}%)",
                            description=(
                                f"**{display_name}** moved **{spike_pct:+.2f}%** in the last minute!\n"
                                f"• **Previous Price:** €{prev_price:.2f}\n"
                                f"• **Current Price:** €{price:.2f}"
                            ),
                            color=discord.Color.gold() if spike_pct > 0 else discord.Color.dark_red(),
                            timestamp=discord.utils.utcnow()
                        )
                        await alert_channel.send(embed=alert_embed)

                last_prices[ticker] = price

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

        await log_channel.send(embed=embed)
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
    embed = discord.Embed(
        title="📈 StockWatcher Commands", 
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="Portfolio & Account",
        value=(
            "`!connect matice` — Link Discord ID to custom CLI username\n"
            "`!add AAPL 500 172.30` — Add position (total paid in €, price per share in €)\n"
            "`!remove AAPL` — Remove whole position\n"
            "`!remove AAPL 2` — Remove 2 shares\n"
            "`!portfolio` — Show total value and P/L in €"
        ),
        inline=False,
    )

    embed.add_field(
        name="Watchlist & Scanning",
        value=(
            "`!watch MSFT` — Add ticker to active scanner\n"
            "`!unwatch MSFT` — Remove ticker from active scanner\n"
            "`!watchlist` — Show monitored tickers\n"
            "`!scan` — Run signal scan manually across watchlist"
        ),
        inline=False,
    )

    embed.add_field(
        name="Signals & Analysis",
        value="`!check TSLA` — Show live price & indicators for a ticker",
        inline=False,
    )

    embed.add_field(
        name="Alert Configuration",
        value=(
            "`!threshold` — View the current price spike alert percentage\n"
            "`!setalert <percent>` — Set spike alert sensitivity (e.g. `!setalert 1.5`)"
        ),
        inline=False,
    )

    embed.add_field(
        name="Other", 
        value="`!ping` — Check if bot is online", 
        inline=False
    )

    embed.set_footer(text="Signals are prompts to look closer, not financial advice. • All prices in EUR")
    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx):
    """Check if bot is online."""
    await ctx.send("Pong! 🏓")


@bot.command(name="connect")
async def connect_account(ctx, username: str):
    """Links your Discord ID to a custom username for CLI UI login."""
    clean_username = username.strip().lower()
    discord_id = str(ctx.author.id)

    portfolio.link_discord_account(discord_id, clean_username)

    embed = discord.Embed(
        title="🔗 Account Connected",
        description=(
            f"Successfully linked **{ctx.author.name}** (Discord ID: `{discord_id}`) "
            f"to CLI username **`{clean_username}`**!\n\n"
            f"You can now use `!login {clean_username}` in the CLI dashboard to manage this portfolio."
        ),
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed)


@bot.command(name="add")
async def add_cmd(ctx, ticker: str, total_paid: float, buy_price: float):
    try:
        portfolio.add_holding(str(ctx.author.id), ticker, total_paid, buy_price)
        shares = total_paid / buy_price
        
        embed = discord.Embed(
            title="✅ Position Added",
            description=(
                f"Added **{ticker.upper()}** to **{ctx.author.name}**'s portfolio!\n"
                f"• Total Paid: €`{total_paid:.2f}`\n"
                f"• Buy Price: €`{buy_price:.2f}` / share\n"
                f"• Shares Acquired: `{shares:.4f}`"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    except ValueError as e:
        await ctx.send(f"⚠️ Error: {e}")
    except Exception as e:
        await ctx.send(f"❌ Failed to add position: {e}")


@bot.command(name="remove")
async def remove_cmd(ctx, ticker: str, shares: float = None):
    try:
        success = portfolio.remove_holding(str(ctx.author.id), ticker, shares)
        if success:
            removed_str = f"`{shares}` shares of" if shares else "all shares of"
            await ctx.send(f"🗑️ Removed {removed_str} **{ticker.upper()}** from **{ctx.author.name}**'s portfolio.")
        else:
            await ctx.send(f"⚠️ No open position for **{ticker.upper()}** found.")
    except Exception as e:
        await ctx.send(f"❌ Failed to remove position: {e}")


@bot.command(name="portfolio")
async def show_portfolio(ctx):
    """Displays user portfolio using exact custom Embed styling."""
    # Resolve user ID (handles raw Discord ID or custom linked account)
    holdings = portfolio.get_portfolio(str(ctx.author.id))

    if not holdings:
        await ctx.send(
            f"💼 Portfolio for **{ctx.author.name}** is currently empty. "
            "Use `!add <ticker> <total_paid> <buy_price>` to add positions."
        )
        return

    # Create Embed styled exactly like your reference UI
    embed = discord.Embed(
        title="📊 Portfolio (EUR)",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )

    total_val = 0.0
    total_cost = 0.0

    for item in holdings:
        ticker = item["ticker"]
        display_name = get_display_name(ticker)
        
        # Build composite label like "AAPL (APC.DE)" if ticker differs from display name
        if display_name != ticker:
            label = f"{display_name} ({ticker})"
        else:
            label = ticker

        shares = item["shares"]
        buy_p = item["buy_price"]
        curr_p = item.get("price", buy_p) or buy_p
        val = item.get("value", shares * curr_p)
        cost = item.get("cost", shares * buy_p)
        pl = item.get("pl", val - cost)
        pl_pct = item.get("pl_pct", 0.0)

        total_val += val
        total_cost += cost

        # Green circle for profit / Red circle for loss
        circle = "🟢" if pl >= 0 else "🔴"

        field_title = f"{circle} {label}   {pl:+.2f} € ({pl_pct:+.2f}%)"
        field_body = (
            f"{shares:.4f} shares\n"
            f"Bought at {buy_p:.2f} € → now {curr_p:.2f} €\n"
            f"Value **{val:.2f} €** (paid {cost:.2f} €)"
        )

        embed.add_field(name=field_title, value=field_body, inline=False)

    total_pl = total_val - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0

    # Total Summary Section
    summary_body = (
        f"Value **{total_val:.2f} €** · paid {total_cost:.2f} €\n"
        f"Profit/loss **{total_pl:+.2f} €** ({total_pl_pct:+.2f}%)"
    )
    embed.add_field(name="Total", value=summary_body, inline=False)

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
    watchlist_items = ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]

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