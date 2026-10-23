import time
from contextlib import closing
from datetime import date

import data
import portfolio
import signals

FETCH_BUDGET = 15  # max API calls per scan (leaves room for manual !check)
FETCH_DELAY = 13   # seconds between API calls, the free tier also limits per minute


def init_alerts_db():
    with closing(data._connect()) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS signal_state (
                ticker TEXT PRIMARY KEY,
                signal TEXT NOT NULL,
                updated_on TEXT NOT NULL
            )"""
        )


def add_watch(ticker):
    """Returns True if newly added, False if already on the list."""
    init_alerts_db()
    with closing(data._connect()) as conn, conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker) VALUES (?)",
            (ticker.upper().strip(),),
        )
        return cur.rowcount > 0


def remove_watch(ticker):
    init_alerts_db()
    with closing(data._connect()) as conn, conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE ticker = ?", (ticker.upper().strip(),)
        )
        return cur.rowcount > 0


def get_watchlist():
    init_alerts_db()
    with closing(data._connect()) as conn:
        return [r[0] for r in conn.execute("SELECT ticker FROM watchlist ORDER BY ticker")]


def _held_tickers():
    portfolio.init_portfolio_db()
    with closing(data._connect()) as conn:
        return [r[0] for r in conn.execute("SELECT ticker FROM holdings")]


def _get_state(ticker):
    with closing(data._connect()) as conn:
        row = conn.execute(
            "SELECT signal FROM signal_state WHERE ticker = ?", (ticker,)
        ).fetchone()
    return row[0] if row else None


def _set_state(ticker, signal):
    with closing(data._connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO signal_state (ticker, signal, updated_on) VALUES (?, ?, ?)",
            (ticker, signal, date.today().isoformat()),
        )


def scan():
    """Check holdings + watchlist. Returns (alerts, skipped, errors).
    An alert is a NEW buy/sell signal that differs from the last one stored."""
    init_alerts_db()
    held = set(_held_tickers())
    tickers = sorted(held | set(get_watchlist()))

    alerts, skipped, errors = [], [], []
    fetches = 0
    for t in tickers:
        if data.needs_fetch(t):
            if fetches >= FETCH_BUDGET:
                skipped.append(t)
                continue
            if fetches > 0:
                time.sleep(FETCH_DELAY)
            fetches += 1
        try:
            df = data.get_daily(t)
        except data.DataError as e:
            errors.append((t, str(e)))
            continue

        res = signals.analyze(df)
        new = res["signal"]
        old = _get_state(t)
        _set_state(t, new)
        if new != old and new in ("buy", "sell"):
            alerts.append({"ticker": t, "held": t in held, **res})
    return alerts, skipped, errors
