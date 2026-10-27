import numpy as np

def calculate_kelly_criterion(win_rate: float, win_loss_ratio: float) -> float:
    if not (0.0 <= win_rate <= 1.0):
        raise ValueError("Win rate must be between 0 and 1.")
    if win_loss_ratio <= 0:
        raise ValueError("Win/loss ratio must be greater than 0.")

    p = win_rate
    q = 1.0 - p
    b = win_loss_ratio
    fraction = (p * b - q) / b
    return max(0.0, float(fraction))


def calculate_expected_shortfall(returns: list, confidence_level: float = 0.95) -> float:
    if not returns or len(returns) < 5:
        return 0.05
    arr = np.array(returns, dtype=float)
    var_threshold = np.percentile(arr, (1.0 - confidence_level) * 100.0)
    tail_losses = arr[arr <= var_threshold]
    if len(tail_losses) == 0:
        return float(abs(var_threshold))
    return float(abs(np.mean(tail_losses)))


def calculate_1pct_risk_position(portfolio_val: float, entry_price: float, atr: float, risk_pct: float = 0.01) -> dict:
    if entry_price <= 0 or atr <= 0 or portfolio_val <= 0:
        return {"max_shares": 0.0, "max_eur": 0.0, "stop_loss_price": entry_price, "max_risk_eur": 0.0, "stop_loss_distance": 0.0}

    max_risk_eur = portfolio_val * risk_pct
    stop_loss_distance = 1.5 * atr
    max_shares = max_risk_eur / stop_loss_distance if stop_loss_distance > 0 else 0.0
    max_eur = max_shares * entry_price
    stop_loss_price = entry_price - stop_loss_distance

    return {
        "max_risk_eur": float(max_risk_eur),
        "stop_loss_distance": float(stop_loss_distance),
        "max_shares": float(max_shares),
        "max_eur": float(max_eur),
        "stop_loss_price": float(stop_loss_price),
    }


def calculate_expected_value(win_rate: float, avg_win_eur: float, avg_loss_eur: float) -> float:
    p = win_rate
    q = 1.0 - p
    ev = (p * avg_win_eur) - (q * avg_loss_eur)
    return float(ev)


def run_monte_carlo_simulation(capital: float = 1000.0, daily_return: float = 0.001, volatility: float = 0.015, days: int = 252, simulations: int = 1000, **kwargs) -> dict:
    cap = kwargs.get("initial_capital", capital)
    ret = kwargs.get("mean_daily_return", daily_return)
    vol = kwargs.get("daily_volatility", volatility)

    rng = np.random.default_rng(42)
    daily_returns = rng.normal(ret, vol, (simulations, days))
    price_paths = cap * np.exp(np.cumsum(daily_returns, axis=1))
    final_values = price_paths[:, -1]

    return {
        "mean_final": float(np.mean(final_values)),
        "median_final": float(np.median(final_values)),
        "percentile_5": float(np.percentile(final_values, 5)),
        "percentile_95": float(np.percentile(final_values, 95)),
        "worst_case": float(np.min(final_values)),
        "best_case": float(np.max(final_values)),
    }