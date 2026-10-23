import sqlite3
from contextlib import closing
from datetime import date
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
        if row:  # Fallback to last saved rate if API fails
            return row[0]
        usd_eur_rate = 0.89  # Default safe fallback rate

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO fx (pair, rate, fetched_on) VALUES ('USDEUR', ?, ?)",
            (usd_eur_rate, today),
        )

    return usd_eur_rate


# --- QUOTE FETCHING (Finnhub with FMP Fallback) ---


def _fetch_fmp_quote(ticker: str) -> dict:
    """Fallback: Fetch current price from Financial Modeling Prep."""
    url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={config.FMP_KEY}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data or not isinstance(data, list):
        raise DataError(f"No price data found on FMP for '{ticker}'")

    item = data[0]
    price = float(item.get("price", 0))
    prev_close = float(item.get("previousClose", price))

    if price == 0:
        raise DataError(f"FMP returned zero price for '{ticker}'")

    pct_change = float(item.get("changesPercentage", 0))

    return {
        "ticker": ticker,
        "price": price,
        "prev_close": prev_close,
        "pct_change": pct_change,
    }


def get_finnhub_quote(ticker: str) -> dict:
    """Fetch real-time price from Finnhub, falling back automatically to FMP if Finnhub fails."""
    ticker = ticker.upper().strip()
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={config.FINNHUB_KEY}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        res = resp.json()

        price = float(res.get("c", 0))
        prev_close = float(res.get("pc", 0))

        # If Finnhub returns 0 (missing symbol/European ETF), try FMP fallback
        if price == 0:
            return _fetch_fmp_quote(ticker)

        pct_change = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

        quote_data = {
            "ticker": ticker,
            "price": price,
            "prev_close": prev_close,
            "pct_change": pct_change,
        }

    except Exception:
        # Finnhub failed completely -> Use FMP as fallback
        quote_data = _fetch_fmp_quote(ticker)

    # Save today's price to local SQLite history
    today = date.today().isoformat()
    init_db()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            (ticker, today, quote_data["price"]),
        )

    return quote_data


def get_daily(ticker: str) -> pd.DataFrame:
    """Return DataFrame (index=date, column=close in EUR) from local SQLite history.

    Populates today's price automatically using Finnhub/FMP if not yet saved.
    """
    ticker = ticker.upper().strip()
    init_db()

    # Trigger quote fetch to store/update today's price locally
    try:
        get_finnhub_quote(ticker)
    except DataError:
        pass

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

    # If European ticker with suffix (.DE, .LS, .AS, .L), price is ALREADY in EUR
    is_european_ticker = any(ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"])

    if not is_european_ticker:
        # Convert US USD stock price to EUR
        eur_rate = get_usd_eur()
        df["close"] = df["close"] * eur_rate

    return df