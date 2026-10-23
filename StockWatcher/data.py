import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd
import requests

import config

DB_PATH = "stockwatcher.db"
API_URL = "https://www.alphavantage.co/query"


class DataError(Exception):
    """Raised when price data can't be fetched."""


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                close REAL NOT NULL,
                PRIMARY KEY (ticker, date)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS fetch_log (
                ticker TEXT PRIMARY KEY,
                fetched_on TEXT NOT NULL
            )"""
        )


def _fetch_from_api(ticker):
    print(f"[data] fetching {ticker} from Alpha Vantage...")
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker,
        "outputsize": "compact",  # last ~100 days
        "apikey": config.ALPHAVANTAGE_KEY,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise DataError(f"Request failed: {e}")

    series = data.get("Time Series (Daily)")
    if not series:
        msg = (
            data.get("Error Message")
            or data.get("Note")
            or data.get("Information")
            or "Unknown API response"
        )
        raise DataError(msg)

    return [(d, float(v["4. close"])) for d, v in series.items()]


def get_daily(ticker):
    """Return a DataFrame (index=date, column=close) for the ticker.
    Only calls the API if we haven't fetched this ticker today."""
    ticker = ticker.upper().strip()
    init_db()
    today = date.today().isoformat()

    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT fetched_on FROM fetch_log WHERE ticker = ?", (ticker,)
        ).fetchone()

    if not row or row[0] != today:
        rows = _fetch_from_api(ticker)
        with closing(_connect()) as conn, conn:
            conn.executemany(
                "INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                [(ticker, d, c) for d, c in rows],
            )
            conn.execute(
                "INSERT OR REPLACE INTO fetch_log (ticker, fetched_on) VALUES (?, ?)",
                (ticker, today),
            )

    with closing(_connect()) as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
            conn,
            params=(ticker,),
            parse_dates=["date"],
            index_col="date",
        )
    return df