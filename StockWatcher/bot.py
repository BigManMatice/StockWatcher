import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

import alerts
import config
import data
import portfolio
import signals

log = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not daily_scan.is_running():
        daily_scan.start()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send(f"❌ Usage: `!{ctx.command.name} {ctx.command.signature}`")
        return
    log.error("Command failed", exc_info=error)
    await ctx.send("❌ Something went wrong. Check the console for details.")


@bot.command()
async def ping(ctx):
    await ctx.send("pong")


@bot.command()
async def add(ctx, ticker: str, shares: float, price: float):
    """!add AAPL 5 172.30"""
    try:
        await asyncio.to_thread(portfolio.add_holding, ticker, shares, price)
    except ValueError as e:
        await ctx.send(f"❌ {e}")
        return
    await ctx.send(f"✅ Added {shares:g} × {ticker.upper()} @ {price:.2f}")


@bot.command()
async def remove(ctx, ticker: str, shares: float = None):
    """!remove AAPL  (whole position)  or  !remove AAPL 2  (some shares)"""
    found = await asyncio.to_thread(portfolio.remove_holding, ticker, shares)
    if not found:
        await ctx.send(f"❌ You don't hold {ticker.upper()}.")
    elif shares is None:
        await ctx.send(f"✅ Removed {ticker.upper()}.")
    else:
        await ctx.send(f"✅ Removed {shares:g} × {ticker.upper()}.")


@bot.command(name="portfolio")
async def show_portfolio(ctx):
    async with ctx.typing():
        items = await asyncio.to_thread(portfolio.get_portfolio)

    if not items:
        await ctx.send("Your portfolio is empty. Add a position with `!add AAPL 5 172.30`.")
        return

    lines = []
    total_value = total_cost = 0.0
    for it in items:
        if it["price"] is None:
            lines.append(f"{it['ticker']:<6} ⚠️ {it['error']}")
            continue
        total_value += it["value"]
        total_cost += it["cost"]
        lines.append(
            f"{it['ticker']:<6} {it['shares']:g} sh  "
            f"{it['buy_price']:.2f} -> {it['price']:.2f}  "
            f"{it['value']:>9.2f}  {it['pl']:+.2f} ({it['pl_pct']:+.1f}%)"
        )

    if total_cost > 0:
        pl = total_value - total_cost
        lines.append("-" * 40)
        lines.append(f"TOTAL  value {total_value:.2f}  P/L {pl:+.2f} ({pl / total_cost * 100:+.1f}%)")

    await ctx.send("```\n" + "\n".join(lines) + "\n```")

@bot.command()
async def check(ctx, ticker: str):
    """!check TSLA"""
    ticker = ticker.upper()
    async with ctx.typing():
        try:
            df = await asyncio.to_thread(data.get_daily, ticker)
        except data.DataError as e:
            await ctx.send(f"❌ {e}")
            return

    res = signals.analyze(df)
    icon = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}[res["signal"]]
    lines = [f"{icon} **{ticker}: {res['signal'].upper()}**  (close {res['price']:.2f})"]
    if "rsi" in res:
        lines.append(
            f"SMA{signals.FAST} {res['sma_fast']:.2f} / SMA{signals.SLOW} {res['sma_slow']:.2f} "
            f"(trend {res['trend']}), RSI {res['rsi']:.0f}"
        )
    lines += [f"• {r}" for r in res["reasons"]]
    await ctx.send("\n".join(lines))
SCAN_TZ = ZoneInfo("Europe/Brussels")
SCAN_TIME = dt.time(hour=23, minute=0, tzinfo=SCAN_TZ)  # after the US market closes


def format_alert(a):
    icon = "🟢" if a["signal"] == "buy" else "🔴"
    tag = " (you hold this)" if a["held"] else ""
    lines = [f"{icon} **{a['ticker']}: {a['signal'].upper()}**{tag}  close {a['price']:.2f}"]
    lines += [f"• {r}" for r in a["reasons"]]
    return "\n".join(lines)


async def run_scan(channel, always_reply=False):
    alert_list, skipped, errors = await asyncio.to_thread(alerts.scan)
    parts = [format_alert(a) for a in alert_list]
    if skipped:
        parts.append(f"⚠️ Skipped (API budget, will retry next scan): {', '.join(skipped)}")
    if errors:
        parts.append("⚠️ Errors: " + "; ".join(f"{t}: {e[:80]}" for t, e in errors))
    if not parts and always_reply:
        parts.append("Scan done: no new buy/sell signals.")
    if parts:
        await channel.send("\n\n".join(parts))


@tasks.loop(time=SCAN_TIME)
async def daily_scan():
    if dt.datetime.now(SCAN_TZ).weekday() >= 5:  # skip Saturday and Sunday
        return
    channel = bot.get_channel(config.CHANNEL_ID) or await bot.fetch_channel(config.CHANNEL_ID)
    await run_scan(channel)


@daily_scan.error
async def daily_scan_error(error):
    log.error("Daily scan failed", exc_info=error)


@bot.command()
async def watch(ctx, ticker: str):
    """!watch MSFT"""
    added = await asyncio.to_thread(alerts.add_watch, ticker)
    await ctx.send(f"👀 Watching {ticker.upper()}." if added else f"Already watching {ticker.upper()}.")


@bot.command()
async def unwatch(ctx, ticker: str):
    """!unwatch MSFT"""
    removed = await asyncio.to_thread(alerts.remove_watch, ticker)
    await ctx.send(f"✅ Stopped watching {ticker.upper()}." if removed else f"❌ {ticker.upper()} isn't on your watchlist.")


@bot.command()
async def watchlist(ctx):
    items = await asyncio.to_thread(alerts.get_watchlist)
    await ctx.send("Watchlist: " + ", ".join(items) if items else "Watchlist is empty. Try `!watch MSFT`.")


@bot.command()
async def scan(ctx):
    """Run the scan now, instead of waiting for 23:00."""
    async with ctx.typing():
        await run_scan(ctx.channel, always_reply=True)