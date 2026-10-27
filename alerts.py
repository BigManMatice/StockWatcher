from contextlib import closing
from typing import List, Tuple, Any, Optional
import data
import portfolio
import signals


def add_watchlist(user_identifier: str, ticker: Optional[str] = None) -> None:
    if ticker is None:
        ticker = user_identifier
        user_identifier = "default_user"

    data.init_db()
    user_id = portfolio.resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (user_id, ticker) VALUES (?, ?)",
            (user_id, ticker),
        )


def remove_watchlist(user_identifier: str, ticker: Optional[str] = None) -> None:
    if ticker is None:
        ticker = user_identifier
        user_identifier = "default_user"

    data.init_db()
    user_id = portfolio.resolve_user_id(user_identifier)
    ticker = ticker.upper().strip()
    with closing(data._connect()) as conn, conn:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )


def get_watchlist(user_identifier: str = "default_user") -> List[str]:
    data.init_db()
    user_id = portfolio.resolve_user_id(user_identifier)
    with closing(data._connect()) as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]


def get_all_global_watchlists() -> List[str]:
    data.init_db()
    with closing(data._connect()) as conn:
        rows = conn.execute("SELECT DISTINCT ticker FROM watchlist ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def scan(user_identifier: str = "default_user") -> Tuple[List[Any], List[Any], List[Tuple[str, str]]]:
    data.init_db()

    try:
        data.get_usd_eur()
    except data.DataError as e:
        return [], [], [("USD/EUR", str(e))]

    tickers = get_watchlist(user_identifier)
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