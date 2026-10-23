import argparse
import io
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Footer, Header, Input, Log, Static

# Ensure relative module resolution
sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts
import bot
import config
import data
import portfolio
import signals
from stockName import get_display_name

CACHE_FILE = config.BASE_DIR / "active_user.txt"


def get_cached_user() -> str:
    """Read last logged-in user from cache file."""
    if CACHE_FILE.exists():
        try:
            user = CACHE_FILE.read_text(encoding="utf-8").strip()
            if user:
                return user
        except Exception:
            pass
    return "default_user"


def set_cached_user(user_id: str) -> None:
    """Save active user to cache file."""
    try:
        CACHE_FILE.write_text(str(user_id).strip(), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ Failed to cache active user: {e}")


class LogRedirector(io.TextIOBase):
    """Thread-safe stdout redirector for Textual's Log widget."""

    def __init__(self, log_widget: Log):
        self.log_widget = log_widget
        self._buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                if threading.get_ident() == self.log_widget.app._thread_id:
                    self.log_widget.write_line(line)
                else:
                    self.log_widget.app.call_from_thread(
                        self.log_widget.write_line, line
                    )
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            line = self._buffer.strip()
            if threading.get_ident() == self.log_widget.app._thread_id:
                self.log_widget.write_line(line)
            else:
                self.log_widget.app.call_from_thread(
                    self.log_widget.write_line, line
                )
            self._buffer = ""


class DashboardApp(App):
    """Terminal Dashboard for StonksBot with Persistent Account Caching"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.active_user_id = get_cached_user()

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-rows: 1fr 1fr;
        grid-columns: 1fr 1fr;
    }
    .box {
        border: solid green;
        padding: 1;
        height: 100%;
    }
    #controls {
        layout: vertical;
        overflow-y: scroll;
    }
    .control-row {
        height: auto;
        margin: 1 0;
    }
    Input {
        width: 70%;
    }
    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        yield Static("", classes="box", id="status")
        yield Static(
            "📈 [bold yellow]Watchlist Quick View[/bold yellow]\nLoading tickers...",
            classes="box",
            id="watchlist",
        )
        yield Log(classes="box", id="log_window")

        with Container(classes="box", id="controls"):
            yield Static("⚙️ [bold cyan]Command & Account Hub[/bold cyan]")

            with Horizontal(classes="control-row"):
                yield Input(
                    placeholder="Set Alert % (e.g. 1.5)",
                    id="input_threshold",
                    value="2.0",
                )
                yield Button("Set Threshold", id="btn_set_threshold", variant="success")

            with Horizontal(classes="control-row"):
                yield Input(
                    placeholder="Type command (e.g. !login matic)", id="input_cmd"
                )
                yield Button("Run Command", id="btn_run_cmd", variant="primary")

            with Horizontal(classes="control-row"):
                yield Button("💼 Portfolio", id="btn_portfolio", variant="default")
                yield Button("🔍 Scan Watchlist", id="btn_scan", variant="primary")

            with Horizontal(classes="control-row"):
                yield Button("📊 Refresh View", id="btn_refresh", variant="default")
                yield Button("❌ Exit Dashboard", id="btn_exit", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        log_widget = self.query_one("#log_window", Log)
        log_widget.write_line("🚀 Dashboard Command Hub Initialized.")

        sys.stdout = LogRedirector(log_widget)

        self.update_status_view()
        self.update_watchlist_view()

        self.set_interval(60.0, self.update_watchlist_view)
        self.set_interval(60.0, self.update_status_view)

    def update_status_view(self) -> None:
        threshold = getattr(bot, "SPIKE_THRESHOLD_PCT", 2.0)
        status_text = (
            "📊 [bold green]System Status[/bold green]\n"
            f"• Active Account: [bold cyan]{self.active_user_id}[/bold cyan] (Cached)\n"
            "• Discord Bot: Active\n"
            "• Database: Connected\n"
            f"• Alert Threshold: [bold yellow]±{threshold:.1f}%[/bold yellow]"
        )
        self.query_one("#status", Static).update(status_text)

    def update_watchlist_view(self) -> None:
        watchlist = ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]
        lines = ["📈 [bold yellow]Watchlist Quick View[/bold yellow]"]

        for ticker in watchlist:
            try:
                quote = data.get_finnhub_quote(ticker)
                p = quote["price"]
                pct = quote["pct_change"]
                color = "green" if pct >= 0 else "red"
                lines.append(
                    f"• {ticker:<8} €{p:.2f} [{color}]({pct:+.2f}%)[/{color}]"
                )
            except Exception as e:
                lines.append(f"• {ticker:<8} [red]Error[/red]")

        self.query_one("#watchlist", Static).update("\n".join(lines))

    def execute_custom_command(self, cmd_text: str) -> None:
        cmd_text = cmd_text.strip()
        if not cmd_text:
            return

        parts = cmd_text.split()
        cmd = parts[0].lower()

        print(f"💻 [UI Command]: {cmd_text}")

        # Login command with caching
        if cmd == "!login":
            if len(parts) < 2:
                print(
                    f"⚠️ Usage: `!login <user_id_or_name>` (Current Active: `{self.active_user_id}`)"
                )
            else:
                self.active_user_id = parts[1]
                set_cached_user(self.active_user_id)
                self.update_status_view()
                print(
                    f"🔐 Switched and cached active account to: [bold cyan]{self.active_user_id}[/bold cyan]"
                )
                self.execute_custom_command("!portfolio")

        # Help command
        elif cmd in ("!help", "help"):
            print(
                "📜 [Available CLI Commands]\n"
                "• `!login <user_id>` — Switch active portfolio account (saved to cache)\n"
                "• `!portfolio` — Show active account holdings and total P/L\n"
                "• `!add <ticker> <total_paid> <buy_price>` — Add position (e.g. `!add AAPL 500 172.30`)\n"
                "• `!remove <ticker> [shares]` — Remove whole or partial position\n"
                "• `!check <ticker>` — Run price & indicator check on ticker\n"
                "• `!scan` — Run signal scan across watchlist"
            )

        # Portfolio command
        elif cmd == "!portfolio":
            try:
                holdings = portfolio.get_portfolio(self.active_user_id)
                if not holdings:
                    print(
                        f"💼 Portfolio for account `{self.active_user_id}` is empty. "
                        "Add positions using `!add <ticker> <total_paid> <buy_price>`."
                    )
                    return

                print(f"\n💼 [PORTFOLIO SUMMARY — Account: {self.active_user_id}]")
                print("-" * 62)
                print(
                    f"{'Ticker':<8} | {'Shares':<8} | {'Avg Price':<10} | {'Current':<10} | {'P/L (€)':<10}"
                )
                print("-" * 62)

                total_val = 0.0
                total_cost = 0.0

                for item in holdings:
                    ticker = item["ticker"]
                    shares = item["shares"]
                    buy_price = item["buy_price"]
                    curr_price = item.get("price", buy_price) or buy_price
                    val = item.get("value", shares * curr_price)
                    cost = item.get("cost", shares * buy_price)
                    pl = item.get("pl", val - cost)

                    total_val += val
                    total_cost += cost

                    print(
                        f"{ticker:<8} | {shares:<8.2f} | €{buy_price:<9.2f} | €{curr_price:<9.2f} | €{pl:<+9.2f}"
                    )

                total_pl = total_val - total_cost
                total_pl_pct = (
                    (total_pl / total_cost * 100) if total_cost > 0 else 0.0
                )

                print("-" * 62)
                print(
                    f"Total Value: €{total_val:.2f} | Total P/L: €{total_pl:+.2f} ({total_pl_pct:+.2f}%)\n"
                )

            except Exception as e:
                print(f"❌ Portfolio Error: {e}")

        # Add position command
        elif cmd == "!add":
            if len(parts) < 4:
                print(
                    "⚠️ Usage: `!add <ticker> <total_paid> <buy_price>` (e.g. `!add AAPL 500 172.30`)"
                )
            else:
                ticker = parts[1].upper()
                try:
                    total_paid = float(parts[2])
                    buy_price = float(parts[3])
                    portfolio.add_holding(
                        self.active_user_id, ticker, total_paid, buy_price
                    )

                    print(
                        f"\n✅ [POSITION ADDED] Account: {self.active_user_id}\n"
                        f"• Ticker: {ticker}\n"
                        f"• Total Paid: €{total_paid:.2f}\n"
                        f"• Buy Price: €{buy_price:.2f} / share\n"
                        f"• Shares: {total_paid / buy_price:.4f}\n"
                    )

                    self.execute_custom_command("!portfolio")

                except ValueError:
                    print("⚠️ Total paid and buy price must be valid numbers.")
                except Exception as e:
                    print(f"❌ Failed to add position: {e}")

        # Remove position command
        elif cmd == "!remove":
            if len(parts) < 2:
                print(
                    "⚠️ Usage: `!remove <ticker> [shares]` (e.g. `!remove AAPL` or `!remove AAPL 2`)"
                )
            else:
                ticker = parts[1].upper()
                shares = float(parts[2]) if len(parts) >= 3 else None
                try:
                    success = portfolio.remove_holding(
                        self.active_user_id, ticker, shares
                    )
                    if success:
                        print(
                            f"🗑️ Removed position for {ticker} from account `{self.active_user_id}`."
                        )
                        self.execute_custom_command("!portfolio")
                    else:
                        print(
                            f"⚠️ No open position for {ticker} found in account `{self.active_user_id}`."
                        )
                except Exception as e:
                    print(f"❌ Failed to remove position: {e}")

        # Check / Watch command
        elif cmd in ("!check", "!watch"):
            if len(parts) < 2:
                print("⚠️ Usage: `!check <ticker>` (e.g. `!check TSLA`)")
            else:
                ticker = parts[1].upper()
                try:
                    res = signals.analyze_ticker(ticker)
                    print(
                        f"🔍 {ticker}: €{res.get('price', 0.0):.2f} | Verdict: {res.get('verdict', 'N/A')}"
                    )
                except Exception as e:
                    print(f"❌ Check failed for {ticker}: {e}")

        # Scan command with Rich terminal markup
        elif cmd == "!scan":
            print("🔍 Running manual signal scan across watchlist...")
            for t in ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]:
                try:
                    res = signals.analyze_ticker(t)
                    signal_str = res.get("signal") or res.get("verdict", "N/A")
                    display_n = res.get("display_name") or get_display_name(t)
                    price = res.get("price", 0.0)
                    pct = res.get("pct_change", 0.0)

                    # Determine markup colors
                    if pct >= 0:
                        color_tag = "green"
                        circle = "🟢"
                    else:
                        color_tag = "red"
                        circle = "🔴"

                    # Print formatted line with Rich text styling
                    print(
                        f"-> {circle} [bold]{display_n:<8}[/bold] (€{price:.2f} | [{color_tag}]{pct:+.2f}%[/{color_tag}]): {signal_str}"
                    )
                except Exception as e:
                    print(f"❌ {t} scan failed: {e}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_set_threshold":
            val_str = self.query_one("#input_threshold", Input).value
            try:
                val = float(val_str)
                if val <= 0:
                    print("⚠️ Threshold must be greater than 0.")
                    return
                bot.SPIKE_THRESHOLD_PCT = val
                self.update_status_view()
                print(f"⚙️ Alert threshold updated via UI to ±{val:.2f}%")
            except ValueError:
                print("⚠️ Invalid number format.")

        elif event.button.id == "btn_run_cmd":
            cmd_input = self.query_one("#input_cmd", Input)
            self.execute_custom_command(cmd_input.value)
            cmd_input.value = ""

        elif event.button.id == "btn_portfolio":
            self.execute_custom_command("!portfolio")

        elif event.button.id == "btn_scan":
            self.execute_custom_command("!scan")

        elif event.button.id == "btn_refresh":
            print("🔄 Refreshing display...")
            self.update_watchlist_view()
            self.update_status_view()

        elif event.button.id == "btn_exit":
            self.exit()


def start_bot_background():
    import main


def main_cli():
    parser = argparse.ArgumentParser(description="StonksBot Terminal Dashboard")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("start", help="Start Bot with CMD UI Dashboard")
    subparsers.add_parser("cli-only", help="Start without UI (standard output)")

    args = parser.parse_args()

    if args.command == "start" or args.command is None:
        bot_thread = threading.Thread(target=start_bot_background, daemon=True)
        bot_thread.start()

        app = DashboardApp()
        app.run()

    elif args.command == "cli-only":
        import main


if __name__ == "__main__":
    main_cli()