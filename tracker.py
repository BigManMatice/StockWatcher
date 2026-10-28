
import sqlite3
from datetime import date, datetime, timedelta, timezone

import data

DB_FILE = "alerts_history.db"
HORIZONS = (1, 3, 7)
ATR_MULTIPLIER = 1.0
ATR_PERIOD = 14


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)

    return result.astimezone(timezone.utc)


def _parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        return value.date()

    text = str(value).strip()

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def _daily_rows(ticker: str) -> list[dict]:
    """Return normalized daily OHLC rows from data.get_daily()."""
    df = data.get_daily(ticker)

    if df is None or df.empty:
        return []

    rows = []

    for index, row in df.iterrows():
        values = {
            str(key).lower(): value
            for key, value in row.items()
        }

        raw_date = values.get(
            "date",
            values.get(
                "datetime",
                values.get("timestamp", index),
            ),
        )

        try:
            day = _parse_date(raw_date)
            high = float(values["high"])
            low = float(values["low"])
            close = float(values["close"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

        if high <= 0 or low <= 0 or close <= 0 or high < low:
            continue

        rows.append({
            "date": day,
            "high": high,
            "low": low,
            "close": close,
        })

    rows.sort(key=lambda item: item["date"])

    # Keep the last bar if the data source returns duplicate dates.
    unique_rows = {row["date"]: row for row in rows}
    return [unique_rows[day] for day in sorted(unique_rows)]



def _calculate_atr(
    ticker: str,
    alert_time: datetime,
    period: int = 14,
) -> float | None:
    """Calculate ATR from completed daily candles before the alert date."""
    if period < 1:
        return None

    try:
        rows = _daily_rows(ticker)
        alert_date = alert_time.date()

        rows = [
            row for row in rows
            if row["date"] < alert_date
        ]

        if len(rows) < period + 1:
            return None

        true_ranges = []

        for index in range(1, len(rows)):
            current = rows[index]
            previous = rows[index - 1]

            true_range = max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            )

            true_ranges.append(true_range)

        if len(true_ranges) < period:
            return None

        recent_ranges = true_ranges[-period:]
        atr = sum(recent_ranges) / period

        return atr if atr > 0 else None

    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        print(f"[Tracker ATR Error] {ticker}: {exc}")
        return None



def init_db() -> None:
    with _connect() as conn:
        # Bestaande alert_history tabel
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                ticker TEXT,
                signal_type TEXT,
                action TEXT,
                price_at_alert REAL,
                evaluation_price_at_alert REAL,
                price_1d REAL,
                price_3d REAL,
                price_7d REAL,
                is_winner INTEGER DEFAULT NULL
            )
        """)

        # Nieuwe tabel voor actieve posities van gebruikers die een signaal volgen
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                ticker TEXT,
                shares REAL,
                entry_price REAL,
                stop_loss REAL,
                peak_price REAL,
                status TEXT DEFAULT 'OPEN',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migratie check voor alert_history kolommen
        existing = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(alert_history)"
            ).fetchall()
        }

        new_columns = {
            "evaluation_price_at_alert": "REAL",
            "atr_at_alert": "REAL",
            "is_winner_1d": "INTEGER DEFAULT NULL",
            "is_winner_3d": "INTEGER DEFAULT NULL",
            "is_winner_7d": "INTEGER DEFAULT NULL",
        }

        for column, definition in new_columns.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE alert_history "
                    f"ADD COLUMN {column} {definition}"
                )

init_db()



def log_alert(
    ticker: str,
    signal_type: str = None,
    action: str = "HOLD",
    price: float = 0.0,
    atr: float | None = None,
    warning: str = None,
) -> None:
    """Record an alert with its entry price and ATR."""
    timestamp = datetime.now(timezone.utc)
    
    # Ondersteun zowel 'signal_type' als 'warning' als keyword argument
    actual_signal_type = signal_type or warning or "UNKNOWN"

    try:
        price = float(price)
        if price <= 0:
            raise ValueError("Alert price must be positive.")

        evaluation_price = _to_history_currency(price, ticker)

        atr_val = _calculate_atr(ticker, timestamp) if atr is None else atr

        if atr_val is not None:
            atr_val = float(atr_val)
            if atr_val <= 0:
                atr_val = None

    except (TypeError, ValueError) as exc:
        print(f"[Tracker Log Error] {ticker}: {exc}")
        return

    with _connect() as conn:
        conn.execute("""
            INSERT INTO alert_history (
                timestamp,
                ticker,
                signal_type,
                action,
                price_at_alert,
                evaluation_price_at_alert,
                atr_at_alert
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp.isoformat(),
            ticker,
            actual_signal_type,
            action,
            price,
            evaluation_price,
            atr_val,
        ))



def _is_correct(
    action: str,
    entry_price: float,
    exit_price: float,
    atr: float,
) -> int | None:
    """Require a directional price movement of at least one ATR."""
    action = (action or "").upper()

    if entry_price <= 0 or atr <= 0:
        return None

    movement = exit_price - entry_price
    threshold = atr * ATR_MULTIPLIER

    if "BUY" in action:
        return int(movement >= threshold)

    if "SELL" in action:
        return int(movement <= -threshold)

    # HOLD and other non-directional actions are not scored.
    return None



def update_alert_outcomes() -> None:
    """Evaluate alerts independently at 1, 3 and 7 calendar days."""
    now = datetime.now(timezone.utc)
    today = now.date()

    with _connect() as conn:
        alerts = conn.execute("""
            SELECT *
            FROM alert_history
            WHERE is_winner_1d IS NULL
               OR is_winner_3d IS NULL
               OR is_winner_7d IS NULL
        """).fetchall()

        for alert in alerts:
            try:
                alert_time = _parse_datetime(alert["timestamp"])
                ticker = alert["ticker"]
                entry_value = alert["evaluation_price_at_alert"]

                # Older alerts without a normalized entry price cannot
                # be reliably evaluated.
                if not ticker or entry_value is None:
                    continue

                entry_price = float(entry_value)
                if entry_price <= 0:
                    continue

                atr = alert["atr_at_alert"]

                if atr is None or float(atr) <= 0:
                    atr = _calculate_atr(ticker, alert_time)

                    if atr is None:
                        continue

                    conn.execute("""
                        UPDATE alert_history
                        SET atr_at_alert = ?
                        WHERE id = ?
                    """, (atr, alert["id"]))

                atr = float(atr)

                try:
                    data.refresh_daily(ticker)
                except Exception as exc:
                    print(f"[Tracker Refresh Error] {ticker}: {exc}")
                    continue

                rows = [
                    row for row in _daily_rows(ticker)
                    if row["date"] < today
                ]

                if not rows:
                    continue

                for days in HORIZONS:
                    winner_column = f"is_winner_{days}d"
                    price_column = f"price_{days}d"

                    if alert[winner_column] is not None:
                        continue

                    target_date = alert_time.date() + timedelta(days=days)

                    if today < target_date:
                        continue

                    candidates = [
                        row for row in rows
                        if row["date"] >= target_date
                    ]

                    if not candidates:
                        continue

                    # Use the first available completed daily close
                    # on or after the target date.
                    outcome = candidates[0]

                    result = _is_correct(
                        alert["action"],
                        entry_price,
                        outcome["close"],
                        atr,
                    )

                    if result is None:
                        continue

                    conn.execute(
                        f"""
                        UPDATE alert_history
                        SET {price_column} = ?,
                            {winner_column} = ?
                        WHERE id = ?
                        """,
                        (outcome["close"], result, alert["id"]),
                    )

                    # Keep the legacy field aligned with the 1-day result.
                    if days == 1:
                        conn.execute("""
                            UPDATE alert_history
                            SET is_winner = ?
                            WHERE id = ?
                        """, (result, alert["id"]))

            except Exception as exc:
                print(
                    f"[Tracker Error] {alert['ticker']}: {exc}"
                )



def get_accuracy_stats(
    signal_type: str = None,
    horizon: str = "1d",
    warning: str = None,
) -> dict:
    """Return measured accuracy for a specific evaluation horizon."""
    if horizon not in {"1d", "3d", "7d"}:
        raise ValueError("horizon must be '1d', '3d' or '7d'.")

    actual_signal_type = signal_type or warning
    winner_column = f"is_winner_{horizon}"

    with _connect() as conn:
        # Haal het totaal aantal gelogde alerts op voor dit signaaltype
        if actual_signal_type:
            total_logged = conn.execute(
                "SELECT COUNT(*) FROM alert_history WHERE signal_type = ?",
                (actual_signal_type,)
            ).fetchone()[0]
            
            evaluated_rows = [
                row[0] for row in conn.execute(
                    f"SELECT {winner_column} FROM alert_history WHERE signal_type = ? AND {winner_column} IS NOT NULL",
                    (actual_signal_type,)
                ).fetchall()
            ]
        else:
            total_logged = conn.execute(
                "SELECT COUNT(*) FROM alert_history"
            ).fetchone()[0]
            
            evaluated_rows = [
                row[0] for row in conn.execute(
                    f"SELECT {winner_column} FROM alert_history WHERE {winner_column} IS NOT NULL"
                ).fetchall()
            ]

    evaluated_count = len(evaluated_rows)
    wins = sum(evaluated_rows)

    return {
        "horizon": horizon,
        "win_rate": wins / evaluated_count if evaluated_count else 0.0,
        "total": total_logged,  # Totaal geregistreerde alerts (sluit aan op de assert)
        "evaluated": evaluated_count,
        "wins": wins,
        "accuracy_pct": (wins / evaluated_count * 100.0) if evaluated_count else None,
    }

def _is_european_ticker(ticker: str) -> bool:
    api_ticker = data.get_mapped_ticker(ticker.upper().strip())
    return any(
        api_ticker.endswith(ext)
        for ext in (".DE", ".LS", ".AS", ".L", ".PA", ".MI")
    )


def _to_history_currency(price: float, ticker: str) -> float:
    """Convert quote prices to the EUR currency used by data.get_daily()."""
    if _is_european_ticker(ticker):
        return float(price)

    return float(price) * data.get_usd_eur()

def monitor_active_trades() -> list:
    """
    Controleert alle openstaande trades in 'active_trades'.
    Vergelijkt de live koers met stop-loss en piekkoers.
    Retourneert een lijst met actie-meldingen die naar Discord gestuurd moeten worden.
    """
    notifications = []
    
    with _connect() as conn:
        cursor = conn.cursor()
        trades = cursor.execute(
            "SELECT id, user_id, ticker, shares, entry_price, stop_loss, peak_price FROM active_trades WHERE status = 'OPEN'"
        ).fetchall()
        
        for trade in trades:
            trade_id, user_id, ticker, shares, entry_price, stop_loss, peak_price = trade
            
            try:
                # Gebruik de globale data module (zodat monkeypatch in tests werkt)
                quote = data.get_finnhub_quote(ticker)
                current_price = quote["price"]
                
                if peak_price is None or peak_price < entry_price:
                    peak_price = entry_price
                
                # 1. Update de piekprijs als de huidige koers hoger is
                if current_price > peak_price:
                    peak_price = current_price
                    cursor.execute(
                        "UPDATE active_trades SET peak_price = ? WHERE id = ?",
                        (peak_price, trade_id)
                    )
                
                # 2. Check of de Stop-Loss is geraakt
                if current_price <= stop_loss:
                    cursor.execute(
                        "UPDATE active_trades SET status = 'CLOSED_STOP_LOSS' WHERE id = ?",
                        (trade_id,)
                    )
                    pl_eur = (current_price - entry_price) * shares
                    pl_pct = ((current_price - entry_price) / entry_price) * 100.0
                    notifications.append({
                        "type": "STOP_LOSS",
                        "user_id": user_id,
                        "ticker": ticker,
                        "message": (
                            f"🚨 **STOP-LOSS GERAAKT!**\n"
                            f"• **Asset:** `{ticker}`\n"
                            f"• **Huidige Koers:** `€ {current_price:.2f}` (Stop-loss was: `€ {stop_loss:.2f}`)\n"
                            f"• **Resultaat:** `€ {pl_eur:+.2f}` (`{pl_pct:+.2f}%`)\n"
                            f"👉 *Verkoop je positie direct om verdere daling te voorkomen!*"
                        )
                    })
                    continue
                
                # 3. Check voor Winst Pakken (Trailing Drop vanaf de piek)
                gain_from_entry = ((current_price - entry_price) / entry_price) * 100.0
                drop_from_peak = ((peak_price - current_price) / peak_price) * 100.0
                
                if gain_from_entry > 1.5 and drop_from_peak >= 2.0:
                    cursor.execute(
                        "UPDATE active_trades SET status = 'CLOSED_TAKE_PROFIT' WHERE id = ?",
                        (trade_id,)
                    )
                    pl_eur = (current_price - entry_price) * shares
                    notifications.append({
                        "type": "TAKE_PROFIT",
                        "user_id": user_id,
                        "ticker": ticker,
                        "message": (
                            f"🎯 **WINST PAKKEN / TRENDOMSLAG DETECTIE!**\n"
                            f"• **Asset:** `{ticker}`\n"
                            f"• **Piekkoers was:** `€ {peak_price:.2f}` | **Nu:** `€ {current_price:.2f}`\n"
                            f"• **Gerealiseerde winst:** `€ {pl_eur:+.2f}` (`{gain_from_entry:+.2f}%` vanaf instap)\n"
                            f"👉 *De koers trekt terug vanaf de piek. Overweeg je winst veilig te stellen!*"
                        )
                    })
                    
            except Exception as e:
                print(f"[Trade Monitor Error] {ticker}: {e}")
                
        conn.commit()
        
    return notifications