# tests/test_portfolio.py
from contextlib import closing
import pytest

import data
import portfolio


def test_portfolio_full_lifecycle():
    user = "test_qa_user"

    data.init_db()
    with closing(data._connect()) as conn, conn:
        conn.execute("DELETE FROM holdings WHERE user_id IN (?, '123456789')", (user,))

    portfolio.link_discord_account("123456789", "test_qa_user")
    assert portfolio.resolve_user_id("test_qa_user") == "123456789"

    portfolio.add_holding(user, "AAPL", total_paid=500.0, buy_price=250.0)
    portfolio.add_holding(user, "AAPL", total_paid=500.0, buy_price=250.0)

    holdings = portfolio.get_portfolio(user)
    assert len(holdings) == 1
    assert holdings[0]["shares"] == 4.0

    assert portfolio.remove_holding(user, "AAPL", shares=1.0) is True
    assert portfolio.get_portfolio(user)[0]["shares"] == 3.0

    assert portfolio.remove_holding(user, "AAPL") is True
    assert len(portfolio.get_portfolio(user)) == 0

    assert portfolio.remove_holding(user, "NON_EXISTENT") is False

    with pytest.raises(ValueError):
        portfolio.add_holding(user, "AAPL", total_paid=-100, buy_price=10)