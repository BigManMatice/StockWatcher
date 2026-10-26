# signals.py
import numpy as np
import pandas as pd
import data
from stockName import get_mapped_ticker, get_display_name


# --- STANDALONE INDICATOR FUNCTIONS ---

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (RSI)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Moving Average Convergence Divergence (MACD)."""
    exp1 = close.ewm(span=fast, adjust=False).mean()
    exp2 = close.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd_line": float(macd_line.iloc[-1]),
        "signal_line": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "cross": "bullish" if histogram.iloc[-1] > 0 else "bearish",
    }


def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: int = 2) -> dict:
    """Bollinger Bands (Upper, Middle, Lower, %B)."""
    sma = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = sma + (rolling_std * std_dev)
    lower = sma - (rolling_std * std_dev)

    current_price = float(close.iloc[-1])
    u_val = float(upper.iloc[-1])
    l_val = float(lower.iloc[-1])

    percent_b = (current_price - l_val) / (u_val - l_val) if u_val != l_val else 0.5

    return {
        "middle": float(sma.iloc[-1]),
        "upper": u_val,
        "lower": l_val,
        "percent_b": percent_b,
        "squeeze": bool((u_val - l_val) / float(sma.iloc[-1]) < 0.10),
    }


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range (ATR)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1])


def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    """Stochastic Oscillator (%K, %D)."""
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()

    k = 100 * ((df["close"] - low_min) / (high_max - low_min))
    d = k.rolling(window=d_period).mean()

    return {
        "k": float(k.iloc[-1]),
        "d": float(d.iloc[-1]),
        "status": "oversold" if k.iloc[-1] < 20 else ("overbought" if k.iloc[-1] > 80 else "neutral"),
    }


def calculate_obv(df: pd.DataFrame) -> dict:
    """On-Balance Volume (OBV) trend indicator."""
    close = df["close"]
    volume = df["volume"]

    direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
    obv = (direction * volume).fillna(0).cumsum()

    obv_trend = "rising" if obv.iloc[-1] > obv.iloc[-5] else "falling"
    return {
        "obv": float(obv.iloc[-1]),
        "trend": obv_trend,
    }


def calculate_pivot_points(df: pd.DataFrame) -> dict:
    """Classic Pivot Points."""
    prev_high = float(df["high"].iloc[-2])
    prev_low = float(df["low"].iloc[-2])
    prev_close = float(df["close"].iloc[-2])

    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = (2 * pivot) - prev_low
    s1 = (2 * pivot) - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)

    return {
        "pivot": pivot,
        "r1": r1,
        "s1": s1,
        "r2": r2,
        "s2": s2,
    }


# --- MASTER TECHNICAL ANALYSIS FUNCTION ---

def analyze_ticker(ticker: str) -> dict:
    """
    Runs full multi-indicator analysis combining SMA, RSI, MACD,
    Bollinger Bands, ATR, Stochastic, OBV, and Pivot Points.
    """
    api_ticker = get_mapped_ticker(ticker)
    display_name = get_display_name(ticker)

    try:
        quote = data.get_finnhub_quote(api_ticker)
        price = float(quote["price"])
        pct_change = float(quote["pct_change"])

        df = data.get_daily(api_ticker)

        # Normalize column names to lower case
        df.columns = [str(c).lower().strip() for c in df.columns]

        # Safety Fallback: Ensure high/low exist if legacy rows are empty
        if "high" not in df.columns or df["high"].isnull().all():
            df["high"] = df["close"]
        if "low" not in df.columns or df["low"].isnull().all():
            df["low"] = df["close"]
        if "open" not in df.columns or df["open"].isnull().all():
            df["open"] = df["close"]
        if "volume" not in df.columns or df["volume"].isnull().all():
            df["volume"] = 0

        if df.empty or len(df) < 50:
            signal_text = "NEUTRAL (Need at least 50 days of data)"
            return {
                "ticker": ticker,
                "display_name": display_name,
                "price": price,
                "pct_change": pct_change,
                "signal": signal_text,
                "verdict": "NEUTRAL ⚖️",
                "reasons": ["Insufficient history for full indicators"],
            }

        # --- FIX 1: Flatten MultiIndex columns if present ---
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        # --- FIX 2: Safely convert all column names to lowercase strings ---
        df.columns = [str(c).lower().strip() for c in df.columns]

        # --- FIX 3: Ensure essential columns exist, fill if missing ---
        if "close" not in df.columns:
            raise KeyError(f"Missing 'close' column in data for {ticker}. Available: {list(df.columns)}")

        if "high" not in df.columns:
            df["high"] = df["close"]
        if "low" not in df.columns:
            df["low"] = df["close"]
        if "volume" not in df.columns:
            df["volume"] = 0

        close = df["close"]

        # Run standalone indicator calculations
        rsi_series = calculate_rsi(close)
        current_rsi = float(rsi_series.iloc[-1])
        macd = calculate_macd(close)
        bb = calculate_bollinger_bands(close)
        atr = calculate_atr(df)
        stoch = calculate_stochastic(df)
        obv = calculate_obv(df)
        pivots = calculate_pivot_points(df)

        # SMA Crossovers
        fast_sma = float(close.rolling(20).mean().iloc[-1])
        slow_sma = float(close.rolling(50).mean().iloc[-1])

        # Evaluate score / reasons
        reasons = []
        bullish_signals = 0
        bearish_signals = 0

        # 1. SMA Trend
        if price > fast_sma:
            bullish_signals += 1
            reasons.append(f"Price > SMA20 (€{fast_sma:.2f})")
        else:
            bearish_signals += 1
            reasons.append(f"Price < SMA20 (€{fast_sma:.2f})")

        # 2. RSI
        if current_rsi < 30:
            bullish_signals += 2
            reasons.append(f"RSI Oversold ({current_rsi:.1f})")
        elif current_rsi > 70:
            bearish_signals += 2
            reasons.append(f"RSI Overbought ({current_rsi:.1f})")

        # 3. MACD
        if macd["cross"] == "bullish":
            bullish_signals += 1
            reasons.append("MACD Bullish Cross")
        else:
            bearish_signals += 1
            reasons.append("MACD Bearish Cross")

        # 4. Bollinger Bands
        if price <= bb["lower"]:
            bullish_signals += 1
            reasons.append("Price at Lower Bollinger Band")
        elif price >= bb["upper"]:
            bearish_signals += 1
            reasons.append("Price at Upper Bollinger Band")

        # 5. Stochastic
        if stoch["status"] == "oversold":
            bullish_signals += 1
            reasons.append(f"Stochastic Oversold (%K: {stoch['k']:.1f})")
        elif stoch["status"] == "overbought":
            bearish_signals += 1
            reasons.append(f"Stochastic Overbought (%K: {stoch['k']:.1f})")

        # Verdict Determination
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