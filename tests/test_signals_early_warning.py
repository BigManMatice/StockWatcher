# tests/test_signals_early_warning.py
import pandas as pd
import signals


def test_detect_early_warnings():
    dates = pd.date_range(start="2025-01-01", periods=30, freq="D")
    # Maak een dataframe met extreem lage volatiliteit (Squeeze)
    df = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [100.1] * 30,
            "low": [99.9] * 30,
            "close": [100.0] * 30,
        },
        index=dates,
    )

    warnings = signals.detect_early_warnings(df, current_price=100.0)
    assert isinstance(warnings, list)
    assert len(warnings) > 0
    assert any("Bollinger Squeeze" in w for w in warnings)

import os
import sqlite3
import pytest
from datetime import datetime, timezone

# Importeer de modules die we willen testen
import tracker

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    """
    Fixture die voor elke test een schone, tijdelijke SQLite database opzet,
    zodatstests elkaars data niet beïnvloeden.
    """
    test_db = tmp_path / "test_stockwatcher.db"
    
    # Monkeypatch de DB_FILE in tracker zodat deze naar onze testdatabase wijst
    monkeypatch.setattr(tracker, "DB_FILE", str(test_db))
    
    # Initialiseer de tabellen
    tracker.init_db()
    yield
    # Cleanup gebeurt automatisch door pytest via tmp_path

def test_init_db_creates_tables():
    """Controleer of alle vereiste tabellen succesvol worden aangemaakt."""
    with sqlite3.connect(tracker.DB_FILE) as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "alert_history" in tables
        assert "active_trades" in tables

def test_log_alert_and_stats():
    """Test of alerts correct worden gelogd en opgeslagen in de database."""
    # Log een test alert
    tracker.log_alert(
        ticker="TEST.DE",
        warning="Bollinger Squeeze",
        action="BUY",
        price=100.0,
        atr=2.5
    )
    
    # Controleer of de statistieken opgehaald kunnen worden
    stats = tracker.get_accuracy_stats(warning="Bollinger Squeeze", horizon="1d")
    assert stats["total"] >= 1
    assert stats["wins"] == 0  # Nog niet geëvalueerd of geen koerswijziging

def test_active_trades_insertion():
    """Test of een actieve positie handmatig toegevoegd kan worden aan active_trades."""
    with sqlite3.connect(tracker.DB_FILE) as conn:
        conn.execute(
            """
            INSERT INTO active_trades (user_id, ticker, shares, entry_price, stop_loss, peak_price, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("user123", "SXR8.DE", 0.5, 740.0, 730.0, 740.0, "OPEN")
        )
        conn.commit()

        trade = conn.execute("SELECT ticker, shares, status FROM active_trades WHERE user_id = 'user123'").fetchone()
        assert trade is not None
        assert trade[0] == "SXR8.DE"
        assert trade[1] == 0.5
        assert trade[2] == "OPEN"

def test_monitor_active_trades_stop_loss(monkeypatch):
    """Test of de monitor-functie correct een stop-loss triggert wanneer de koers daalt."""
    # Voeg een actieve trade toe aan de test database
    with sqlite3.connect(tracker.DB_FILE) as conn:
        conn.execute(
            """
            INSERT INTO active_trades (user_id, ticker, shares, entry_price, stop_loss, peak_price, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("user123", "SXR8.DE", 1.0, 740.0, 735.0, 740.0, "OPEN")
        )
        conn.commit()

    # Mock de data.get_finnhub_quote functie zodat deze een dalende koers retourneert (onder de stop loss van 735)
    class MockDataModule:
        @staticmethod
        def get_finnhub_quote(ticker):
            return {"price": 730.0, "pct_change": -1.35}

    monkeypatch.setattr(tracker, "data", MockDataModule)

    # Voer de monitor uit
    notifications = tracker.monitor_active_trades()

    # Controleer of er een stop-loss notificatie is gegenereerd
    assert len(notifications) == 1
    assert notifications[0]["type"] == "STOP_LOSS"
    assert notifications[0]["ticker"] == "SXR8.DE"

    # Controleer of de status in de database is bijgewerkt naar gesloten
    with sqlite3.connect(tracker.DB_FILE) as conn:
        status = conn.execute("SELECT status FROM active_trades WHERE ticker = 'SXR8.DE'").fetchone()[0]
        assert status == "CLOSED_STOP_LOSS"