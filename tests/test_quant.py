# tests/test_quant.py
import pytest
import quant


def test_kelly_criterion_valid():
    # 60% win rate, 1.5 win/loss ratio -> Kelly fraction = (0.6*1.5 - 0.4)/1.5 = 0.3333...
    res = quant.calculate_kelly_criterion(0.6, 1.5)
    assert abs(res - 0.3333) < 0.01


def test_kelly_criterion_invalid_inputs():
    with pytest.raises(ValueError):
        quant.calculate_kelly_criterion(-0.1, 1.5)

    with pytest.raises(ValueError):
        quant.calculate_kelly_criterion(0.5, 0.0)


def test_monte_carlo_simulation():
    res = quant.run_monte_carlo_simulation(
        initial_capital=1000.0,
        mean_daily_return=0.001,
        daily_volatility=0.015,
        days=10,
        simulations=100,
    )
    assert "mean_final" in res
    assert "median_final" in res
    assert res["mean_final"] > 0


def test_1pct_risk_position():
    res = quant.calculate_1pct_risk_position(portfolio_val=1000.0, entry_price=100.0, atr=2.0)
    assert res["max_risk_eur"] == 10.0
    assert res["stop_loss_distance"] == 3.0
    assert res["stop_loss_price"] == 97.0
    assert res["max_shares"] > 0