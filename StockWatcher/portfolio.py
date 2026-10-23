from contextlib import closing

import data


def init_portfolio_db():
    with closing(data._connect()) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS holdings (
                ticker TEXT PRIMARY KEY,
                shares REAL NOT NULL,
                buy_price REAL NOT NULL
            )"""
        )


def add_holding(ticker, shares, buy_price):
    """Add a position. If you already hold the ticker, merge them
    and keep a weighted-average buy price."""
    ticker = ticker.upper().strip()
    if shares <= 0 or buy_price <= 0:
        raise ValueError("Shares and price must be positive.")
    init_portfolio_db()

    with closing(data._connect()) as conn, conn:
        row = conn.execute(
            "SELECT shares, buy_price FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row:
            old_shares, old_price = row
            total = old_shares + shares
            avg = (old_shares * old_price + shares * buy_price) / total
            conn.execute(
                "UPDATE holdings SET shares = ?, buy_price = ? WHERE ticker = ?",
                (total, avg, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO holdings (ticker, shares, buy_price) VALUES (?, ?, ?)",
                (ticker, shares, buy_price),
            )


def remove_holding(ticker, shares=None):
    """Remove a whole position, or just some shares. Returns False if not held."""
    ticker = ticker.upper().strip()
    init_portfolio_db()

    with closing(data._connect()) as conn, conn:
        row = conn.execute(
            "SELECT shares FROM holdings WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not row:
            return False
        if shares is None or shares >= row[0]:
            conn.execute("DELETE FROM holdings WHERE ticker = ?", (ticker,))
        else:
            conn.execute(
                "UPDATE holdings SET shares = ? WHERE ticker = ?",
                (row[0] - shares, ticker),
            )
        return True


def get_portfolio():
    """Holdings with value and profit/loss in EUR. Buy prices are entered in EUR."""
    init_portfolio_db()
    with closing(data._connect()) as conn:
        rows = conn.execute(
            "SELECT ticker, shares, buy_price FROM holdings ORDER BY ticker"
        ).fetchall()

    try:
        fx = data.get_usd_eur()
    except data.DataError as e:
        return [
            {"ticker": t, "shares": s, "buy_price": b, "price": None, "error": str(e)}
            for t, s, b in rows
        ]

    result = []
    for ticker, shares, buy_price in rows:
        item = {"ticker": ticker, "shares": shares, "buy_price": buy_price}
        try:
            price = float(data.get_daily(ticker)["close"].iloc[-1]) * fx
        except data.DataError as e:
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
            pl_pct=(value - cost) / cost * 100,
        )
        result.append(item)
    return result