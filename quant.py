# quant.py
import numpy as np


def calculate_kelly_criterion(win_rate: float, win_loss_ratio: float) -> float:
    """
    Berekent het Kelly-criterium percentage van het totale vermogen dat ingezet moet worden.
    
    Formula: f* = (p * b - q) / b
    - p = winstkans (win_rate)
    - q = verlieskans (1 - win_rate)
    - b = winst/verlies verhouding (win_loss_ratio)
    """
    if not (0 < win_rate < 1):
        raise ValueError("Winstkans (win_rate) moet tussen 0 en 1 liggen.")
    if win_loss_ratio <= 0:
        raise ValueError("Winst/verlies verhouding moet groter zijn dan 0.")

    p = win_rate
    q = 1.0 - win_rate
    b = win_loss_ratio

    kelly_fraction = (p * b - q) / b
    # Retourneer minimaal 0% (niet investeren als de verwachte waarde negatief is)
    return max(0.0, float(kelly_fraction))


def run_monte_carlo_simulation(
    initial_capital: float,
    mean_daily_return: float,
    daily_volatility: float,
    days: int = 252,
    simulations: int = 1000,
) -> dict:
    """
    Voert een Monte Carlo-simulatie uit op basis van een Geometric Brownian Motion (GBM).
    Returns statistieken over het verwachte eindvermogen na het opgegeven aantal dagen.
    """
    if initial_capital <= 0:
        raise ValueError("Startkapitaal moet groter zijn dan 0.")
    if days <= 0 or simulations <= 0:
        raise ValueError("Dagen en simulaties moeten positieve gehele getallen zijn.")

    # Drift correctie voor stochastische calculus
    dt = 1.0
    drift = (mean_daily_return - 0.5 * (daily_volatility ** 2)) * dt
    vol = daily_volatility * np.sqrt(dt)

    # Genereer willekeurige scenario's (Normal distribution)
    random_shocks = np.random.normal(0, 1, (days, simulations))
    daily_returns = np.exp(drift + vol * random_shocks)

    # Bereken prijsverloop
    price_paths = np.zeros((days + 1, simulations))
    price_paths[0] = initial_capital
    for t in range(1, days + 1):
        price_paths[t] = price_paths[t - 1] * daily_returns[t - 1]

    final_values = price_paths[-1]

    return {
        "mean_final": float(np.mean(final_values)),
        "median_final": float(np.median(final_values)),
        "percentile_5": float(np.percentile(final_values, 5)),
        "percentile_95": float(np.percentile(final_values, 95)),
        "worst_case": float(np.min(final_values)),
        "best_case": float(np.max(final_values)),
    }