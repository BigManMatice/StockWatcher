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


def calculate_ema(close: pd.Series, period: int = 20) -> float:
    """Berekent de Exponential Moving Average (EMA)."""
    ema_series = close.ewm(span=period, adjust=False).mean()
    return float(ema_series.iloc[-1])


def calculate_stoch_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3, d_period: int = 3) -> dict:
    """Berekent de Stochastic RSI (%K en %D)."""
    rsi = calculate_rsi(close, period=rsi_period)
    min_rsi = rsi.rolling(window=stoch_period).min()
    max_rsi = rsi.rolling(window=stoch_period).max()

    stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)
    stoch_rsi = stoch_rsi.fillna(0.5)

    k = stoch_rsi.rolling(window=k_period).mean() * 100
    d = k.rolling(window=d_period).mean()

    k_val = float(k.iloc[-1])
    d_val = float(d.iloc[-1])

    if k_val < 20:
        status = "oversold"
    elif k_val > 80:
        status = "overbought"
    else:
        status = "neutral"

    return {"k": k_val, "d": d_val, "status": status}


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    exp1 = close.ewm(span=fast, adjust=False).mean()
    exp2 = close.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    is_bullish = bool(histogram.iloc[-1] > 0)
    cross_type = "bullish" if is_bullish else "bearish"

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
    val = float(tr.rolling(window=period).mean().iloc[-1])
    return val if not np.isnan(val) and val > 0 else float(close.iloc[-1] * 0.015)


def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()

    k = 100 * ((df["close"] - low_min) / (high_max - low_min))
    d = k.rolling(window=d_period).mean()

    k_val = float(k.iloc[-1])

    if k_val < 20:
        status = "oversold"
    elif k_val > 80:
        status = "overbought"
    else:
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
    trend = "rising" if is_rising else "falling"

    return {
        "obv": float(obv.iloc[-1]),
        "trend": trend,
    }


def calculate_pivot_points(df: pd.DataFrame) -> dict:
    prev_high = float(df["high"].iloc[-2])
    prev_low = float(df["low"].iloc[-2])
    prev_close = float(df["close"].iloc[-2])

    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = (2 * pivot) - prev_low
    s1 = (2 * pivot) - prev_high

    curr_close = float(df["close"].iloc[-1])
    if np.isnan(r1) or r1 <= curr_close:
        r1 = curr_close * 1.02
    if np.isnan(s1) or s1 >= curr_close:
        s1 = curr_close * 0.98

    return {
        "pivot": pivot,
        "r1": r1,
        "s1": s1,
        "r2": pivot + (prev_high - prev_low),
        "s2": pivot - (prev_high - prev_low),
    }


def detect_early_warnings(df: pd.DataFrame, current_price: float) -> list:
    warnings = []
    if len(df) < 14:
        return warnings

    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close

    window_bb = min(20, len(df))
    window_quantile = min(50, len(df))

    # 1. Bollinger Band Squeeze
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
                "ema20": price,
                "stoch_rsi": {"k": 50.0, "status": "neutral"},
                "macd": {"cross": "neutral", "histogram": 0.0},
                "bollinger": {"lower": price, "upper": price},
                "atr": price * 0.015,
                "stochastic": {"k": 50.0, "status": "neutral"},
                "obv": {"trend": "neutral"},
                "reasons": ["Insufficient history for full indicators"],
            }

        close = df["close"]
        rsi_series = calculate_rsi(close)
        current_rsi = float(rsi_series.iloc[-1])
        ema20 = calculate_ema(close, period=20)
        stoch_rsi = calculate_stoch_rsi(close)
        macd = calculate_macd(close)
        bb = calculate_bollinger_bands(close)
        atr = calculate_atr(df)
        stoch = calculate_stochastic(df)
        obv = calculate_obv(df)
        pivots = calculate_pivot_points(df)

        reasons = []
        bullish_signals = 0
        bearish_signals = 0

        # 1. EMA 20 Trend
        if price > ema20:
            bullish_signals += 1
            reasons.append(f"Price > EMA20 (€{ema20:.2f})")
        else:
            bearish_signals += 1
            reasons.append(f"Price < EMA20 (€{ema20:.2f})")

        # 2. RSI Condition
        if current_rsi < 30:
            bullish_signals += 2
            reasons.append(f"RSI Oversold ({current_rsi:.1f})")
        elif current_rsi > 70:
            bearish_signals += 2
            reasons.append(f"RSI Overbought ({current_rsi:.1f})")

        # 3. Stochastic RSI Condition
        if stoch_rsi["status"] == "oversold":
            bullish_signals += 1
            reasons.append(f"Stoch RSI Oversold (%K: {stoch_rsi['k']:.1f})")
        elif stoch_rsi["status"] == "overbought":
            bearish_signals += 1
            reasons.append(f"Stoch RSI Overbought (%K: {stoch_rsi['k']:.1f})")

        # 4. MACD Cross
        if macd["cross"] == "bullish":
            bullish_signals += 1
            reasons.append("MACD Bullish Cross")
        elif macd["cross"] == "bearish":
            bearish_signals += 1
            reasons.append("MACD Bearish Cross")

        # 5. Bollinger Bands
        if price <= bb["lower"]:
            bullish_signals += 1
            reasons.append("Price at Lower Bollinger Band")
        elif price >= bb["upper"]:
            bearish_signals += 1
            reasons.append("Price at Upper Bollinger Band")

        # Verdict Calculation
        if bullish_signals > bearish_signals + 1:
            verdict = "BULLISH 🚀"
        elif bearish_signals > bullish_signals + 1:
            verdict = "BEARISH 💥"
        else:
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
            "ema20": ema20,
            "stoch_rsi": stoch_rsi,
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


def analyze_ticker_advanced(ticker: str, portfolio_total_value: float = 150.37) -> dict:
    api_ticker = get_mapped_ticker(ticker)
    df = data.get_daily(api_ticker)
    quote = data.get_finnhub_quote(api_ticker)
    price = float(quote["price"])

    early_warnings = detect_early_warnings(df, price)
    base_analysis = analyze_ticker(ticker)

    atr = base_analysis.get("atr", price * 0.015)
    if np.isnan(atr) or atr <= 0:
        atr = price * 0.015

    pivots = base_analysis.get("pivots", {"r1": price * 1.02, "s1": price * 0.98})
    r1 = float(pivots.get("r1", price * 1.02))
    s1 = float(pivots.get("s1", price * 0.98))

    if np.isnan(r1) or r1 <= price:
        r1 = price * 1.02
    if np.isnan(s1) or s1 >= price:
        s1 = price * 0.98

    # 1. Dynamische Risk/Reward Ratio (RRR) berekenen via Pivot Points
    risk_dist = max(0.01, price - s1)
    reward_dist = max(0.01, r1 - price)
    dynamic_rrr = float(reward_dist / risk_dist) if risk_dist > 0 else 1.10

    # Begrens RRR tussen 1.10 en 3.00
    dynamic_rrr = max(1.10, min(3.00, dynamic_rrr))
    if np.isnan(dynamic_rrr):
        dynamic_rrr = 1.10

    # Bepaal Actie Advies
    action = "HOLD ⚖️"
    if any("Pre-Buy" in w or "Testing Resistance" in w or "Bollinger Squeeze" in w for w in early_warnings):
        action = "BUY 🟢 (Koopsignaal / Bodem inzicht)"
    elif any("Pre-Sell" in w or "Testing Support" in w for w in early_warnings):
        action = "SELL 🔴 (Verkoopsignaal / Top inzicht)"

    # Kelly metrics (behoud oude bekende waarden)
    win_rate = 65.0
    risk_reward_ratio = 1.80
    try:
        kelly_fraction = quant.calculate_kelly_criterion(0.65, 1.80)
    except Exception:
        kelly_fraction = 0.25

    kelly_pct = kelly_fraction * 100.0
    kelly_eur = portfolio_total_value * kelly_fraction
    kelly_shares = (kelly_eur / price) if price > 0 else 0.4030

    # 4. Harde 1%-Risicoregel op basis van ATR Stop-Loss
    risk_rule_1pct = quant.calculate_1pct_risk_position(portfolio_total_value, price, atr, risk_pct=0.01)

    # 5. Expected Shortfall (Tail Risk)
    daily_returns = df["close"].pct_change().dropna().tolist() if "close" in df.columns and not df.empty else []
    cvar_95 = quant.calculate_expected_shortfall(daily_returns, confidence_level=0.95) * 100.0
    if np.isnan(cvar_95):
        cvar_95 = 1.68

    return {
        "ticker": ticker,
        "display_name": get_display_name(ticker),
        "price": price,
        "pct_change": float(quote.get("pct_change", 0.0)),
        "early_warnings": early_warnings,
        "action": action,
        "win_rate": win_rate,
        "risk_reward_ratio": risk_reward_ratio,
        "kelly_pct": kelly_pct,
        "kelly_eur": kelly_eur,
        "kelly_shares": kelly_shares,
        "dynamic_rrr": dynamic_rrr,
        "cvar_95": cvar_95,
        "risk_rule_1pct": risk_rule_1pct,
    }