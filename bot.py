# bot.py
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
from stockName import get_display_name

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

LOG_CHANNEL_ID = getattr(config, "LOG_CHANNEL_ID", None)
ALERT_CHANNEL_ID = getattr(config, "ALERT_CHANNEL_ID", None)

if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
if ALERT_CHANNEL_ID:
    ALERT_CHANNEL_ID = int(ALERT_CHANNEL_ID)

SPIKE_THRESHOLD_PCT = 2.0
last_prices = {}


@bot.command(name="setalert")
@commands.has_permissions(administrator=True)
async def set_alert_threshold(ctx, percentage: float):
    global SPIKE_THRESHOLD_PCT
    val = float(percentage)
    if val <= 0:
        await ctx.send("⚠️ Threshold percentage must be greater than 0.")
        return

    SPIKE_THRESHOLD_PCT = val
    embed = discord.Embed(
        title="⚙️ Alert Threshold Updated",
        description=f"Price spike alerts will now trigger on moves of **±{SPIKE_THRESHOLD_PCT}%** or higher.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
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
    embed = discord.Embed(
        title="📊 Current Alert Settings",
        description=f"Spike Alert Threshold: **±{SPIKE_THRESHOLD_PCT}%**",
        color=discord.Color.blue(),
    )
    await ctx.send(embed=embed)


@tasks.loop(minutes=1)
async def minute_market_scanner():
    try:
        if not LOG_CHANNEL_ID:
            return

        log_channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return

        alert_channel = None
        if ALERT_CHANNEL_ID:
            try:
                alert_channel = bot.get_channel(ALERT_CHANNEL_ID) or await bot.fetch_channel(ALERT_CHANNEL_ID)
            except Exception as e:
                print(f"[Alert Warning] Could not find alert channel: {e}")

        watchlist_items = alerts.get_all_global_watchlists() or ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]

        embed = discord.Embed(
            title="📈 Watchlist Live Status",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        for ticker in watchlist_items:
            display_name = get_display_name(ticker)
            try:
                quote = await asyncio.to_thread(data.get_finnhub_quote, ticker)
                price = quote["price"]
                pct = quote["pct_change"]
                icon = "🟢" if pct >= 0 else "🔴"

                if ticker in last_prices:
                    prev_price = last_prices[ticker]
                    spike_pct = ((price - prev_price) / prev_price) * 100 if prev_price > 0 else 0.0

                    if abs(spike_pct) >= SPIKE_THRESHOLD_PCT:
                        alert_icon = "🚀" if spike_pct > 0 else "💥"
                        alert_msg = (
                            f"{alert_icon} **Price Spike Alert!**\n"
                            f"**{display_name}** moved **{spike_pct:+.2f}%**!\n"
                            f"• Prev: €{prev_price:.2f} ➔ Curr: €{price:.2f}"
                        )
                        alert_embed = discord.Embed(
                            title=f"{alert_icon} Price Spike Alert! (Threshold: ±{SPIKE_THRESHOLD_PCT}%)",
                            description=alert_msg,
                            color=discord.Color.gold() if spike_pct > 0 else discord.Color.dark_red(),
                            timestamp=discord.utils.utcnow(),
                        )
                        
                        target = alert_channel or log_channel
                        if target:
                            await target.send(embed=alert_embed)

                last_prices[ticker] = price

                embed.add_field(
                    name=f"{icon} {display_name}",
                    value=f"**€{price:.2f}** · ({pct:+.2f}%)",
                    inline=False,
                )
            except Exception as e:
                embed.add_field(
                    name=f"⚠️ {display_name}",
                    value=f"Error: {e}",
                    inline=False,
                )

        await log_channel.send(embed=embed)

    except Exception as outer_err:
        print(f"[Logger Outer Error]: {outer_err}")


@minute_market_scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    bot_name = bot.user.name if bot.user else "StonksBot"
    bot_id = bot.user.id if bot.user else "0000"
    print(f"Logged in as {bot_name} ({bot_id})")
    if not minute_market_scanner.is_running():
        minute_market_scanner.start()


@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="📈 StockWatcher Commands",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Portfolio & Account",
        value=(
            "`!connect <username>` — Link Discord ID to custom CLI username\n"
            "`!add <ticker> <total_paid> <buy_price>` — Add position\n"
            "`!remove <ticker> [shares]` — Remove whole or partial position\n"
            "`!portfolio` — Show total value and P/L in €"
        ),
        inline=False,
    )
    embed.add_field(
        name="Watchlist & Scanning",
        value=(
            "`!watch <ticker>` — Add ticker to scanner\n"
            "`!unwatch <ticker>` — Remove ticker from scanner\n"
            "`!watchlist` — Show monitored tickers\n"
            "`!scan` — Run signal scan manually across watchlist"
        ),
        inline=False,
    )
    embed.add_field(
        name="Signals & Analysis",
        value="`!check <ticker>` — Show live price & indicators for a ticker",
        inline=False,
    )
    embed.add_field(
        name="Alert Configuration",
        value=(
            "`!threshold` — View current spike alert percentage\n"
            "`!setalert <percent>` — Set spike alert sensitivity"
        ),
        inline=False,
    )
    embed.add_field(name="Other", value="`!ping` — Check bot latency", inline=False)
    embed.set_footer(text="Signals are prompts to look closer, not financial advice. • All prices in EUR")
    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx):
    await ctx.send("Pong! 🏓")


@bot.command(name="connect")
async def connect_account(ctx, username: str):
    clean_username = username.strip().lower()
    portfolio.link_discord_account(str(ctx.author.id), clean_username)
    embed = discord.Embed(
        title="🔗 Account Connected",
        description=f"Successfully linked **{ctx.author.name}** to CLI username **`{clean_username}`**!",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed)


@bot.command(name="add")
async def add_cmd(ctx, ticker: str, total_paid: float, buy_price: float):
    try:
        total_paid_num = float(total_paid)
        buy_price_num = float(buy_price)

        user_id = portfolio.resolve_user_id(str(ctx.author.id))
        portfolio.add_holding(user_id, ticker, total_paid_num, buy_price_num)
        shares = total_paid_num / buy_price_num

        embed = discord.Embed(
            title="✅ Position Added",
            description=(
                f"Added **{ticker.upper()}** to portfolio!\n"
                f"• Total Paid: €`{total_paid_num:.2f}`\n"
                f"• Buy Price: €`{buy_price_num:.2f}` / share\n"
                f"• Shares Acquired: `{shares:.4f}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"⚠️ Error: {e}")


@bot.command(name="remove")
async def remove_cmd(ctx, ticker: str, shares: float = None):
    try:
        user_id = portfolio.resolve_user_id(str(ctx.author.id))
        shares_num = float(shares) if shares is not None else None
        if portfolio.remove_holding(user_id, ticker, shares_num):
            removed_str = f"`{shares_num}` shares of" if shares_num is not None else "all shares of"
            await ctx.send(f"🗑️ Removed {removed_str} **{ticker.upper()}** from portfolio.")
        else:
            await ctx.send(f"⚠️ No open position for **{ticker.upper()}** found.")
    except Exception as e:
        await ctx.send(f"❌ Failed to remove position: {e}")


@bot.command(name="portfolio")
async def show_portfolio(ctx):
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    holdings = portfolio.get_portfolio(user_id)
    if not holdings:
        await ctx.send("💼 Portfolio is currently empty. Use `!add` to track positions.")
        return

    embed = discord.Embed(
        title="📊 Portfolio (EUR)",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )

    total_val, total_cost = 0.0, 0.0

    for item in holdings:
        ticker = item["ticker"]
        display_name = get_display_name(ticker)
        shares, buy_p = item["shares"], item["buy_price"]
        curr_p = item.get("price", buy_p) or buy_p
        val = item.get("value", shares * curr_p)
        cost = item.get("cost", shares * buy_p)
        pl = item.get("pl", val - cost)
        pl_pct = item.get("pl_pct", 0.0)

        total_val += val
        total_cost += cost

        circle = "🟢" if pl >= 0 else "🔴"
        field_title = f"{circle} {display_name}   {pl:+.2f} € ({pl_pct:+.2f}%)"
        field_body = (
            f"{shares:.4f} shares\n"
            f"Bought at {buy_p:.2f} € → now {curr_p:.2f} €\n"
            f"Value **{val:.2f} €** (paid {cost:.2f} €)"
        )
        embed.add_field(name=field_title, value=field_body, inline=False)

    total_pl = total_val - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0

    summary_body = (
        f"Value **{total_val:.2f} €** · paid {total_cost:.2f} €\n"
        f"Profit/loss **{total_pl:+.2f} €** ({total_pl_pct:+.2f}%)"
    )
    embed.add_field(name="Total", value=summary_body, inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def watch(ctx, ticker: str):
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    await asyncio.to_thread(alerts.add_watchlist, user_id, ticker)
    await ctx.send(f"✅ Added **{ticker.upper()}** to watchlist.")


@bot.command()
async def unwatch(ctx, ticker: str):
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    await asyncio.to_thread(alerts.remove_watchlist, user_id, ticker)
    await ctx.send(f"✅ Removed **{ticker.upper()}** from watchlist.")


@bot.command()
async def watchlist(ctx):
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    tickers = await asyncio.to_thread(alerts.get_watchlist, user_id)
    if not tickers:
        await ctx.send("Watchlist is empty. Add stocks with `!watch TICKER`.")
    else:
        await ctx.send(f"📋 **Watchlist**: {', '.join(tickers)}")


@bot.command(name="scan")
async def scan_watchlist(ctx):
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    watchlist_items = alerts.get_watchlist(user_id)
    if not watchlist_items:
        await ctx.send("⚠️ Watchlist is empty. Add tickers using `!watch TICKER`.")
        return

    async with ctx.typing():
        embed = discord.Embed(
            title="🔍 Technical Analysis Scan (EUR)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        for ticker in watchlist_items:
            try:
                res = signals.analyze_ticker(ticker)
                display_n = res.get("display_name") or get_display_name(ticker)
                price = res.get("price", 0.0)
                pct = res.get("pct_change", 0.0)
                verdict = res.get("verdict", "NEUTRAL ⚖️")

                circle = "🟢" if pct >= 0 else "🔴"
                field_name = f"{circle} {display_n} — €{price:.2f} ({pct:+.2f}%)"
                field_value = (
                    f"**Verdict:** {verdict}\n"
                    f"• **RSI:** `{res.get('rsi', 0.0):.1f}` | **ATR:** `€{res.get('atr', 0.0):.2f}`\n"
                    f"• **Stoch %K:** `{res['stochastic']['k']:.1f}` | **OBV:** `{res['obv']['trend'].title()}`\n"
                    f"• **Key Reasons:** {', '.join(res.get('reasons', [])[:2])}"
                )
                embed.add_field(name=field_name, value=field_value, inline=False)
            except Exception as e:
                embed.add_field(
                    name=f"⚠️ {get_display_name(ticker)}",
                    value=f"Error scanning: {e}",
                    inline=False,
                )

        await ctx.send(embed=embed)


@bot.command(name="check")
async def check_ticker(ctx, ticker: str):
    async with ctx.typing():
        try:
            res = signals.analyze_ticker(ticker)
            display_n = res.get("display_name") or get_display_name(ticker)
            price = res.get("price", 0.0)
            pct = res.get("pct_change", 0.0)
            verdict = res.get("verdict", "NEUTRAL ⚖️")

            embed = discord.Embed(
                title=f"🔍 Technical Check: {display_n}",
                color=discord.Color.green() if pct >= 0 else discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="Market Overview",
                value=f"• **Price:** €{price:.2f}\n• **Change:** {pct:+.2f}%\n• **Verdict:** {verdict}",
                inline=False,
            )
            embed.add_field(
                name="Technical Indicators",
                value=(
                    f"• **RSI (14):** `{res.get('rsi', 0.0):.1f}`\n"
                    f"• **ATR (14):** `€{res.get('atr', 0.0):.2f}`\n"
                    f"• **Stochastic %K:** `{res['stochastic']['k']:.1f}` ({res['stochastic']['status']})\n"
                    f"• **OBV Trend:** `{res['obv']['trend'].title()}`"
                ),
                inline=False,
            )
            embed.add_field(
                name="Signals & Reasons",
                value="\n".join([f"• {r}" for r in res.get("reasons", [])]) or "None",
                inline=False,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Failed to check {ticker}: {e}")


class CLIContext:
    def __init__(self, user_id: str):
        resolved_id = portfolio.resolve_user_id(user_id)
        self.author = type("User", (), {"id": resolved_id, "name": user_id})()

    async def send(self, content=None, embed=None):
        if content:
            print(f"🤖 {content}")
        if embed:
            print(f"\n--- {embed.title} ---")
            if embed.description:
                print(embed.description)
            for field in embed.fields:
                print(f"• {field.name}:\n  {field.value}")
            print("-" * 40)

    def typing(self):
        class DummyTyping:
            async def __aenter__(self): pass
            async def __aexit__(self, *args): pass
        return DummyTyping()


async def execute_unified_command(user_id: str, command_line: str):
    cmd_line = command_line.strip()
    if not cmd_line.startswith("!"):
        cmd_line = "!" + cmd_line

    parts = cmd_line[1:].split()
    if not parts:
        return

    cmd_name = parts[0].lower()
    args = parts[1:]

    cmd = bot.get_command(cmd_name)
    if not cmd:
        print(f"⚠️ Unknown command: `!{cmd_name}`. Type `!help` for available commands.")
        return

    ctx = CLIContext(user_id)
    try:
        await cmd.callback(ctx, *args)
    except TypeError as e:
        print(f"⚠️ Command argument error: {e}")
    except Exception as e:
        print(f"❌ Execution Error: {e}")