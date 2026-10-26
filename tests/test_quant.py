# tests/test_quant.py
import pytest
import quant


def test_kelly_criterion_valid():
    # 60% winstkans, 1.5 winst/verlies ratio
    # f* = (0.6 * 1.5 - 0.4) / 1.5 = (0.9 - 0.4) / 1.5 = 0.5 / 1.5 = 0.3333...
    res = quant.calculate_kelly_criterion(0.6, 1.5)
    assert round(res, 4) == 0.3333


def test_kelly_criterion_negative_expectation():
    # Slechte kansen moeten 0% inzet adviseren
    res = quant.calculate_kelly_criterion(0.3, 1.0)
    assert res == 0.0


def test_kelly_criterion_invalid_inputs():
    with pytest.raises(ValueError):
        quant.calculate_kelly_criterion(1.5, 1.5)

    with pytest.raises(ValueError):
        quant.calculate_kelly_criterion(0.5, -1.0)


def test_monte_carlo_simulation():
    res = quant.run_monte_carlo_simulation(
        initial_capital=1000.0,
        mean_daily_return=0.001,
        daily_volatility=0.015,
        days=10,
        simulations=100,
    )
    assert "mean_final" in res
    assert res["worst_case"] <= res["median_final"] <= res["best_case"]