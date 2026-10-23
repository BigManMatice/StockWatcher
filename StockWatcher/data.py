import sqlite3
from contextlib import closing
from datetime import date
import pandas as pd
import requests
import yfinance as yf
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


# --- FX RATES (USD -> EUR) ---


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

    # Primary: yfinance EUR/USD
    try:
        eurusd = yf.Ticker("EURUSD=X").fast_info["lastPrice"]
        usd_eur_rate = 1.0 / float(eurusd)
    except Exception:
        # Fallback: FMP API
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/EURUSD?apikey={config.FMP_KEY}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            usd_eur_rate = 1.0 / float(data[0]["price"])
        except Exception:
            if row:
                return row[0]
            usd_eur_rate = 0.89  # Default fallback rate

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO fx (pair, rate, fetched_on) VALUES ('USDEUR', ?, ?)",
            (usd_eur_rate, today),
        )

    return usd_eur_rate


# --- QUOTE FETCHING PROVIDERS ---


def _fetch_yfinance_quote(ticker: str) -> dict:
    """Fetch live price directly via Yahoo Finance (native European ETF support)."""
    stock = yf.Ticker(ticker)
    info = stock.fast_info

    price = float(info.get("lastPrice", 0) or 0)
    prev_close = float(info.get("previousClose", price) or price)

    if price == 0:
        raise DataError(f"yfinance returned zero price for '{ticker}'")

    pct_change = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

    return {
        "ticker": ticker,
        "price": price,
        "prev_close": prev_close,
        "pct_change": pct_change,
    }


def _fetch_fmp_quote(ticker: str) -> dict:
    """Fetch current price from Financial Modeling Prep."""
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
    """Multi-provider quote fetcher: yfinance (for EU tickers) -> Finnhub -> FMP -> yfinance."""
    ticker = ticker.upper().strip()
    quote_data = None

    is_european = any(
        ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    # 1. European tickers query yfinance directly first
    if is_european:
        try:
            quote_data = _fetch_yfinance_quote(ticker)
        except Exception:
            pass

    # 2. Try Finnhub for standard tickers
    if not quote_data:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={config.FINNHUB_KEY}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            res = resp.json()

            price = float(res.get("c", 0))
            prev_close = float(res.get("pc", 0))

            if price > 0:
                pct_change = (
                    ((price - prev_close) / prev_close) * 100
                    if prev_close > 0
                    else 0.0
                )
                quote_data = {
                    "ticker": ticker,
                    "price": price,
                    "prev_close": prev_close,
                    "pct_change": pct_change,
                }
        except Exception:
            pass

    # 3. Try FMP
    if not quote_data:
        try:
            quote_data = _fetch_fmp_quote(ticker)
        except Exception:
            pass

    # 4. Final fallback to yfinance
    if not quote_data:
        try:
            quote_data = _fetch_yfinance_quote(ticker)
        except Exception as e:
            raise DataError(f"Could not fetch quote for '{ticker}': {e}")

    # Save snapshot to SQLite history
    today = date.today().isoformat()
    init_db()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            (ticker, today, quote_data["price"]),
        )

    return quote_data


def get_daily(ticker: str) -> pd.DataFrame:
    """Return DataFrame from local SQLite history."""
    ticker = ticker.upper().strip()
    init_db()

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

    # If US stock (no European suffix), convert USD to EUR
    is_european = any(
        ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    if not is_european:
        eur_rate = get_usd_eur()
        df["close"] = df["close"] * eur_rate

    return df