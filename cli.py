import argparse
import io
import os
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Button, Footer, Header, Log, Static

# Ensure relative module resolution
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import data
import signals


class LogRedirector(io.TextIOBase):
    """Redirects sys.stdout calls to the Textual Log widget."""

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
                # Post log line safely on Textual's main thread
                self.log_widget.app.call_from_thread(self.log_widget.write_line, line)
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            self.log_widget.app.call_from_thread(
                self.log_widget.write_line, self._buffer
            )
            self._buffer = ""


class DashboardApp(App):
    """Terminal Dashboard for StonksBot with Live Terminal Logs"""

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
        content-align: center middle;
    }
    Button {
        margin: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Quadrant 1: System Status
        yield Static(
            "📊 [bold green]System Status[/bold green]\n• Discord Bot: Active\n• Database: Connected\n• Scanner: Every 1 min",
            classes="box",
            id="status",
        )

        # Quadrant 2: Live Watchlist Quick View
        yield Static(
            "📈 [bold yellow]Watchlist Quick View[/bold yellow]\nLoading tickers...",
            classes="box",
            id="watchlist",
        )

        # Quadrant 3: Live Terminal Print Stream
        yield Log(classes="box", id="log_window")

        # Quadrant 4: Interactive Controls
        with Container(classes="box", id="controls"):
            yield Button("🔍 Run Signal Scan", id="btn_scan", variant="primary")
            yield Button("📊 Refresh Watchlist", id="btn_refresh", variant="default")
            yield Button("❌ Exit Dashboard", id="btn_exit", variant="error")

        yield Footer()

    def on_mount(self) -> None:
            """Runs when dashboard launches—redirects stdout and starts auto-refresh timer."""
            log_widget = self.query_one("#log_window", Log)
            log_widget.write_line("🚀 Dashboard Initialized. Hooking stdout...")

            # 1. Redirect standard stdout to write directly into Textual log
            sys.stdout = LogRedirector(log_widget)

            # 2. Initial watchlist load
            self.update_watchlist_view()

            # 3. Automatically refresh UI watchlist every 60 seconds
            self.set_interval(60.0, self.update_watchlist_view)

    def update_watchlist_view(self) -> None:
        """Fetch live ticker prices and update the UI box"""
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle dashboard button interactions"""
        if event.button.id == "btn_scan":
            print("🔍 Triggering manual signal scan from CLI...")
            for ticker in ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]:
                try:
                    res = signals.analyze_ticker(ticker)
                    print(f"-> {ticker}: {res['verdict']}")
                except Exception as e:
                    print(f"❌ {ticker} scan failed: {e}")

        elif event.button.id == "btn_refresh":
            print("🔄 Refreshing watchlist display...")
            self.update_watchlist_view()

        elif event.button.id == "btn_exit":
            self.exit()


def start_bot_background():
    """Start Discord bot process in background thread"""
    import main


def main_cli():
    parser = argparse.ArgumentParser(description="StonksBot Terminal Dashboard")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("start", help="Start Bot with CMD UI Dashboard")
    subparsers.add_parser("cli-only", help="Start without UI (standard raw stdout)")

    args = parser.parse_args()

    if args.command == "start" or args.command is None:
        # Start Discord Bot in background
        bot_thread = threading.Thread(target=start_bot_background, daemon=True)
        bot_thread.start()

        # Launch Textual TUI Dashboard
        app = DashboardApp()
        app.run()

    elif args.command == "cli-only":
        import main


if __name__ == "__main__":
    main_cli()