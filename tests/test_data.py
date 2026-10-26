# tests/test_data.py
import os
import sqlite3
from unittest.mock import patch
import pytest

import config
import data


def test_database_init_and_schema_migration():
    data.init_db()
    assert os.path.exists(config.DB_PATH)

    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS test_legacy_prices")
        conn.execute("CREATE TABLE test_legacy_prices (ticker TEXT, date TEXT, close REAL)")
        cursor = conn.execute("PRAGMA table_info(test_legacy_prices)")
        cols = [c[1] for c in cursor.fetchall()]
        assert "open" not in cols

    data.init_db()


def test_data_usd_eur_caching_and_fallbacks():
    rate1 = data.get_usd_eur()
    assert rate1 > 0
    rate2 = data.get_usd_eur()
    assert rate1 == rate2

    with patch("yfinance.Ticker", side_effect=Exception("API Error")), \
         patch("requests.get", side_effect=Exception("FMP Error")):
        rate_fallback = data.get_usd_eur()
        assert rate_fallback > 0


def test_data_quotes_and_fallback():
    quote = data.get_finnhub_quote("APC.DE")
    assert "price" in quote
    assert quote["price"] > 0

    with pytest.raises(data.DataError):
        data.get_finnhub_quote("INVALID_TICKER_XYZ_999")

    with pytest.raises(data.DataError):
        data._fetch_yfinance_quote("INVALID_TICKER_XYZ_999")

    with pytest.raises(data.DataError):
        data._fetch_fmp_quote("INVALID_TICKER_XYZ_999")


def test_data_get_daily():
    df = data.get_daily("APC.DE")
    assert not df.empty
    assert "close" in df.columns

    with pytest.raises(data.DataError):
        data.get_daily("NON_EXISTENT_TICKER_999")