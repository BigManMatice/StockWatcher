import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, AsyncGenerator
import discord
from discord.ext import commands, tasks
import sqlite3
import alerts
import config
import data
import portfolio
import quant
import signals
import tracker
from stockName import get_display_name

alert_tracker: Dict[str, Dict[str, Any]] = {}
username: str = "matice"

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

LOG_CHANNEL_ID = getattr(config, "LOG_CHANNEL_ID", None)
ALERT_CHANNEL_ID = getattr(config, "ALERT_CHANNEL_ID", None)

if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
if ALERT_CHANNEL_ID:
    ALERT_CHANNEL_ID = int(ALERT_CHANNEL_ID)

SPIKE_THRESHOLD_PCT: float = 2.0
last_prices: Dict[str, float] = {}


def _parse_float(val: str | float | int) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    return float(str(val).replace(",", ".").strip())


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
        if message.author.id == bot.user.id and message.embeds:
            embed = message.embeds[0]
            embed_text = (embed.title or "") + " " + (embed.description or "")
            
            for ticker in alerts.get_all_global_watchlists() or ["APC.DE", "MSF.DE", "VWCE.DE", "2B76.DE", "EUNK.DE"]:
                display_name = get_display_name(ticker)
                if ticker in embed_text or display_name in embed_text:
                    now = datetime.now(timezone.utc)
                    if ticker not in alert_tracker:
                        alert_tracker[ticker] = {
                            "last_sent": datetime.min.replace(tzinfo=timezone.utc), 
                            "last_price": 0.0, 
                            "last_warning": "", 
                            "muted_until": datetime.min.replace(tzinfo=timezone.utc)
                        }
                    
                    alert_tracker[ticker]["muted_until"] = now + timedelta(hours=3)
                    await channel.send(f"🔕 Alert voor **{display_name}** is gepauzeerd voor **3 uur** (reactie-stop actief).")
                    break
    except Exception as e:
        print(f"[Reaction Handler Error]: {e}")


@bot.command(name="setalert")
@commands.has_permissions(administrator=True)
async def set_alert_threshold(ctx: commands.Context, percentage: str) -> None:
    global SPIKE_THRESHOLD_PCT
    try:
        val = _parse_float(percentage)
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
    except ValueError:
        await ctx.send("⚠️ Please provide a valid number. Example: `!setalert 2.5`")


@set_alert_threshold.error
async def set_alert_threshold_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Please specify a percentage. Example: `!setalert 1.5`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Please provide a valid number. Example: `!setalert 2.5`")


@bot.command(name="threshold")
async def view_alert_threshold(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="📊 Current Alert Settings",
        description=f"Spike Alert Threshold: **±{SPIKE_THRESHOLD_PCT}%**",
        color=discord.Color.blue(),
    )
    await ctx.send(embed=embed)


@tasks.loop(minutes=1)
async def minute_market_scanner() -> None:
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

        target_send_channel = alert_channel or log_channel
        watchlist_items = alerts.get_all_global_watchlists() or ["APC.DE", "MSF.DE", "VWCE.DE", "2B76.DE", "EUNK.DE"]
        now = datetime.now(timezone.utc)

        await asyncio.to_thread(tracker.update_alert_outcomes)

        try:
            tot_portfolio_val = await asyncio.to_thread(portfolio.get_portfolio_total, username)
        except Exception as e:
            print(f"[Portfolio Total Error]: {e}")
            tot_portfolio_val = 0.0

        for ticker in watchlist_items:
            display_name = get_display_name(ticker)
            try:
                quote = await asyncio.to_thread(data.get_finnhub_quote, ticker)
                price = quote["price"]

                if ticker in last_prices:
                    prev_price = last_prices[ticker]
                    spike_pct = ((price - prev_price) / prev_price) * 100.0 if prev_price > 0 else 0.0

                    if abs(spike_pct) >= SPIKE_THRESHOLD_PCT:
                        diff_tag = "+" if spike_pct > 0 else "-"
                        alert_icon = "🚀" if spike_pct > 0 else "💥"

                        spike_embed = discord.Embed(
                            title=f"{alert_icon} PRICE SPIKE DETECTED",
                            description=(
                                f"## {display_name}\n"
                                f"De koers stijgt/daalt krachtig buiten de ingestelde drempelwaarde!\n\n"
                                f"```diff\n"
                                f"{diff_tag} Verandering: {spike_pct:+.2f}%\n"
                                f"{diff_tag} Oude Koers:  € {prev_price:.2f}\n"
                                f"{diff_tag} Nieuwe Koers: € {price:.2f}\n"
                                f"```"
                            ),
                            color=discord.Color.green() if spike_pct > 0 else discord.Color.red(),
                            timestamp=discord.utils.utcnow(),
                        )
                        spike_embed.add_field(
                            name="📊 Markt Details",
                            value=f"• **Drempelwaarde:** `±{SPIKE_THRESHOLD_PCT}%`\n**Status:** Actieve markt-uitbraak",
                            inline=False,
                        )
                        spike_embed.set_footer(text="StockWatcher Real-Time Scanner • Trading Alert")

                        if target_send_channel:
                            await target_send_channel.send(embed=spike_embed)

                last_prices[ticker] = price

                res = await asyncio.to_thread(signals.analyze_ticker_advanced, ticker, tot_portfolio_val)
                warnings = res.get("early_warnings", [])
                action_text = res.get("action", "HOLD ⚖️")

                should_trigger = bool(warnings) or "SELL" in action_text

                if should_trigger:
                    if not warnings:
                        warnings = [f"Actief signaal gewijzigd naar {action_text}"]

                    tracker_state = alert_tracker.get(ticker, {
                        "last_sent": datetime.min.replace(tzinfo=timezone.utc),
                        "last_price": price,
                        "last_warning": "",
                        "muted_until": datetime.min.replace(tzinfo=timezone.utc)
                    })

                    time_since_last = now - tracker_state["last_sent"]
                    is_muted = now < tracker_state["muted_until"]
                    price_diff_pct = abs((price - tracker_state["last_price"]) / tracker_state["last_price"] * 100.0) if tracker_state["last_price"] > 0 else 0.0
                    primary_warning = warnings[0] if warnings else ""

                    signal_changed = primary_warning != tracker_state["last_warning"] or "SELL" in action_text
                    time_window_passed = time_since_last >= timedelta(hours=2) and not is_muted
                    big_price_move = price_diff_pct >= 1.5

                    should_send_alert = signal_changed or big_price_move or time_window_passed

                    if should_send_alert:
                        embed_color = discord.Color.green() if "BUY" in action_text else (discord.Color.red() if "SELL" in action_text else discord.Color.gold())

                        await asyncio.to_thread(tracker.log_alert,ticker,primary_warning,action_text,price,res.get("atr"),)
                        hist_stats = await asyncio.to_thread(tracker.get_accuracy_stats, primary_warning)

                        risk_data = res.get("risk_rule_1pct", {})
                        max_risk_eur_val = risk_data.get("max_risk_eur", 0.0)
                        max_eur_val = risk_data.get("max_eur", 0.0)
                        max_shares_val = risk_data.get("max_shares", 0.0)
                        stop_loss_val = risk_data.get("stop_loss_price", 0.0)

                        warning_embed = discord.Embed(
                            title="🚨 QUANT EARLY WARNING ALERT",
                            description=(
                                f"## {res['display_name']}\n"
                                f"Marktpatroon gedetecteerd **vóór** de daadwerkelijke koersuitbraak!\n\n"
                                f"### ⚠️ Signaal Analyse\n"
                                + "\n".join([f"• {w}" for w in warnings]) + "\n\n"
                                f"• **Huidige Koers:** `€ {res['price']:.2f}` (`{res['pct_change']:+.2f}%`)"
                            ),
                            color=embed_color,
                            timestamp=discord.utils.utcnow(),
                        )
                        warning_embed.add_field(
                            name="🎲 Quant Risicobeheer & Position Sizing",
                            value=(
                                f"```yaml\n"
                                f"Portfoliowaarde:     € {tot_portfolio_val:.2f}\n"
                                f"Winstkans Schatting: {res['win_rate']:.1f}%\n"
                                f"Dynamische RRR:      {res['dynamic_rrr']:.2f}\n"
                                f"Tail Risk (CVaR 95): {res['cvar_95']:.2f}%\n"
                                f"Max 1% Risico (EUR): € {max_risk_eur_val:.2f}\n"
                                f"Max Positie Grootte: € {max_eur_val:.2f} ({max_shares_val:.4f} stuks)\n"
                                f"Stop-Loss Koers:     € {stop_loss_val:.2f}\n"
                                f"```"
                            ),
                            inline=False,
                        )
                        accuracy_pct = hist_stats.get("accuracy_pct")
                        accuracy_text = f"{accuracy_pct:.1f}%" if accuracy_pct is not None else "N/A"

                        warning_embed.add_field(
                            name="📊 Model Zekerheid (Historische Data)",
                            value=(
                                f"• **Historische Precisie:** `{accuracy_text}` "
                                f"({hist_stats['wins']}/{hist_stats['total']} winstgevend voorspeld)"
                            ),
                            inline=False,
                        )
                        warning_embed.add_field(
                            name="🎯 ACTIE ADVIES",
                            value=f"### **{action_text}**",
                            inline=False,
                        )
                        warning_embed.set_footer(text="Reageer met een emoji op dit bericht om alerts voor 3 uur te pauzeren • StockWatcher Engine")

                        if target_send_channel:
                            await target_send_channel.send(embed=warning_embed)

                        alert_tracker[ticker] = {
                            "last_sent": now,
                            "last_price": price,
                            "last_warning": primary_warning,
                            "muted_until": tracker_state["muted_until"] if not big_price_move else datetime.min.replace(tzinfo=timezone.utc),
                        }

            except Exception as e:
                print(f"[Scanner Error] {ticker}: {e}")

    except Exception as outer_err:
        print(f"[Scanner Outer Error]: {outer_err}")


@minute_market_scanner.before_loop
async def before_scanner() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    bot_name = bot.user.name if bot.user else "StonksBot"
    bot_id = bot.user.id if bot.user else "0000"
    print(f"Logged in as {bot_name} ({bot_id})")
    if not minute_market_scanner.is_running():
        minute_market_scanner.start()



@bot.command(name="accuracy")
async def show_accuracy(ctx: commands.Context) -> None:
    async with ctx.typing():
        await asyncio.to_thread(tracker.update_alert_outcomes)

        stats_1d = await asyncio.to_thread(
            tracker.get_accuracy_stats, None, "1d"
        )
        stats_3d = await asyncio.to_thread(
            tracker.get_accuracy_stats, None, "3d"
        )
        stats_7d = await asyncio.to_thread(
            tracker.get_accuracy_stats, None, "7d"
        )

        with sqlite3.connect(tracker.DB_FILE) as conn:
            total_alerts = conn.execute(
                "SELECT COUNT(*) FROM alert_history"
            ).fetchone()[0]

            pending = conn.execute("""
                SELECT
                    SUM(CASE WHEN is_winner_1d IS NULL THEN 1 ELSE 0 END),
                    SUM(CASE WHEN is_winner_3d IS NULL THEN 1 ELSE 0 END),
                    SUM(CASE WHEN is_winner_7d IS NULL THEN 1 ELSE 0 END)
                FROM alert_history
            """).fetchone()

        def format_stats(stats):
            accuracy = (
                f"{stats['accuracy_pct']:.1f}%"
                if stats["accuracy_pct"] is not None
                else "N/A"
            )
            return (
                f"Precisie: **{accuracy}**\n"
                f"Correct: **{stats['wins']}/{stats['total']}**\n"
            )

        embed = discord.Embed(
            title="🎯 BOT SIGNALS ACCURACY TRACKER",
            description=(
                "## Historische Betrouwbaarheid & Performance Tracker\n"
                "Gemeten resultaten van uitgezonden alerts, "
                "vergeleken met historische marktkoersen.\n\n"
                f"**Totaal geregistreerde alerts:** {total_alerts}"
            ),
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📅 1-daagse evaluatie",
            value=(
                format_stats(stats_1d)
                + f"Nog niet geëvalueerd: **{pending[0] or 0}**"
            ),
            inline=True,
        )

        embed.add_field(
            name="📅 3-daagse evaluatie",
            value=(
                format_stats(stats_3d)
                + f"Nog niet geëvalueerd: **{pending[1] or 0}**"
            ),
            inline=True,
        )

        embed.add_field(
            name="📅 7-daagse evaluatie",
            value=(
                format_stats(stats_7d)
                + f"Nog niet geëvalueerd: **{pending[2] or 0}**"
            ),
            inline=True,
        )

        embed.add_field(
            name="ℹ️ Evaluatiemethode",
            value=(
                "• BUY: koersstijging van minimaal 1 ATR.\n"
                "• SELL: koersdaling van minimaal 1 ATR.\n"
                "• ATR wordt vastgelegd op het moment van de alert.\n"
                "• Elk tijdsvenster wordt afzonderlijk beoordeeld.\n"
                "• N/A betekent dat er nog geen beoordeelde alerts zijn."
            ),
            inline=False,
        )

        embed.set_footer(
            text="StockWatcher Quantitative Validation Engine"
        )
        await ctx.send(embed=embed)



@bot.command(name="help")
async def help_cmd(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="📈 STOCKWATCHER COMMANDS",
        description="## Geünformeerd Handelsplatform & Risicobeheer",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="💼 Portfolio & Account",
        value=(
            "`!connect <username>` — Link Discord ID met custom CLI username\n"
            "`!add <ticker> <total_paid> <buy_price>` — Voeg positie toe\n"
            "`!remove <ticker> [shares]` — Verwijder (gedeeltelijke) positie\n"
            "`!portfolio` — Toon totale waarde en P/L in €"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔍 Watchlist & Scanning",
        value=(
            "`!watch <ticker>` — Voeg ticker toe aan scanner\n"
            "`!unwatch <ticker>` — Verwijder ticker uit scanner\n"
            "`!watchlist` — Bekijk gemonitorde tickers\n"
            "`!scan` — Voer handmatige signaalscan uit over watchlist"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Signalen & Quant Analyse",
        value=(
            "`!check <ticker>` — Toon live koers & indicatoren\n"
            "`!kelly <win_rate> <win_loss_ratio>` — Bereken optimale positiegrootte\n"
            "`!montecarlo <kapitaal> <dag_rendement%> <volatiliteit%> [dagen]` — Voer portfolio simulatie uit\n"
            "`!accuracy` — Toon historische model accuraatheid"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ Alert Instellingen",
        value=(
            "`!threshold` — Bekijk huidige prijs-spike drempelwaarde\n"
            "`!setalert <percent>` — Stel drempelwaarde in\n"
            "`!testalert` — Stuur een test-alert naar het kanaal"
        ),
        inline=False,
    )
    embed.set_footer(text="Signalen zijn geen financieel advies. • Alle prijzen in EUR")
    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx: commands.Context) -> None:
    await ctx.send("Pong! 🏓")


@bot.command(name="connect")
async def connect_account(ctx: commands.Context, username: str) -> None:
    clean_username = username.strip().lower()
    portfolio.link_discord_account(str(ctx.author.id), clean_username)
    embed = discord.Embed(
        title="🔗 ACCOUNT CONNECTED",
        description=f"## Gebruiker Gekoppeld\nSuccesvol **{ctx.author.name}** gelinkt aan CLI username **`{clean_username}`**!",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed)


@bot.command(name="add")
async def add_cmd(ctx: commands.Context, ticker: str, total_paid: str, buy_price: str) -> None:
    try:
        total_paid_num = _parse_float(total_paid)
        buy_price_num = _parse_float(buy_price)

        user_id = portfolio.resolve_user_id(str(ctx.author.id))
        portfolio.add_holding(user_id, ticker, total_paid_num, buy_price_num)
        shares = total_paid_num / buy_price_num

        embed = discord.Embed(
            title="✅ POSITIE TOEGEVOEGD",
            description=(
                f"## {ticker.upper()}\n"
                f"```diff\n"
                f"+ Totaal Ingelegd: € {total_paid_num:.2f}\n"
                f"+ Aankoopkoers:    € {buy_price_num:.2f} / aandeel\n"
                f"+ Aantal Aandelen: {shares:.4f} stuks\n"
                f"```"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)
    except ValueError:
        await ctx.send("⚠️ Ongeldige getallen ingevoerd. Voorbeeld: `!add AAPL 75 309,12`")
    except Exception as e:
        await ctx.send(f"⚠️ Fout bij toevoegen: {e}")


@bot.command(name="remove")
async def remove_cmd(ctx: commands.Context, ticker: str, shares: str = None) -> None:
    try:
        user_id = portfolio.resolve_user_id(str(ctx.author.id))
        shares_num = _parse_float(shares) if shares is not None else None
        if portfolio.remove_holding(user_id, ticker, shares_num):
            removed_str = f"`{shares_num}` aandelen van" if shares_num is not None else "alle aandelen van"
            await ctx.send(f"🗑️ Succesvol {removed_str} **{ticker.upper()}** verwijderd uit portfolio.")
        else:
            await ctx.send(f"⚠️ Geen openstaande positie voor **{ticker.upper()}** gevonden.")
    except Exception as e:
        await ctx.send(f"❌ Fout bij verwijderen positie: {e}")


@bot.command(name="portfolio")
async def show_portfolio(ctx: commands.Context) -> None:
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    holdings = portfolio.get_portfolio(user_id)
    if not holdings:
        await ctx.send("💼 Portfolio is momenteel leeg. Gebruik `!add` om posities toe te voegen.")
        return

    embed = discord.Embed(
        title="💼 PORTFOLIO OVERZICHT",
        description="## Live Waarde & Rendement (EUR)\nOverzicht van al je openstaande aandelen en ETF posities.",
        color=discord.Color.blue(),
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

        diff_symbol = "+" if pl >= 0 else "-"
        field_title = f"📈 {display_name}"
        field_body = (
            f"```diff\n"
            f"{diff_symbol} Rendement: € {pl:+.2f} ({pl_pct:+.2f}%)\n"
            f"  Huidige Waarde: € {val:.2f} (Ingelegd: € {cost:.2f})\n"
            f"  Aantal Aandelen: {shares:.4f} stuks\n"
            f"  Aankoopkoers: € {buy_p:.2f} ➔ Nu: € {curr_p:.2f}\n"
            f"```"
        )
        embed.add_field(name=field_title, value=field_body, inline=False)

    total_pl = total_val - total_cost
    total_pl_pct = (total_pl / total_cost * 100.0) if total_cost > 0 else 0.0
    tot_diff = "+" if total_pl >= 0 else "-"

    summary_body = (
        f"```diff\n"
        f"{tot_diff} TOTAAL RENDEMENT: € {total_pl:+.2f} ({total_pl_pct:+.2f}%)\n"
        f"  Totale Portfoliowaarde: € {total_val:.2f}\n"
        f"  Totaal Geïnvesteerd:    € {total_cost:.2f}\n"
        f"```"
    )
    embed.add_field(name="📊 TOTAAL OVERZICHT", value=summary_body, inline=False)
    embed.set_footer(text="StockWatcher Portfolio Management • Trade Republic Sync")
    await ctx.send(embed=embed)


@bot.command()
async def watch(ctx: commands.Context, ticker: str) -> None:
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    await asyncio.to_thread(alerts.add_watchlist, user_id, ticker)
    await ctx.send(f"✅ **{ticker.upper()}** toegevoegd aan watchlist.")


@bot.command()
async def unwatch(ctx: commands.Context, ticker: str) -> None:
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    await asyncio.to_thread(alerts.remove_watchlist, user_id, ticker)
    await ctx.send(f"✅ **{ticker.upper()}** verwijderd uit watchlist.")


@bot.command()
async def watchlist(ctx: commands.Context) -> None:
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    tickers = await asyncio.to_thread(alerts.get_watchlist, user_id)
    if not tickers:
        await ctx.send("Watchlist is leeg. Voeg tickers toe via `!watch TICKER`.")
    else:
        await ctx.send(f"📋 **Watchlist**: {', '.join(tickers)}")


@bot.command(name="scan")
async def scan_watchlist(ctx: commands.Context) -> None:
    user_id = portfolio.resolve_user_id(str(ctx.author.id))
    watchlist_items = alerts.get_watchlist(user_id)
    if not watchlist_items:
        await ctx.send("⚠️ Watchlist is leeg. Voeg tickers toe met `!watch TICKER`.")
        return

    async with ctx.typing():
        embed = discord.Embed(
            title="🔍 TECHNISCHE ANALYSE SCAN",
            description="## Watchlist Markt Overzicht (EUR)",
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

                diff_sym = "+" if pct >= 0 else "-"
                field_name = f"📈 {display_n}"
                field_value = (
                    f"```diff\n"
                    f"{diff_sym} Koers: € {price:.2f} ({pct:+.2f}%)\n"
                    f"  Advies Verdict: {verdict}\n"
                    f"```\n"
                    f"• **RSI:** `{res.get('rsi', 0.0):.1f}` | **EMA20:** `€{res.get('ema20', price):.2f}`\n"
                    f"• **Redenen:** {', '.join(res.get('reasons', [])[:2])}"
                )
                embed.add_field(name=field_name, value=field_value, inline=False)
            except Exception as e:
                embed.add_field(
                    name=f"⚠️ {get_display_name(ticker)}",
                    value=f"Fout bij scannen: {e}",
                    inline=False,
                )

        embed.set_footer(text="StockWatcher Technical Analysis Engine")
        await ctx.send(embed=embed)


@bot.command(name="check")
async def check_ticker(ctx: commands.Context, ticker: str) -> None:
    async with ctx.typing():
        try:
            res = signals.analyze_ticker(ticker)
            display_n = res.get("display_name") or get_display_name(ticker)
            price = res.get("price", 0.0)
            pct = res.get("pct_change", 0.0)
            verdict = res.get("verdict", "NEUTRAL ⚖️")

            embed = discord.Embed(
                title=f"🔍 TECHNISCHE ANALYSE: {display_n}",
                description=(
                    f"## Huidige Koers: € {price:.2f} (`{pct:+.2f}%`)\n"
                    f"### Advies Verdict: **{verdict}**"
                ),
                color=discord.Color.green() if pct >= 0 else discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="📊 Technische Indicatoren",
                value=(
                    f"```yaml\n"
                    f"RSI (14):        {res.get('rsi', 0.0):.1f}\n"
                    f"EMA (20):        € {res.get('ema20', price):.2f}\n"
                    f"ATR (14):        € {res.get('atr', 0.0):.2f}\n"
                    f"```"
                ),
                inline=False,
            )
            embed.add_field(
                name="📋 Signaal Redenen",
                value="\n".join([f"• **{r}**" for r in res.get("reasons", [])]) or "Geen specifieke signalen",
                inline=False,
            )
            embed.set_footer(text="StockWatcher Technical Analysis Engine")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Fout bij het analyseren van {ticker}: {e}")


@bot.command(name="kelly")
async def kelly_cmd(ctx: commands.Context, win_rate: str, win_loss_ratio: str) -> None:
    try:
        w_rate = _parse_float(win_rate)
        wl_ratio = _parse_float(win_loss_ratio)

        if w_rate > 1.0:
            w_rate = w_rate / 100.0

        fraction = quant.calculate_kelly_criterion(w_rate, wl_ratio)
        pct = fraction * 100.0

        embed = discord.Embed(
            title="🎲 KELLY-CRITERIUM RISICO ADVIES",
            description=f"## Optimaal Inzetpercentage: **`{pct:.2f}%`** van je vermogen",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="📊 Invoerparameters & Uitkomst",
            value=(
                f"```yaml\n"
                f"Winstkans Schatting:  {w_rate * 100.0:.1f}%\n"
                f"Risk/Reward Ratio:   {wl_ratio:.2f}\n"
                f"Kelly Fraction:      {fraction:.4f}\n"
                f"Aanbevolen Positie:  {pct:.2f}%\n"
                f"```"
            ),
            inline=False,
        )
        embed.set_footer(text="StockWatcher Quantitative Engine • Position Sizing")
        await ctx.send(embed=embed)
    except ValueError as e:
        await ctx.send(f"⚠️ Invoerfout: {e}")
    except Exception as e:
        await ctx.send(f"❌ Fout bij berekening: {e}")


@bot.command(name="montecarlo")
async def montecarlo_cmd(ctx: commands.Context, capital: str, daily_return_pct: str, volatility_pct: str, days: int = 252) -> None:
    async with ctx.typing():
        try:
            start_cap = _parse_float(capital)
            ret = _parse_float(daily_return_pct) / 100.0
            vol = _parse_float(volatility_pct) / 100.0

            res = quant.run_monte_carlo_simulation(start_cap, ret, vol, days=int(days))

            embed = discord.Embed(
                title=f"🎲 MONTE CARLO SIMULATIE ({days} HANDELSDAGEN)",
                description=f"## Startkapitaal: € {start_cap:.2f}\nSimulatie uitgevoerd over 1.000 willekeurige marktscenario's.",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(
                name="📈 Verwacht Eindvermogen Statistieken",
                value=(
                    f"```yaml\n"
                    f"Gemiddelde:          € {res['mean_final']:.2f}\n"
                    f"Mediaan:             € {res['median_final']:.2f}\n"
                    f"95% Betrouwbaar:     € {res['percentile_5']:.2f} tot € {res['percentile_95']:.2f}\n"
                    f"Slechtste Scenario:  € {res['worst_case']:.2f}\n"
                    f"Beste Scenario:      € {res['best_case']:.2f}\n"
                    f"```"
                ),
                inline=False,
            )
            embed.set_footer(text="StockWatcher Stochastic Engine • Risk Analysis")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Fout bij het uitvoeren van Monte Carlo-simulatie: {e}")


@bot.command(name="testalert")
@commands.has_permissions(administrator=True)
async def test_alert_cmd(ctx: commands.Context) -> None:
    target_channel = (
        bot.get_channel(ALERT_CHANNEL_ID or LOG_CHANNEL_ID)
        if (ALERT_CHANNEL_ID or LOG_CHANNEL_ID)
        else ctx.channel
    )

    if not target_channel:
        await ctx.send("⚠️ Geen alert of log kanaal gevonden/ingesteld.")
        return

    spike_embed = discord.Embed(
        title="🚀 PRICE SPIKE DETECTED",
        description=(
            "## Apple Inc. (APC.DE)\n"
            "De koers stijgt krachtig buiten de ingestelde drempelwaarde!\n\n"
            "```diff\n"
            "+ Verandering: +5.20%\n"
            "+ Oude Koers:  € 309.12\n"
            "+ Nieuwe Koers: € 325.20\n"
            "```"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    spike_embed.add_field(
        name="📊 Markt Details",
        value="• **Drempelwaarde:** `±2.0%`\n• **Status:** Actieve markt-uitbraak",
        inline=False,
    )
    spike_embed.set_footer(text="StockWatcher Real-Time Scanner • Trading Alert")

    warning_embed = discord.Embed(
        title="🚨 QUANT EARLY WARNING ALERT",
        description=(
            "## Vanguard FTSE All-World (VWCE.DE)\n"
            "Er is een marktpatroon gedetecteerd **vóór** de daadwerkelijke koersuitbraak!\n\n"
            "### ⚠️ Signaal Analyse\n"
            "• **Bollinger Squeeze:** Volatiliteit is extreem laag opgedroogd.\n"
            "• **Huidige Koers:** `€ 170.00` (`+0.45%`)"
        ),
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    warning_embed.add_field(
        name="🎲 Quant Risicobeheer & Position Sizing",
        value=(
            "```yaml\n"
            "Portfoliowaarde:     € 150.37\n"
            "Winstkans Schatting: 62.0%\n"
            "Dynamische RRR:      1.10\n"
            "Tail Risk (CVaR 95): 1.68%\n"
            "Max 1% Risico-Inzet: € 37.59 (0.2211 stuks)\n"
            "Stop-Loss Koers:     € 98.00\n"
            "```"
        ),
        inline=False,
    )
    warning_embed.add_field(
        name="🎯 ACTIE ADVIES",
        value="### **BUY 🟢 (Koopsignaal / Bodem inzicht)**",
        inline=False,
    )
    warning_embed.set_footer(text="Reageer met een emoji op dit bericht om alerts voor 3 uur te pauzeren • StockWatcher Engine")

    await target_channel.send(embed=spike_embed)
    await target_channel.send(embed=warning_embed)

    if target_channel.id != ctx.channel.id:
        await ctx.send(f"✅ Grote test alerts succesvol verzonden naar <#{target_channel.id}>!")


class CLIContext:
    def __init__(self, user_id: str):
        resolved_id = portfolio.resolve_user_id(user_id)
        self.author = type("User", (), {"id": resolved_id, "name": user_id})()

    async def send(self, content: str = None, embed: discord.Embed = None) -> None:
        if content:
            print(f"🤖 {content}")
        if embed:
            print(f"\n--- {embed.title} ---")
            if embed.description:
                print(embed.description)
            for field in embed.fields:
                print(f"• {field.name}:\n  {field.value}")
            print("-" * 40)

    @asynccontextmanager
    async def typing(self) -> AsyncGenerator[None, None]:
        # Cleanly yields an empty async context for CLI commands
        yield


async def execute_unified_command(user_id: str, command_line: str) -> None:
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