from contextlib import closing
import data
import signals


def init_alerts_db():
    with closing(data._connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY
            )
            """
        )


def add_watchlist(ticker):
    init_alerts_db()
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (ticker) VALUES (?)", (ticker,)
        )


def remove_watchlist(ticker):
    init_alerts_db()
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))


def get_watchlist():
    init_alerts_db()
    with closing(data._connect()) as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist ORDER BY ticker"
        ).fetchall()
    return [r[0] for r in rows]


def scan():
    init_alerts_db()

    # Fail cleanly early if USD/EUR rate cannot be fetched
    try:
        data.get_usd_eur()
    except data.DataError as e:
        return [], [], [("USD/EUR", str(e))]

    tickers = get_watchlist()
    buy_alerts = []
    sell_alerts = []
    errors = []

    for ticker in tickers:
        try:
            res = signals.analyze_ticker(ticker)
            if res["signal"] == "BUY":
                buy_alerts.append(res)
            elif res["signal"] == "SELL":
                sell_alerts.append(res)
        except Exception as e:
            errors.append((ticker, str(e)))

    return buy_alerts, sell_alerts, errors