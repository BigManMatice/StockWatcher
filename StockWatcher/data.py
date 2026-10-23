import sqlite3
from contextlib import closing
from datetime import date, datetime
import pandas as pd
import requests
import config


class DataError(Exception):
    """Custom exception for data fetching errors."""

    pass


def _connect():
    return sqlite3.connect("bot_database.db")


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                ticker TEXT,
                date TEXT,
                close REAL,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fx (
                pair TEXT PRIMARY KEY,
                rate REAL NOT NULL,
                fetched_on TEXT NOT NULL
            )
            """
        )


# --- FMP (USD/EUR Rate) ---


def get_usd_eur() -> float:
    """Fetch USD->EUR exchange rate, cached daily in SQLite."""
    init_db()
    today = date.today().isoformat()

    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT rate, fetched_on FROM fx WHERE pair = 'USDEUR'"
        ).fetchone()

    if row and row[1] == today:
        return row[0]

    url = f"https://financialmodelingprep.com/api/v3/quote/EURUSD?apikey={config.FMP_KEY}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data or not isinstance(data, list):
            raise DataError("FMP returned invalid FX data.")

        eur_usd_rate = float(data[0]["price"])
        usd_eur_rate = 1.0 / eur_usd_rate

    except Exception:
        if row:  # Fallback to last saved rate if API fails/limits
            return row[0]
        # Default fallback rate if brand new & API fails
        usd_eur_rate = 0.89

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO fx (pair, rate, fetched_on) VALUES ('USDEUR', ?, ?)",
            (usd_eur_rate, today),
        )

    return usd_eur_rate


# --- FINNHUB (Real-time Quotes + Local Database Storage) ---


def get_finnhub_quote(ticker: str) -> dict:
    """Fetch current real-time price from Finnhub and log it to SQLite."""
    ticker = ticker.upper().strip()
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={config.FINNHUB_KEY}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        res = resp.json()

        price = float(res.get("c", 0))
        prev_close = float(res.get("pc", 0))

        if price == 0:
            raise DataError(f"Invalid ticker or zero price returned for '{ticker}'")

        pct_change = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

        # Save today's price to our local database history
        today = date.today().isoformat()
        init_db()
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                (ticker, today, price),
            )

        return {
            "ticker": ticker,
            "price": price,
            "prev_close": prev_close,
            "pct_change": pct_change,
        }
    except Exception as e:
        raise DataError(f"Failed to fetch quote for {ticker}: {e}")


def get_daily(ticker: str) -> pd.DataFrame:
    """Return DataFrame (index=date, column=close in EUR) built from local SQLite history.

    If today's price isn't in SQLite yet, it pulls from Finnhub to populate it.
    """
    ticker = ticker.upper().strip()
    init_db()

    # Trigger a quote fetch to ensure today's price is recorded locally
    try:
        get_finnhub_quote(ticker)
    except DataError:
        pass  # Use existing history if offline

    with closing(_connect()) as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            conn,
            params=(ticker,),
            parse_dates=["date"],
            index_col="date",
        )

    if df.empty:
        raise DataError(f"No price history found in database for '{ticker}'.")

    # Convert stored USD closes to EUR before returning
    eur_rate = get_usd_eur()
    df["close"] = df["close"] * eur_rate

    return df