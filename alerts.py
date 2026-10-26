from contextlib import closing
import data
import signals


def add_watchlist(ticker: str):
    data.init_db()
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO watchlist (ticker) VALUES (?)", (ticker,))


def remove_watchlist(ticker: str):
    data.init_db()
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))


def get_watchlist() -> list:
    data.init_db()
    with closing(data._connect()) as conn:
        rows = conn.execute("SELECT ticker FROM watchlist ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def scan():
    data.init_db()

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
            verdict = res.get("verdict", "")
            if "BULLISH" in verdict:
                buy_alerts.append(res)
            elif "BEARISH" in verdict:
                sell_alerts.append(res)
        except Exception as e:
            errors.append((ticker, str(e)))

    return buy_alerts, sell_alerts, errors