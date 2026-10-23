import sqlite3
from contextlib import closing
from datetime import date
import pandas as pd
import requests
import yfinance as yf
import config

# Import mapping function from stockName.py
from stockName import get_mapped_ticker


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


# Inside data.py
from stockName import get_mapped_ticker

def get_finnhub_quote(ticker: str) -> dict:
    """Fetches Euro quote via yfinance/APIs using mapped ticker, saving as original ticker."""
    original_ticker = ticker.upper().strip()
    api_ticker = get_mapped_ticker(original_ticker)

    quote_data = None

    # European / Exchange-suffixed tickers query yfinance
    is_european = any(
        api_ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    if is_european:
        try:
            quote_data = _fetch_yfinance_quote(api_ticker)
        except Exception:
            pass

    # Fallback to Finnhub / FMP if yfinance fails
    if not quote_data:
        try:
            quote_data = _fetch_fmp_quote(api_ticker)
        except Exception:
            try:
                quote_data = _fetch_yfinance_quote(api_ticker)
            except Exception as e:
                raise DataError(f"Could not fetch quote for '{original_ticker}' ({api_ticker}): {e}")

    # Set ticker key back to standard name (e.g., AAPL)
    quote_data["ticker"] = original_ticker

    # Save snapshot into SQLite under standard name ('AAPL')
    today = date.today().isoformat()
    init_db()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            (original_ticker, today, quote_data["price"]),
        )

    return quote_data


def get_daily(ticker: str) -> pd.DataFrame:
    """Return DataFrame from local SQLite history, automatically backfilling 1y history via yfinance if needed."""
    ticker = ticker.upper().strip()
    api_ticker = get_mapped_ticker(ticker)
    init_db()

    # 1. Query local SQLite database
    with closing(_connect()) as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            conn,
            params=(ticker,),
            parse_dates=["date"],
            index_col="date",
        )

    # 2. Backfill 1 year of daily history if database has fewer than 20 rows
    if len(df) < 20:
        try:
            stock = yf.Ticker(api_ticker)
            hist = stock.history(period="1y")

            if not hist.empty:
                records = []
                for dt, row in hist.iterrows():
                    d_str = dt.strftime("%Y-%m-%d")
                    records.append((ticker, d_str, float(row["Close"])))

                # Batch insert missing historical snapshots
                with closing(_connect()) as conn, conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                        records,
                    )

                # Re-query SQLite to get the updated history
                with closing(_connect()) as conn:
                    df = pd.read_sql_query(
                        "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
                        conn,
                        params=(ticker,),
                        parse_dates=["date"],
                        index_col="date",
                    )
        except Exception as e:
            print(f"[History Backfill Error] Could not backfill '{ticker}': {e}")

    if df.empty:
        raise DataError(f"No price history found in database for '{ticker}'.")

    # 3. Convert USD to EUR if this is a standard US ticker (no European suffix)
    is_european = any(
        api_ticker.endswith(ext)
        for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    if not is_european:
        eur_rate = get_usd_eur()
        df["close"] = df["close"] * eur_rate

    return df