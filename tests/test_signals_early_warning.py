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