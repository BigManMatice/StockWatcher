import sqlite3
from contextlib import closing
from datetime import date
from typing import Dict, Any
import pandas as pd
import requests
import yfinance as yf
import config
from stockName import get_mapped_ticker


class DataError(Exception):
    """Custom exception for data fetching errors."""
    pass


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(config.DB_PATH)


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL NOT NULL,
                volume REAL,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        
        cursor = conn.execute("PRAGMA table_info(prices)")
        existing_cols = [c[1] for c in cursor.fetchall()]
        for col_name in ["open", "high", "low", "volume"]:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE prices ADD COLUMN {col_name} REAL")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fx (
                pair TEXT PRIMARY KEY,
                rate REAL NOT NULL,
                fetched_on TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id TEXT NOT NULL DEFAULT 'default_user',
                ticker TEXT NOT NULL,
                PRIMARY KEY (user_id, ticker)
            )
            """
        )
        
        cursor = conn.execute("PRAGMA table_info(watchlist)")
        w_cols = [c[1] for c in cursor.fetchall()]
        if "user_id" not in w_cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN user_id TEXT DEFAULT 'default_user'")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS holdings (
                user_id TEXT NOT NULL DEFAULT 'default_user',
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                buy_price REAL NOT NULL,
                PRIMARY KEY (user_id, ticker)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_links (
                custom_username TEXT PRIMARY KEY,
                discord_id TEXT NOT NULL UNIQUE
            )
            """
        )


def get_usd_eur() -> float:
    init_db()
    today = date.today().isoformat()

    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT rate, fetched_on FROM fx WHERE pair = 'USDEUR'"
        ).fetchone()

    if row and row[1] == today:
        return float(row[0])

    try:
        eurusd = yf.Ticker("EURUSD=X").fast_info["lastPrice"]
        usd_eur_rate = 1.0 / float(eurusd)
    except Exception:
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/EURUSD?apikey={config.FMP_KEY}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data_json = resp.json()
            usd_eur_rate = 1.0 / float(data_json[0]["price"])
        except Exception:
            if row:
                return float(row[0])
            usd_eur_rate = 0.89

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO fx (pair, rate, fetched_on) VALUES ('USDEUR', ?, ?)",
            (usd_eur_rate, today),
        )

    return usd_eur_rate


def _fetch_yfinance_quote(ticker: str) -> Dict[str, Any]:
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        price = float(info.get("lastPrice", 0) or 0)
        prev_close = float(info.get("previousClose", price) or price)
    except Exception as e:
        raise DataError(f"yfinance failed for ticker '{ticker}': {e}")

    if price == 0:
        raise DataError(f"yfinance returned zero price for '{ticker}'")

    pct_change = ((price - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0

    return {
        "ticker": ticker,
        "price": price,
        "prev_close": prev_close,
        "pct_change": pct_change,
    }


def _fetch_fmp_quote(ticker: str) -> Dict[str, Any]:
    try:
        url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={config.FMP_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data_json = resp.json()
    except Exception as e:
        raise DataError(f"FMP failed for ticker '{ticker}': {e}")

    if not data_json or not isinstance(data_json, list):
        raise DataError(f"No price data found on FMP for '{ticker}'")

    item = data_json[0]
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


def get_finnhub_quote(ticker: str) -> Dict[str, Any]:
    original_ticker = ticker.upper().strip()
    api_ticker = get_mapped_ticker(original_ticker)

    quote_data = None
    is_european = any(
        api_ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    if is_european:
        try:
            quote_data = _fetch_yfinance_quote(api_ticker)
        except Exception:
            pass

    if not quote_data:
        try:
            quote_data = _fetch_fmp_quote(api_ticker)
        except Exception:
            try:
                quote_data = _fetch_yfinance_quote(api_ticker)
            except Exception as e:
                raise DataError(f"Could not fetch quote for '{original_ticker}' ({api_ticker}): {e}")

    quote_data["ticker"] = original_ticker
    today = date.today().isoformat()
    init_db()

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
            (original_ticker, today, quote_data["price"]),
        )

    return quote_data


def get_daily(ticker: str) -> pd.DataFrame:
    ticker = ticker.upper().strip()
    api_ticker = get_mapped_ticker(ticker)
    init_db()

    with closing(_connect()) as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            conn,
            params=(ticker,),
            parse_dates=["date"],
            index_col="date",
        )

    if len(df) < 20 or df["high"].isnull().all():
        try:
            stock = yf.Ticker(api_ticker)
            hist = stock.history(period="1y")

            if not hist.empty:
                records = [
                    (
                        ticker,
                        dt.strftime("%Y-%m-%d"),
                        float(row.get("Open", row["Close"])),
                        float(row.get("High", row["Close"])),
                        float(row.get("Low", row["Close"])),
                        float(row["Close"]),
                        float(row.get("Volume", 0)),
                    )
                    for dt, row in hist.iterrows()
                ]

                with closing(_connect()) as conn, conn:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        records,
                    )

                with closing(_connect()) as conn:
                    df = pd.read_sql_query(
                        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
                        conn,
                        params=(ticker,),
                        parse_dates=["date"],
                        index_col="date",
                    )
        except Exception as e:
            print(f"[History Backfill Error] Could not backfill '{ticker}': {e}")

    if df.empty:
        raise DataError(f"No price history found in database for '{ticker}'.")

    is_european = any(
        api_ticker.endswith(ext) for ext in [".DE", ".LS", ".AS", ".L", ".PA", ".MI"]
    )

    if not is_european:
        eur_rate = get_usd_eur()
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] * eur_rate

    return df


def refresh_daily(ticker: str) -> pd.DataFrame:
    """Force-refresh daily OHLCV history from Yahoo Finance."""
    ticker = ticker.upper().strip()
    api_ticker = get_mapped_ticker(ticker)

    history = yf.Ticker(api_ticker).history(
        period="1y",
        interval="1d",
        auto_adjust=True,
        repair=True,
        timeout=15,
    )

    if history.empty:
        raise DataError(f"No fresh daily history available for {ticker}")

    history.columns = [str(column).lower() for column in history.columns]
    history.index = pd.to_datetime(history.index).date

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(history.columns):
        raise DataError(f"Incomplete OHLCV data for {ticker}")

    history = history.dropna(subset=["open", "high", "low", "close"])
    history = history[~history.index.duplicated(keep="last")]

    if history.empty:
        raise DataError(f"No valid daily candles available for {ticker}")

    with _connect() as conn:
        for day, row in history.iterrows():
            conn.execute(
                """
                INSERT OR REPLACE INTO prices
                    (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    day.isoformat(),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(row["volume"]),
                ),
            )

    # Use the same currency normalization as get_daily().
    is_european = api_ticker.endswith(
        (".DE", ".LS", ".AS", ".L", ".PA", ".MI")
    )

    if not is_european:
        rate = get_usd_eur()
        for column in ("open", "high", "low", "close"):
            history[column] = history[column] * rate

    return history
