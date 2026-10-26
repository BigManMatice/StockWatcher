from contextlib import closing
import data


def resolve_user_id(identifier: str) -> str:
    data.init_db()
    identifier_clean = str(identifier).strip().lower()

    with closing(data._connect()) as conn:
        row = conn.execute(
            "SELECT discord_id FROM account_links WHERE custom_username = ?",
            (identifier_clean,),
        ).fetchone()
        return row[0] if row else identifier_clean


def link_discord_account(discord_id: str, custom_username: str):
    data.init_db()
    username = custom_username.strip().lower()
    discord_id = str(discord_id)

    with closing(data._connect()) as conn, conn:
        conn.execute(
            """INSERT INTO account_links (custom_username, discord_id) 
               VALUES (?, ?) 
               ON CONFLICT(custom_username) DO UPDATE SET discord_id = excluded.discord_id""",
            (username, discord_id),
        )


def add_holding(user_identifier, ticker, total_paid, buy_price):
    user_id = resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()
    total_paid = float(total_paid)
    buy_price = float(buy_price)

    if total_paid <= 0 or buy_price <= 0:
        raise ValueError("Total paid and buy price must be positive.")

    shares = total_paid / buy_price
    data.init_db()

    with closing(data._connect()) as conn, conn:
        row = conn.execute(
            "SELECT shares, buy_price FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()

        if row:
            old_shares, old_price = row
            total_shares = old_shares + shares
            avg_price = (old_shares * old_price + total_paid) / total_shares
            conn.execute(
                "UPDATE holdings SET shares = ?, buy_price = ? WHERE user_id = ? AND ticker = ?",
                (total_shares, avg_price, user_id, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO holdings (user_id, ticker, shares, buy_price) VALUES (?, ?, ?, ?)",
                (user_id, ticker, shares, buy_price),
            )


def remove_holding(user_identifier, ticker, shares=None):
    user_id = resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()
    data.init_db()

    with closing(data._connect()) as conn, conn:
        row = conn.execute(
            "SELECT shares FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()

        if not row:
            return False

        if shares is None or shares >= row[0]:
            conn.execute(
                "DELETE FROM holdings WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            )
        else:
            conn.execute(
                "UPDATE holdings SET shares = ? WHERE user_id = ? AND ticker = ?",
                (row[0] - shares, user_id, ticker),
            )
        return True


def get_portfolio(user_identifier):
    user_id = resolve_user_id(user_identifier)
    data.init_db()

    with closing(data._connect()) as conn:
        rows = conn.execute(
            "SELECT ticker, shares, buy_price FROM holdings WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        ).fetchall()

    result = []
    for ticker, shares, buy_price in rows:
        item = {"ticker": ticker, "shares": shares, "buy_price": buy_price}
        try:
            quote = data.get_finnhub_quote(ticker)
            price = float(quote.get("price", buy_price))
        except Exception:
            try:
                price = float(data.get_daily(ticker)["close"].iloc[-1])
            except Exception as e:
                item.update(price=None, error=str(e))
                result.append(item)
                continue

        cost = shares * buy_price
        value = shares * price
        item.update(
            price=price,
            value=value,
            cost=cost,
            pl=value - cost,
            pl_pct=(value - cost) / cost * 100 if cost > 0 else 0.0,
        )
        result.append(item)
    return result