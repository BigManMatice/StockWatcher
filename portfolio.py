# portfolio.py
from contextlib import closing
import data
from stockName import get_mapped_ticker, get_display_name


def link_discord_account(discord_id: str, custom_username: str):
    data.init_db()
    clean_user = str(custom_username).strip().lower()
    with closing(data._connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO account_links (custom_username, discord_id) VALUES (?, ?)",
            (clean_user, str(discord_id)),
        )


def resolve_user_id(identifier: str) -> str:
    """Translates a CLI custom username into its linked numeric Discord ID (or vice versa)."""
    data.init_db()
    clean_identifier = str(identifier).strip().lower()

    with closing(data._connect()) as conn:
        row = conn.execute(
            "SELECT discord_id FROM account_links WHERE custom_username = ?",
            (clean_identifier,),
        ).fetchone()
        if row:
            return row[0]

        row_user = conn.execute(
            "SELECT custom_username FROM account_links WHERE discord_id = ?",
            (clean_identifier,),
        ).fetchone()
        if row_user:
            return clean_identifier

    return clean_identifier


def add_holding(user_identifier: str, ticker: str, total_paid: float, buy_price: float):
    # Sanitize float inputs if passed as comma-separated strings
    total_paid_val = float(str(total_paid).replace(",", "."))
    buy_price_val = float(str(buy_price).replace(",", "."))

    if total_paid_val <= 0 or buy_price_val <= 0:
        raise ValueError("Total paid and buy price must be positive numbers.")

    data.init_db()
    user_id = resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()
    shares = total_paid_val / buy_price_val

    with closing(data._connect()) as conn:
        row = conn.execute(
            "SELECT shares, buy_price FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()

    if row:
        existing_shares, existing_buy_price = row
        new_shares = existing_shares + shares
        total_cost = (existing_shares * existing_buy_price) + total_paid_val
        new_avg_price = total_cost / new_shares
        with closing(data._connect()) as conn, conn:
            conn.execute(
                "UPDATE holdings SET shares = ?, buy_price = ? WHERE user_id = ? AND ticker = ?",
                (new_shares, new_avg_price, user_id, ticker),
            )
    else:
        with closing(data._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO holdings (user_id, ticker, shares, buy_price) VALUES (?, ?, ?, ?)",
                (user_id, ticker, shares, buy_price_val),
            )


def remove_holding(user_identifier: str, ticker: str, shares: float = None) -> bool:
    data.init_db()
    user_id = resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()

    shares_val = float(str(shares).replace(",", ".")) if shares is not None else None

    with closing(data._connect()) as conn:
        row = conn.execute(
            "SELECT shares FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()

    if not row:
        return False

    current_shares = row[0]

    if shares_val is None or shares_val >= current_shares:
        with closing(data._connect()) as conn, conn:
            conn.execute(
                "DELETE FROM holdings WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            )
    else:
        new_shares = current_shares - shares_val
        with closing(data._connect()) as conn, conn:
            conn.execute(
                "UPDATE holdings SET shares = ? WHERE user_id = ? AND ticker = ?",
                (new_shares, user_id, ticker),
            )

    return True


def get_portfolio_total(user_identifier: str = "default_user") -> float:
    """
    Berekent de totale actuele waarde van het portfolio voor één specifieke gebruiker.
    Accepteert een custom_username of Discord ID (via resolve_user_id).
    """
    portfolio_items = get_portfolio(user_identifier)
    total_value = sum(item.get("value", 0.0) for item in portfolio_items)
    return round(total_value, 2)

def get_portfolio(user_identifier: str) -> list:
    data.init_db()
    user_id = resolve_user_id(user_identifier)

    with closing(data._connect()) as conn:
        rows = conn.execute(
            "SELECT ticker, shares, buy_price FROM holdings WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    portfolio_list = []
    for r in rows:
        ticker, shares, buy_price = r[0], r[1], r[2]
        item = {
            "ticker": ticker,
            "shares": shares,
            "buy_price": buy_price,
            "cost": shares * buy_price,
        }
        try:
            quote = data.get_finnhub_quote(ticker)
            price = quote["price"]
            item["price"] = price
            item["value"] = shares * price
            item["pl"] = item["value"] - item["cost"]
            item["pl_pct"] = (item["pl"] / item["cost"] * 100) if item["cost"] > 0 else 0.0
        except Exception:
            item["price"] = buy_price
            item["value"] = item["cost"]
            item["pl"] = 0.0
            item["pl_pct"] = 0.0

        portfolio_list.append(item)

    return portfolio_list