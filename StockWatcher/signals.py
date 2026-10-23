import pandas as pd

FAST, SLOW = 20, 50
RSI_PERIOD = 14
CROSS_LOOKBACK = 3  # a crossover counts as "recent" for this many days


def rsi(close, period=RSI_PERIOD):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out = out.where(avg_loss != 0, 100.0)  # only gains -> 100
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)  # flat price -> 50
    return out


def analyze(df):
    """Take a DataFrame with a 'close' column, return a signal dict."""
    close = df["close"]
    if len(close) < SLOW + 1:
        return {
            "signal": "hold",
            "price": float(close.iloc[-1]) if len(close) else None,
            "reasons": [f"Not enough data ({len(close)} days, need {SLOW + 1})"],
        }

    fast = close.rolling(FAST).mean()
    slow = close.rolling(SLOW).mean()
    diff = fast - slow
    prev = diff.shift(1)

    golden = ((prev <= 0) & (diff > 0)).iloc[-CROSS_LOOKBACK:].any()
    death = ((prev >= 0) & (diff < 0)).iloc[-CROSS_LOOKBACK:].any()
    r = float(rsi(close).iloc[-1])

    reasons = []
    buy = sell = False
    if golden:
        buy = True
        reasons.append(f"SMA{FAST} crossed above SMA{SLOW} in the last {CROSS_LOOKBACK} days")
    if death:
        sell = True
        reasons.append(f"SMA{FAST} crossed below SMA{SLOW} in the last {CROSS_LOOKBACK} days")
    if r < 30:
        buy = True
        reasons.append(f"RSI {r:.0f} is oversold (<30)")
    elif r > 70:
        sell = True
        reasons.append(f"RSI {r:.0f} is overbought (>70)")

    if buy and sell:
        signal = "hold"
        reasons.append("Signals conflict")
    elif buy:
        signal = "buy"
    elif sell:
        signal = "sell"
    else:
        signal = "hold"
        reasons.append("No crossover and RSI is in the neutral range")

    return {
        "signal": signal,
        "price": float(close.iloc[-1]),
        "sma_fast": float(fast.iloc[-1]),
        "sma_slow": float(slow.iloc[-1]),
        "trend": "up" if diff.iloc[-1] > 0 else "down",
        "rsi": r,
        "reasons": reasons,
    }