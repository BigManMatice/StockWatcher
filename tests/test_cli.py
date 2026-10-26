# tests/test_cli.py
from unittest.mock import patch
import pytest

import cli
import main


def test_cli_cache_and_helpers():
    cli.set_cached_user("test_cache_user")
    assert cli.get_cached_user() == "test_cache_user"


@pytest.mark.asyncio
async def test_cli_dashboard_app():
    app = cli.DashboardApp()
    async with app.run_test() as pilot:
        app.update_status_view()
        app.update_watchlist_view()

        app.execute_custom_command("!login new_user")
        app.execute_custom_command("!portfolio")
        app.execute_custom_command("!scan")
        app.execute_custom_command("!invalid")

        log_widget = app.query_one("#log_window", cli.Log)
        redirector = cli.LogRedirector(log_widget)
        redirector.write("Testing CLI log output\n")
        redirector.flush()


def test_cli_main_entrypoint():
    with patch("sys.argv", ["cli.py", "cli-only"]), \
         patch("main.bot.run"):
        cli.main_cli()


def test_main_import_and_logging():
    assert main.bot is not None