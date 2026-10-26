# signals.py
import numpy as np
import pandas as pd

import data
import quant
from stockName import get_display_name, get_mapped_ticker


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


def detect_early_warnings(df: pd.DataFrame, current_price: float) -> list:
    """Detecteert patronen die wijzen op een aanstaande koersuitbraak (vóór het gebeurt)."""
    warnings = []

    if len(df) < 14:
        return warnings

    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close

    # Dynamic rolling windows for variable dataframe lengths (e.g., unit test data)
    window_bb = min(20, len(df))
    window_quantile = min(50, len(df))

    # 1. Bollinger Band Squeeze (Volatiliteit droogt op -> grote beweging op komst)
    ma = close.rolling(window_bb).mean()
    std = close.rolling(window_bb).std()
    upper_band = ma + (std * 2)
    lower_band = ma - (std * 2)
    bandwidth = (upper_band - lower_band) / ma

    min_bw = bandwidth.rolling(window_quantile, min_periods=5).quantile(0.20).iloc[-1]
    curr_bw = bandwidth.iloc[-1]

    if pd.notna(curr_bw) and pd.notna(min_bw) and curr_bw <= min_bw:
        warnings.append("⚠️ **Bollinger Squeeze:** Volatiliteit is extreem laag. Een grote koersuitbraak staat op uitbreken!")

    # 2. RSI Divergentie / Approaching Oversold/Overbought
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=5).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=5).mean()
    rs = gain / (loss.replace(0, 1e-9))
    rsi = 100 - (100 / (1 + rs))
    current_rsi = rsi.iloc[-1] if not rsi.empty else 50.0

    if 30 <= current_rsi <= 35:
        warnings.append(f"⚠️ **Pre-Buy Warning:** RSI is bijna oversold ({current_rsi:.1f}). Mogelijk bodemsignaal nabij!")
    elif 65 <= current_rsi <= 70:
        warnings.append(f"⚠️ **Pre-Sell Warning:** RSI is bijna overbought ({current_rsi:.1f}). Mogelijk top bereikt!")

    # 3. Near Resistance / Support Breakout
    recent_high = high.tail(20).max()
    recent_low = low.tail(20).min()

    if current_price >= recent_high * 0.99 and current_price <= recent_high:
        warnings.append("⚠️ **Testing Resistance:** Koers test de weerstand. Mogelijke opwaartse uitbraak!")
    elif current_price <= recent_low * 1.01 and current_price >= recent_low:
        warnings.append("⚠️ **Testing Support:** Koers test de steun. Mogelijke neerwaartse uitbraak!")

    return warnings


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


def analyze_ticker_advanced(ticker: str) -> dict:
    """Uitgebreide analyse inclusief Kelly sizing en Early Warning alerts."""
    api_ticker = get_mapped_ticker(ticker)
    df = data.get_daily(api_ticker)
    quote = data.get_finnhub_quote(api_ticker)
    price = float(quote["price"])

    early_warnings = detect_early_warnings(df, price)

    # Standard quantitative expectation parameters
    win_rate = 0.55
    win_loss_ratio = 1.5

    kelly_pct = quant.calculate_kelly_criterion(win_rate, win_loss_ratio) * 100.0

    return {
        "ticker": ticker,
        "display_name": get_display_name(ticker),
        "price": price,
        "pct_change": float(quote.get("pct_change", 0.0)),
        "early_warnings": early_warnings,
        "kelly_pct": kelly_pct,
    }