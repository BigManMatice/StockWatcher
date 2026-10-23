import argparse
import io
import os
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
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
                    self.log_widget.app.call_from_thread(self.log_widget.write_line, line)
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            line = self._buffer.strip()
            if threading.get_ident() == self.log_widget.app._thread_id:
                self.log_widget.write_line(line)
            else:
                self.log_widget.app.call_from_thread(self.log_widget.write_line, line)
            self._buffer = ""


class DashboardApp(App):
    """Terminal Dashboard for StonksBot with Complete Command Hub Controls"""

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

        # Quadrant 1: System Status
        yield Static("", classes="box", id="status")

        # Quadrant 2: Live Watchlist Quick View
        yield Static(
            "📈 [bold yellow]Watchlist Quick View[/bold yellow]\nLoading tickers...",
            classes="box",
            id="watchlist",
        )

        # Quadrant 3: Live Terminal Logs & Command Output
        yield Log(classes="box", id="log_window")

        # Quadrant 4: Interactive Command Center & Controls
        with Container(classes="box", id="controls"):
            yield Static("⚙️ [bold cyan]Command & Alert Hub[/bold cyan]")

            # Set Threshold Input
            with Horizontal(classes="control-row"):
                yield Input(placeholder="Set Alert % (e.g. 1.5)", id="input_threshold", value="2.0")
                yield Button("Set Threshold", id="btn_set_threshold", variant="success")

            # Custom Bot Command Input
            with Horizontal(classes="control-row"):
                yield Input(placeholder="Type command (e.g. !add AAPL 500 170)", id="input_cmd")
                yield Button("Run Command", id="btn_run_cmd", variant="primary")

            # Quick Action Buttons
            with Horizontal(classes="control-row"):
                yield Button("💼 Portfolio", id="btn_portfolio", variant="default")
                yield Button("🔍 Scan Watchlist", id="btn_scan", variant="primary")

            with Horizontal(classes="control-row"):
                yield Button("📊 Refresh View", id="btn_refresh", variant="default")
                yield Button("❌ Exit Dashboard", id="btn_exit", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        """Runs when dashboard launches."""
        log_widget = self.query_one("#log_window", Log)
        log_widget.write_line("🚀 Dashboard Command Hub Initialized.")

        sys.stdout = LogRedirector(log_widget)

        self.update_status_view()
        self.update_watchlist_view()

        # Auto-refresh UI status and prices every 60 seconds
        self.set_interval(60.0, self.update_watchlist_view)
        self.set_interval(60.0, self.update_status_view)

    def update_status_view(self) -> None:
        """Update system status widget with active threshold."""
        threshold = getattr(bot, "SPIKE_THRESHOLD_PCT", 2.0)
        status_text = (
            "📊 [bold green]System Status[/bold green]\n"
            "• Discord Bot: Active\n"
            "• Database: Connected\n"
            "• Scanner Interval: 1 min\n"
            f"• Alert Threshold: [bold yellow]±{threshold:.1f}%[/bold yellow]"
        )
        self.query_one("#status", Static).update(status_text)

    def update_watchlist_view(self) -> None:
        """Fetch live ticker prices and update the UI box."""
        watchlist = ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]
        lines = ["📈 [bold yellow]Watchlist Quick View[/bold yellow]"]

        for ticker in watchlist:
            try:
                quote = data.get_finnhub_quote(ticker)
                p = quote["price"]
                pct = quote["pct_change"]
                color = "green" if pct >= 0 else "red"
                lines.append(f"• {ticker:<8} €{p:.2f} [{color}]({pct:+.2f}%)[/{color}]")
            except Exception as e:
                lines.append(f"• {ticker:<8} [red]Error[/red]")

        self.query_one("#watchlist", Static).update("\n".join(lines))

    def execute_custom_command(self, cmd_text: str) -> None:
        """Parse and execute CLI commands with detailed portfolio breakdown in UI."""
        cmd_text = cmd_text.strip()
        if not cmd_text:
            return

        parts = cmd_text.split()
        cmd = parts[0].lower()

        print(f"💻 [UI Command]: {cmd_text}")

        # Help command
        if cmd in ("!help", "help"):
            print(
                "📜 [Available CLI Commands]\n"
                "• `!portfolio` — Show current holdings, values, and total P/L\n"
                "• `!add <ticker> <total_paid> <buy_price>` — Add stock position (e.g. `!add AAPL 500 172.30`)\n"
                "• `!remove <ticker> [shares]` — Remove whole or partial position (e.g. `!remove AAPL`)\n"
                "• `!check <ticker>` — Run price & indicator check on ticker\n"
                "• `!scan` — Run signal scan across watchlist\n"
                "• `!threshold` — View active alert percentage"
            )

        # Portfolio command
        elif cmd == "!portfolio":
            try:
                positions = []
                if hasattr(portfolio, "get_positions"):
                    positions = portfolio.get_positions()
                elif hasattr(portfolio, "load_portfolio"):
                    positions = portfolio.load_portfolio()
                
                if not positions:
                    print("💼 Portfolio is currently empty. Add positions using `!add <ticker> <paid_eur> <buy_price>`.")
                    return

                print("\n💼 [PORTFOLIO SUMMARY]")
                print("-" * 55)
                print(f"{'Ticker':<8} | {'Shares':<8} | {'Avg Price':<10} | {'Current':<10} | {'P/L (€)':<10}")
                print("-" * 55)

                total_val = 0.0
                total_cost = 0.0

                for item in positions:
                    if isinstance(item, dict):
                        ticker = item.get("ticker", "UNKNOWN").upper()
                        shares = float(item.get("shares", 0))
                        buy_price = float(item.get("buy_price", 0))
                        paid = float(item.get("total_paid", shares * buy_price))
                    elif isinstance(item, (list, tuple)) and len(item) >= 3:
                        ticker, shares, buy_price = item[0].upper(), float(item[1]), float(item[2])
                        paid = shares * buy_price
                    else:
                        continue

                    # Fetch live market price
                    try:
                        quote = data.get_finnhub_quote(ticker)
                        curr_price = float(quote.get("price", buy_price))
                    except Exception:
                        curr_price = buy_price

                    curr_val = shares * curr_price
                    pl = curr_val - paid
                    
                    total_val += curr_val
                    total_cost += paid

                    print(f"{ticker:<8} | {shares:<8.2f} | €{buy_price:<9.2f} | €{curr_price:<9.2f} | €{pl:<+9.2f}")

                total_pl = total_val - total_cost
                total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0.0

                print("-" * 55)
                print(f"Total Value: €{total_val:.2f} | Total P/L: €{total_pl:+.2f} ({total_pl_pct:+.2f}%)\n")

            except Exception as e:
                print(f"❌ Portfolio Error: {e}")

        # Add position command
        elif cmd == "!add":
            if len(parts) < 4:
                print("⚠️ Usage: `!add <ticker> <total_paid> <buy_price>` (e.g. `!add AAPL 500 172.30`)")
            else:
                ticker = parts[1].upper()
                try:
                    total_paid = float(parts[2])
                    buy_price = float(parts[3])
                    shares = total_paid / buy_price

                    if hasattr(portfolio, "add_position"):
                        portfolio.add_position(ticker, total_paid, buy_price)

                    print(f"\n✅ [POSITION ADDED]")
                    print(f"• Ticker: {ticker}")
                    print(f"• Total Paid: €{total_paid:.2f}")
                    print(f"• Buy Price: €{buy_price:.2f} / share")
                    print(f"• Shares Acquired: {shares:.4f}\n")

                    # Automatically refresh portfolio view
                    self.execute_custom_command("!portfolio")

                except ValueError:
                    print("⚠️ Invalid numerical inputs for total_paid or buy_price.")
                except Exception as e:
                    print(f"❌ Failed to add position: {e}")

        # Remove position command
        elif cmd == "!remove":
            if len(parts) < 2:
                print("⚠️ Usage: `!remove <ticker> [shares]` (e.g. `!remove AAPL` or `!remove AAPL 2`)")
            else:
                ticker = parts[1].upper()
                shares = float(parts[2]) if len(parts) >= 3 else None
                try:
                    if hasattr(portfolio, "remove_position"):
                        portfolio.remove_position(ticker, shares)

                    removed_str = f"{shares} shares of" if shares else "all shares of"
                    print(f"🗑️ Removed {removed_str} {ticker} from portfolio.")
                    
                    # Refresh portfolio view
                    self.execute_custom_command("!portfolio")
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
                    print(f"🔍 {ticker}: €{res.get('price', 0.0):.2f} | Verdict: {res.get('verdict', 'N/A')}")
                except Exception as e:
                    print(f"❌ Check failed for {ticker}: {e}")

        # Scan command
        elif cmd == "!scan":
            print("🔍 Running manual signal scan across watchlist...")
            for t in ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]:
                try:
                    res = signals.analyze_ticker(t)
                    print(f"-> {t}: {res['verdict']}")
                except Exception as e:
                    print(f"❌ {t} scan failed: {e}")

        # Threshold view command
        elif cmd == "!threshold":
            t = getattr(bot, "SPIKE_THRESHOLD_PCT", 2.0)
            print(f"⚙️ Current Alert Threshold: ±{t}%")

        else:
            print(f"⚠️ Command '{cmd}' not recognized. Type `!help` to view valid commands.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle UI button interactions."""
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
                print("⚠️ Invalid number format. Please enter a valid float (e.g. 1.5).")

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