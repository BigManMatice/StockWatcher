# tracker.py
import sqlite3
from datetime import datetime, timedelta
import data

DB_FILE = "alerts_history.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()


init_db()


def log_alert(ticker: str, signal_type: str, action: str, price: float):
    """Slaat een nieuw verstuurde alert op in de geschiedenis."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alert_history (timestamp, ticker, signal_type, action, price_at_alert)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.utcnow(), ticker, signal_type, action, price))
    conn.commit()
    conn.close()


def update_alert_outcomes():
    """Controleert historische alerts en werkt de resultaten bij (1d, 3d, 7d)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Haal geopende alerts op die ouder zijn dan 24 uur
    cursor.execute("SELECT id, ticker, action, price_at_alert, timestamp FROM alert_history WHERE is_winner IS NULL")
    open_alerts = cursor.fetchall()

    now = datetime.utcnow()

    for alert_id, ticker, action, entry_price, ts_str in open_alerts:
        ts = datetime.fromisoformat(str(ts_str))
        age_days = (now - ts).days

        if age_days >= 1:
            try:
                quote = data.get_finnhub_quote(ticker)
                curr_price = float(quote["price"])
                
                # Bepaal of het signaal correct was
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
    conn.close()


def get_accuracy_stats(signal_type: str = None) -> dict:
    """Berekent het zekerheidspercentage van de bot uit het verleden."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if signal_type:
        cursor.execute("SELECT is_winner FROM alert_history WHERE is_winner IS NOT NULL AND signal_type = ?", (signal_type,))
    else:
        cursor.execute("SELECT is_winner FROM alert_history WHERE is_winner IS NOT NULL")

    results = [row[0] for row in cursor.fetchall()]
    conn.close()

    total = len(results)
    if total == 0:
        return {"win_rate": 0.55, "total": 0, "wins": 0, "accuracy_pct": 55.0}

    wins = sum(results)
    win_rate = wins / total
    return {
        "win_rate": win_rate,
        "total": total,
        "wins": wins,
        "accuracy_pct": win_rate * 100.0,
    }