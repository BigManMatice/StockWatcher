import sqlite3
from datetime import datetime, timezone
import data

DB_FILE = "alerts_history.db"

def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                ticker TEXT,
                signal_type TEXT,
                action TEXT,
                price_at_alert REAL,
                price_1d REAL,
                price_3d REAL,
                price_7d REAL,
                is_winner INTEGER DEFAULT NULL
            )
        """)
        conn.commit()

init_db()


def log_alert(ticker: str, signal_type: str, action: str, price: float) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO alert_history (timestamp, ticker, signal_type, action, price_at_alert)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc), ticker, signal_type, action, price))
        conn.commit()


def update_alert_outcomes() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, action, price_at_alert, timestamp FROM alert_history WHERE is_winner IS NULL")
        open_alerts = cursor.fetchall()

        now = datetime.now(timezone.utc)

        for alert_id, ticker, action, entry_price, ts_str in open_alerts:
            try:
                ts = datetime.fromisoformat(str(ts_str))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).days

                if age_days >= 1:
                    quote = data.get_finnhub_quote(ticker)
                    curr_price = float(quote["price"])
                    is_buy = "BUY" in action
                    price_diff = curr_price - entry_price

                    is_winner = 1 if (is_buy and price_diff > 0) or (not is_buy and price_diff < 0) else 0

                    cursor.execute("""
                        UPDATE alert_history 
                        SET price_1d = ?, is_winner = ? 
                        WHERE id = ?
                    """, (curr_price, is_winner, alert_id))
            except Exception as e:
                print(f"[Tracker Error] {ticker}: {e}")

        conn.commit()


def get_accuracy_stats(signal_type: str = None) -> dict:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        if signal_type:
            cursor.execute("SELECT is_winner FROM alert_history WHERE is_winner IS NOT NULL AND signal_type = ?", (signal_type,))
        else:
            cursor.execute("SELECT is_winner FROM alert_history WHERE is_winner IS NOT NULL")
        results = [row[0] for row in cursor.fetchall()]

    total = len(results)
    if total == 0:
        return {"win_rate": 0.55, "total": 0, "wins": 0, "accuracy_pct": 55.0}

    wins = sum(results)
    win_rate = wins / total
    return {
        "win_rate": float(win_rate),
        "total": int(total),
        "wins": int(wins),
        "accuracy_pct": float(win_rate * 100.0),
    }