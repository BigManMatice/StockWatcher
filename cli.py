# cli.py
import argparse
import asyncio
import io
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Footer, Header, Input, Log, Static

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
    if CACHE_FILE.exists():
        try:
            user = CACHE_FILE.read_text(encoding="utf-8").strip()
            if user:
                return user
        except Exception:
            pass
    return "default_user"


def set_cached_user(user_id: str) -> None:
    try:
        CACHE_FILE.write_text(str(user_id).strip(), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ Failed to cache active user: {e}")


class LogRedirector(io.TextIOBase):
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
                try:
                    if threading.get_ident() == self.log_widget.app._thread_id:
                        self.log_widget.write_line(line)
                    else:
                        self.log_widget.app.call_from_thread(self.log_widget.write_line, line)
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            line = self._buffer.strip()
            try:
                if threading.get_ident() == self.log_widget.app._thread_id:
                    self.log_widget.write_line(line)
                else:
                    self.log_widget.app.call_from_thread(self.log_widget.write_line, line)
            except Exception:
                pass
            self._buffer = ""


class DashboardApp(App):
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
                    placeholder="Set Alert % (e.g. 0.1)",
                    id="input_threshold",
                    value="2.0",
                )
                yield Button("Set Threshold", id="btn_set_threshold", variant="success")

            with Horizontal(classes="control-row"):
                yield Input(placeholder="Type command (e.g. !check AAPL)", id="input_cmd")
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
        sys.stdout = LogRedirector(log_widget)
        print("🚀 Dashboard Command Hub Initialized.")

        self.update_status_view()
        self.update_watchlist_view()

        self.set_interval(60.0, self.update_watchlist_view)
        self.set_interval(60.0, self.update_status_view)

    def update_status_view(self) -> None:
        threshold = getattr(bot, "SPIKE_THRESHOLD_PCT", 2.0)
        bot_status = "🟢 Connected" if bot.bot.is_ready() else "🟡 Connecting..."
        status_text = (
            "📊 [bold green]System Status[/bold green]\n"
            f"• Active Account: [bold cyan]{self.active_user_id}[/bold cyan] (Cached)\n"
            f"• Discord Bot: {bot_status}\n"
            "• Database: Connected\n"
            f"• Alert Threshold: [bold yellow]±{threshold:.1f}%[/bold yellow]"
        )
        self.query_one("#status", Static).update(status_text)

    def update_watchlist_view(self) -> None:
        user_watchlist = alerts.get_watchlist(self.active_user_id) or ["APC.DE", "MSF.DE", "NVD.DE", "SXR8.DE"]
        lines = [f"📈 [bold yellow]Watchlist Quick View ({self.active_user_id})[/bold yellow]"]

        for ticker in user_watchlist:
            try:
                quote = data.get_finnhub_quote(ticker)
                p = quote["price"]
                pct = quote["pct_change"]
                color = "green" if pct >= 0 else "red"
                lines.append(f"• {ticker:<8} €{p:.2f} [{color}]({pct:+.2f}%)[/{color}]")
            except Exception:
                lines.append(f"• {ticker:<8} [red]Error[/red]")

        self.query_one("#watchlist", Static).update("\n".join(lines))

    def run_async_command(self, cmd_text: str):
        coro = bot.execute_unified_command(self.active_user_id, cmd_text)
        try:
            running_loop = asyncio.get_running_loop()
            running_loop.create_task(coro)
        except RuntimeError:
            try:
                loop = getattr(bot.bot, "_loop", None) or asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(coro, loop)
            except Exception:
                asyncio.run(coro)

    def execute_custom_command(self, cmd_text: str) -> None:
        cmd_text = cmd_text.strip()
        if not cmd_text:
            return

        parts = cmd_text.split()
        cmd = parts[0].lower()

        if cmd == "!login":
            if len(parts) < 2:
                print(f"⚠️ Usage: `!login <user_id>` (Current: `{self.active_user_id}`)")
            else:
                self.active_user_id = parts[1]
                set_cached_user(self.active_user_id)
                self.update_status_view()
                self.update_watchlist_view()
                print(f"🔐 Switched active account to: [bold cyan]{self.active_user_id}[/bold cyan]")
                self.run_async_command("!portfolio")
        else:
            self.run_async_command(cmd_text)

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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot.bot.start(config.DISCORD_TOKEN))
    except Exception as e:
        print(f"❌ Discord Bot Connection Error: {e}")


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