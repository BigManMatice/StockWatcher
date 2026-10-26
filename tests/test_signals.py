# tests/test_signals.py
from unittest.mock import patch
import pandas as pd
import pytest

import signals


def test_technical_indicators_math():
    dates = pd.date_range(start="2025-01-01", periods=60, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(60)],
            "high": [105.0 + i for i in range(60)],
            "low": [95.0 + i for i in range(60)],
            "close": [102.0 + i for i in range(60)],
            "volume": [1000 + i * 10 for i in range(60)],
        },
        index=dates,
    )

    rsi = signals.calculate_rsi(df["close"])
    assert not rsi.empty

    macd = signals.calculate_macd(df["close"])
    assert macd["cross"] in ["bullish", "bearish"]

    bb = signals.calculate_bollinger_bands(df["close"])
    assert "middle" in bb
    assert "squeeze" in bb

    atr = signals.calculate_atr(df)
    assert atr > 0

    stoch = signals.calculate_stochastic(df)
    assert stoch["status"] in ["oversold", "overbought", "neutral"]

    obv = signals.calculate_obv(df)
    assert obv["trend"] in ["rising", "falling"]

    pivots = signals.calculate_pivot_points(df)
    assert "pivot" in pivots


def test_analyze_ticker_branches():
    res = signals.analyze_ticker("APC.DE")
    assert "verdict" in res
    assert res["verdict"] in ["BULLISH 🚀", "BEARISH 💥", "NEUTRAL ⚖️"]

    multi_dates = pd.date_range(start="2025-01-01", periods=60, freq="D")
    tuples = [("close", "APC.DE"), ("high", "APC.DE"), ("low", "APC.DE"), ("open", "APC.DE"), ("volume", "APC.DE")]
    cols = pd.MultiIndex.from_tuples(tuples)
    multi_df = pd.DataFrame(
        [[100.0 + i, 105.0 + i, 95.0 + i, 100.0 + i, 1000] for i in range(60)],
        index=multi_dates,
        columns=cols,
    )

    with patch("data.get_daily", return_value=multi_df):
        res_multi = signals.analyze_ticker("APC.DE")
        assert "verdict" in res_multi

    dates = pd.date_range(start="2025-01-01", periods=20, freq="D")
    short_df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "close": [102.0] * 20,
            "volume": [1000] * 20,
        },
        index=dates,
    )

    with patch("data.get_daily", return_value=short_df):
        res_short = signals.analyze_ticker("APC.DE")
        assert "Insufficient data" in res_short["signal"]

    with pytest.raises(RuntimeError):
        signals.analyze_ticker("INVALID_TICKER_XYZ_999")