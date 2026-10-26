import numpy as np
import pandas as pd
import data
from stockName import get_mapped_ticker, get_display_name


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    exp1 = close.ewm(span=fast, adjust=False).mean()
    exp2 = close.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    is_bullish = bool(histogram.iloc[-1] > 0)
    match is_bullish:
        case True:
            cross_type = "bullish"
        case False:
            cross_type = "bearish"

    return {
        "macd_line": float(macd_line.iloc[-1]),
        "signal_line": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "cross": cross_type,
    }


def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: int = 2) -> dict:
    sma = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = sma + (rolling_std * std_dev)
    lower = sma - (rolling_std * std_dev)

    current_price = float(close.iloc[-1])
    u_val = float(upper.iloc[-1])
    l_val = float(lower.iloc[-1])
    mid_val = float(sma.iloc[-1])

    percent_b = (current_price - l_val) / (u_val - l_val) if u_val != l_val else 0.5

    return {
        "middle": mid_val,
        "upper": u_val,
        "lower": l_val,
        "percent_b": percent_b,
        "squeeze": bool((u_val - l_val) / mid_val < 0.10) if mid_val else False,
    }


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(window=period).mean().iloc[-1])


def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()

    k = 100 * ((df["close"] - low_min) / (high_max - low_min))
    d = k.rolling(window=d_period).mean()

    k_val = float(k.iloc[-1])

    match k_val:
        case k_val if k_val < 20:
            status = "oversold"
        case k_val if k_val > 80:
            status = "overbought"
        case _:
            status = "neutral"

    return {
        "k": k_val,
        "d": float(d.iloc[-1]),
        "status": status,
    }


def calculate_obv(df: pd.DataFrame) -> dict:
    close, volume = df["close"], df["volume"]
    direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
    obv = (direction * volume).fillna(0).cumsum()

    is_rising = bool(obv.iloc[-1] > obv.iloc[-5])
    match is_rising:
        case True:
            trend = "rising"
        case False:
            trend = "falling"

    return {
        "obv": float(obv.iloc[-1]),
        "trend": trend,
    }


def calculate_pivot_points(df: pd.DataFrame) -> dict:
    prev_high = float(df["high"].iloc[-2])
    prev_low = float(df["low"].iloc[-2])
    prev_close = float(df["close"].iloc[-2])

    pivot = (prev_high + prev_low + prev_close) / 3
    return {
        "pivot": pivot,
        "r1": (2 * pivot) - prev_low,
        "s1": (2 * pivot) - prev_high,
        "r2": pivot + (prev_high - prev_low),
        "s2": pivot - (prev_high - prev_low),
    }


def analyze_ticker(ticker: str) -> dict:
    api_ticker = get_mapped_ticker(ticker)
    display_name = get_display_name(ticker)

    try:
        quote = data.get_finnhub_quote(api_ticker)
        price = float(quote["price"])
        pct_change = float(quote["pct_change"])

        df = data.get_daily(api_ticker)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        df.columns = [str(c).lower().strip() for c in df.columns]

        for col in ["high", "low", "open"]:
            if col not in df.columns or df[col].isnull().all():
                df[col] = df["close"]

        if "volume" not in df.columns or df["volume"].isnull().all():
            df["volume"] = 0

        if len(df) < 50:
            return {
                "ticker": ticker,
                "display_name": display_name,
                "price": price,
                "pct_change": pct_change,
                "signal": "NEUTRAL ⚖️ | Insufficient data",
                "verdict": "NEUTRAL ⚖️",
                "rsi": 50.0,
                "macd": {"cross": "neutral", "histogram": 0.0},
                "bollinger": {"lower": price, "upper": price},
                "atr": 0.0,
                "stochastic": {"k": 50.0, "status": "neutral"},
                "obv": {"trend": "neutral"},
                "reasons": ["Insufficient history for full indicators"],
            }

        close = df["close"]
        rsi_series = calculate_rsi(close)
        current_rsi = float(rsi_series.iloc[-1])
        macd = calculate_macd(close)
        bb = calculate_bollinger_bands(close)
        atr = calculate_atr(df)
        stoch = calculate_stochastic(df)
        obv = calculate_obv(df)
        pivots = calculate_pivot_points(df)

        fast_sma = float(close.rolling(20).mean().iloc[-1])

        reasons = []
        bullish_signals = 0
        bearish_signals = 0

        # 1. SMA Trend
        is_above_sma = bool(price > fast_sma)
        match is_above_sma:
            case True:
                bullish_signals += 1
                reasons.append(f"Price > SMA20 (€{fast_sma:.2f})")
            case False:
                bearish_signals += 1
                reasons.append(f"Price < SMA20 (€{fast_sma:.2f})")

        # 2. RSI Condition
        match current_rsi:
            case current_rsi if current_rsi < 30:
                bullish_signals += 2
                reasons.append(f"RSI Oversold ({current_rsi:.1f})")
            case current_rsi if current_rsi > 70:
                bearish_signals += 2
                reasons.append(f"RSI Overbought ({current_rsi:.1f})")
            case _:
                pass

        # 3. MACD Cross
        match macd["cross"]:
            case "bullish":
                bullish_signals += 1
                reasons.append("MACD Bullish Cross")
            case "bearish":
                bearish_signals += 1
                reasons.append("MACD Bearish Cross")

        # 4. Bollinger Bands
        match price:
            case p if p <= bb["lower"]:
                bullish_signals += 1
                reasons.append("Price at Lower Bollinger Band")
            case p if p >= bb["upper"]:
                bearish_signals += 1
                reasons.append("Price at Upper Bollinger Band")
            case _:
                pass

        # 5. Stochastic Status
        match stoch["status"]:
            case "oversold":
                bullish_signals += 1
                reasons.append(f"Stochastic Oversold (%K: {stoch['k']:.1f})")
            case "overbought":
                bearish_signals += 1
                reasons.append(f"Stochastic Overbought (%K: {stoch['k']:.1f})")
            case _:
                pass

        # Verdict Calculation
        match (bullish_signals > bearish_signals + 1, bearish_signals > bullish_signals + 1):
            case (True, _):
                verdict = "BULLISH 🚀"
            case (_, True):
                verdict = "BEARISH 💥"
            case _:
                verdict = "NEUTRAL ⚖️"

        signal_text = f"{verdict} | " + " | ".join(reasons[:3])

        return {
            "ticker": ticker,
            "display_name": display_name,
            "price": price,
            "pct_change": pct_change,
            "signal": signal_text,
            "verdict": verdict,
            "rsi": current_rsi,
            "macd": macd,
            "bollinger": bb,
            "atr": atr,
            "stochastic": stoch,
            "obv": obv,
            "pivots": pivots,
            "reasons": reasons,
        }

    except Exception as e:
        raise RuntimeError(f"Error processing {ticker}: {e}")