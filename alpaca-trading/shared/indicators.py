"""
shared/indicators.py
====================
Calculates all technical indicators from OHLCV price data.
No API calls here — pure math on DataFrames.

Indicators computed:
- RSI   (Relative Strength Index)     → momentum
- MACD  (Moving Avg Convergence Div)  → trend direction
- EMA   (Exponential Moving Average)  → trend filter
- ATR   (Average True Range)          → volatility / stop sizing
- Volume ratio                        → confirmation signal

All functions accept a pandas DataFrame with columns:
    open, high, low, close, volume
And return the same DataFrame with new indicator columns added.
"""

import logging
import pandas as pd
import numpy as np

from shared.config import INDICATORS

logger = logging.getLogger(__name__)


# ============================================================
# RSI — Relative Strength Index
# Measures momentum. Range: 0–100.
# < 30 = oversold (potential buy)
# > 70 = overbought (potential sell)
# ============================================================

def compute_rsi(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
    """
    Adds 'rsi' column to DataFrame.
    Uses Wilder's smoothing method (standard RSI calculation).
    """
    period = period or INDICATORS["rsi_period"]
    df = df.copy()

    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    # Wilder's smoothing (exponential, not simple average)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    return df


# ============================================================
# MACD — Moving Average Convergence Divergence
# Measures trend strength and direction.
# macd_line crosses above signal → bullish
# macd_line crosses below signal → bearish
# ============================================================

def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds columns: 'macd_line', 'macd_signal', 'macd_hist'

    macd_line   = EMA(fast) - EMA(slow)
    macd_signal = EMA(macd_line, signal_period)
    macd_hist   = macd_line - macd_signal (positive = bullish momentum)
    """
    df = df.copy()

    fast   = INDICATORS["macd_fast"]
    slow   = INDICATORS["macd_slow"]
    signal = INDICATORS["macd_signal"]

    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    df["macd_line"]   = ema_fast - ema_slow
    df["macd_signal"] = df["macd_line"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"]   = df["macd_line"] - df["macd_signal"]

    return df


# ============================================================
# EMA — Exponential Moving Average
# Faster-reacting than simple moving average.
# Price above EMA = uptrend
# Price below EMA = downtrend
# EMA9 crossing above EMA21 = bullish signal
# ============================================================

def compute_ema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds columns: 'ema_fast' (9), 'ema_slow' (21)
    Also adds 'ema_signal': 'bullish', 'bearish', or 'neutral'
    """
    df = df.copy()

    fast = INDICATORS["ema_fast"]   # 9
    slow = INDICATORS["ema_slow"]   # 21

    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()

    # Detect crossover direction
    df["ema_signal"] = "neutral"
    df.loc[df["ema_fast"] > df["ema_slow"], "ema_signal"] = "bullish"
    df.loc[df["ema_fast"] < df["ema_slow"], "ema_signal"] = "bearish"

    return df


# ============================================================
# ATR — Average True Range
# Measures how much an asset moves on average.
# Used to size stop-losses dynamically:
#   stop = entry_price - (atr_multiplier × ATR)
# Higher ATR = more volatile = wider stop needed
# ============================================================

def compute_atr(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
    """
    Adds 'atr' column to DataFrame.

    True Range = max of:
        high - low
        abs(high - previous close)
        abs(low  - previous close)

    ATR = smoothed average of True Range over N periods
    """
    period = period or INDICATORS["atr_period"]
    df = df.copy()

    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing (same as RSI)
    df["atr"] = true_range.ewm(
        alpha=1/period,
        min_periods=period,
        adjust=False
    ).mean()

    return df


# ============================================================
# VOLUME RATIO
# Compares current volume to 20-day average.
# Ratio > 1.2 = volume surge = signal has more conviction
# ============================================================

def compute_volume_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds 'volume_ratio' column.
    volume_ratio = current volume / 20-day average volume
    """
    df = df.copy()
    avg_period = INDICATORS["volume_avg_period"]  # 20

    df["volume_ma"] = df["volume"].rolling(window=avg_period).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]

    return df


# ============================================================
# MASTER FUNCTION — compute all indicators at once
# ============================================================

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Runs all indicator calculations on a price DataFrame.
    Call this once per symbol per cycle instead of calling
    each function separately.

    Returns DataFrame with all indicator columns added.
    Returns empty DataFrame if input has insufficient data.
    """
    if df.empty:
        logger.warning("⚠️  Empty DataFrame passed to compute_all — skipping.")
        return df

    min_rows = max(
        INDICATORS["macd_slow"] + INDICATORS["macd_signal"],
        INDICATORS["rsi_period"],
        INDICATORS["ema_slow"],
        INDICATORS["atr_period"],
        INDICATORS["volume_avg_period"],
    )

    if len(df) < min_rows:
        logger.warning(
            f"⚠️  Not enough data rows ({len(df)}) to compute indicators. "
            f"Need at least {min_rows}."
        )
        return pd.DataFrame()

    try:
        df = compute_rsi(df)
        df = compute_macd(df)
        df = compute_ema(df)
        df = compute_atr(df)
        df = compute_volume_ratio(df)
        return df

    except Exception as e:
        logger.error(f"❌ Error computing indicators: {e}")
        return pd.DataFrame()


# ============================================================
# SIGNAL EXTRACTOR
# Pulls the latest indicator values into a clean dict
# This is what gets passed to Claude in the prompt
# ============================================================

def get_latest_signals(df: pd.DataFrame) -> dict | None:
    """
    Extracts the most recent row of indicator values.
    Returns a clean dict ready to be injected into Claude prompt.

    Returns None if data is invalid or missing.
    """
    if df.empty:
        return None

    required_cols = [
        "close", "rsi", "macd_line", "macd_signal",
        "macd_hist", "ema_fast", "ema_slow", "ema_signal",
        "atr", "volume_ratio"
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.error(f"❌ Missing indicator columns: {missing}")
        return None

    latest = df.iloc[-1]
    prev   = df.iloc[-2] if len(df) >= 2 else latest

    # Determine MACD crossover direction
    macd_cross = "neutral"
    if latest["macd_line"] > latest["macd_signal"] and \
       prev["macd_line"] <= prev["macd_signal"]:
        macd_cross = "bullish_cross"
    elif latest["macd_line"] < latest["macd_signal"] and \
         prev["macd_line"] >= prev["macd_signal"]:
        macd_cross = "bearish_cross"
    elif latest["macd_line"] > latest["macd_signal"]:
        macd_cross = "bullish"
    else:
        macd_cross = "bearish"

    # RSI zone
    rsi_val = latest["rsi"]
    rsi_zone = "neutral"
    if rsi_val < INDICATORS["rsi_oversold"]:
        rsi_zone = "oversold"
    elif rsi_val > INDICATORS["rsi_overbought"]:
        rsi_zone = "overbought"

    # Volume confirmation
    vol_ratio = latest["volume_ratio"]
    volume_confirmed = vol_ratio >= INDICATORS["volume_surge_threshold"]

    return {
        "price":            round(float(latest["close"]), 4),
        "rsi":              round(float(rsi_val), 2),
        "rsi_zone":         rsi_zone,
        "macd":             macd_cross,
        "ema_signal":       latest["ema_signal"],
        "ema_fast":         round(float(latest["ema_fast"]), 4),
        "ema_slow":         round(float(latest["ema_slow"]), 4),
        "atr":              round(float(latest["atr"]), 4),
        "volume_ratio":     round(float(vol_ratio), 2),
        "volume_confirmed": volume_confirmed,
    }
