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

def test_get_portfolio_total():
    # Zorg dat de database geinitialiseerd is
    data.init_db()
    
    # Test of de functie een float teruggeeft (geen crash of type-fout)
    username = "matice"
    total = portfolio.get_portfolio_total(username)
    
    assert isinstance(total, (int, float)), "De totale portfoliowaarde moet een getal zijn."
    assert total >= 0.0, "De portfoliowaarde kan niet negatief zijn."
    print(f"Test geslaagd! Totale waarde voor {username}: €{total}")

def test_resolve_user_id_mapping():
    # Test of resolve_user_id correct omgaat met de custom_username of fallback
    data.init_db()
    username = "matice"
    resolved_id = portfolio.resolve_user_id(username)
    
    assert resolved_id is not None, "De resolved_id mag niet None zijn."
    print(f"Resolved ID voor {username} is: {resolved_id}")