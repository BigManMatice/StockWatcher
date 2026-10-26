# tests/test_alerts.py
from unittest.mock import patch
import alerts
import data


def test_alerts_and_watchlist_scan():
    alerts.add_watchlist("test_qa_user", "APC.DE")
    assert "APC.DE" in alerts.get_watchlist("test_qa_user")

    buy_alerts, sell_alerts, errors = alerts.scan("test_qa_user")
    assert isinstance(buy_alerts, list)
    assert isinstance(sell_alerts, list)

    alerts.remove_watchlist("test_qa_user", "APC.DE")
    assert "APC.DE" not in alerts.get_watchlist("test_qa_user")

    with patch("data.get_usd_eur", side_effect=data.DataError("Mock USD/EUR failure")):
        b, s, errs = alerts.scan("test_qa_user")
        assert len(errs) > 0