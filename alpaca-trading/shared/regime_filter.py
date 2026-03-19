"""
shared/regime_filter.py
=======================
Detects whether the market is currently TRENDING or RANGING (choppy).

Why this matters:
- Trend-following strategies (momentum, breakout) work great in trends
  but get chopped up in sideways markets
- Mean-reversion strategies work in ranges but get destroyed in trends
- Without a regime filter, your bot uses the same strategy regardless
  of market condition — this is one of the biggest reasons bots fail

How we detect regime:
1. ADX  (Average Directional Index)  — measures trend STRENGTH
2. EMA slope                         — measures trend DIRECTION
3. Price range compression           — detects consolidation (ranging)

Output:
    "TREND"   → strong directional move, use trend-following signals
    "RANGE"   → sideways/choppy, use mean-reversion signals
    "UNCLEAR" → mixed signals, default to HOLD
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ============================================================
# THRESHOLDS
# These are standard values used by professional traders
# ============================================================
ADX_TREND_THRESHOLD  = 25   # ADX > 25 = trending market
ADX_RANGE_THRESHOLD  = 20   # ADX < 20 = ranging market
EMA_SLOPE_THRESHOLD  = 0.001 # Minimum slope to consider directional
RANGE_COMPRESSION    = 0.02  # Price range < 2% of price = compression


# ============================================================
# ADX — Average Directional Index
# Measures trend STRENGTH (not direction).
# 0–20  = weak/no trend (ranging)
# 20–25 = developing trend
# 25+   = strong trend
# 40+   = very strong trend
# ============================================================

def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Adds 'adx' column to DataFrame.
    ADX is derived from +DI and -DI (directional indicators).
    """
    df = df.copy()

    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    dm_plus  = high.diff()
    dm_minus = -low.diff()

    dm_plus  = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0)

    # Smoothed (Wilder's method)
    alpha = 1 / period
    atr_smooth    = tr.ewm(alpha=alpha, adjust=False).mean()
    dmp_smooth    = dm_plus.ewm(alpha=alpha, adjust=False).mean()
    dmm_smooth    = dm_minus.ewm(alpha=alpha, adjust=False).mean()

    # Directional Indicators
    di_plus  = 100 * dmp_smooth / atr_smooth.replace(0, np.nan)
    di_minus = 100 * dmm_smooth / atr_smooth.replace(0, np.nan)

    # DX and ADX
    dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    df["adx"]      = adx
    df["di_plus"]  = di_plus
    df["di_minus"] = di_minus

    return df


# ============================================================
# EMA SLOPE
# Measures how steeply the trend is rising or falling.
# A flat EMA = no trend. A steep EMA = strong trend.
# ============================================================

def compute_ema_slope(df: pd.DataFrame, period: int = 21) -> float:
    """
    Returns the normalized slope of the EMA over the last N periods.
    Positive = uptrend, Negative = downtrend, Near zero = flat.
    """
    if len(df) < period + 5:
        return 0.0

    ema = df["close"].ewm(span=period, adjust=False).mean()

    # Slope = change over last 5 bars, normalized by price level
    recent_ema = ema.iloc[-5:]
    if recent_ema.iloc[0] == 0:
        return 0.0

    slope = (recent_ema.iloc[-1] - recent_ema.iloc[0]) / recent_ema.iloc[0]
    return float(slope)


# ============================================================
# RANGE COMPRESSION
# Detects if price has been moving in a tight range (consolidation).
# Tight range often precedes a breakout — signals RANGE regime.
# ============================================================

def compute_range_compression(df: pd.DataFrame, lookback: int = 20) -> bool:
    """
    Returns True if price has been in a tight range recently.
    Calculated as: (high - low) / close over last N bars.
    """
    if len(df) < lookback:
        return False

    recent = df.iloc[-lookback:]
    price_range = (recent["high"].max() - recent["low"].min())
    mid_price   = recent["close"].mean()

    if mid_price == 0:
        return False

    compression_ratio = price_range / mid_price
    return compression_ratio < RANGE_COMPRESSION


# ============================================================
# MASTER REGIME DETECTION
# ============================================================

def detect_regime(df: pd.DataFrame) -> str:
    """
    Main function — detects market regime from price data.

    Logic:
        TREND   → ADX > 25 AND EMA slope is meaningful
        RANGE   → ADX < 20 OR price is compressed
        UNCLEAR → everything else

    Args:
        df: DataFrame with OHLCV columns (at least 50 rows recommended)

    Returns:
        "TREND" | "RANGE" | "UNCLEAR"
    """
    if df.empty or len(df) < 30:
        logger.warning("⚠️  Not enough data for regime detection — returning UNCLEAR")
        return "UNCLEAR"

    try:
        # Compute ADX
        df_adx = compute_adx(df)
        latest_adx = float(df_adx["adx"].iloc[-1])

        # Compute EMA slope
        ema_slope = compute_ema_slope(df)

        # Check range compression
        is_compressed = compute_range_compression(df)

        logger.debug(
            f"Regime inputs — ADX: {latest_adx:.1f} | "
            f"EMA slope: {ema_slope:.4f} | "
            f"Compressed: {is_compressed}"
        )

        # --- Decision logic ---

        # Strong trend: ADX above threshold AND meaningful slope
        if latest_adx > ADX_TREND_THRESHOLD and \
           abs(ema_slope) > EMA_SLOPE_THRESHOLD:
            return "TREND"

        # Ranging: ADX is low OR price is compressed
        if latest_adx < ADX_RANGE_THRESHOLD or is_compressed:
            return "RANGE"

        # Everything in between
        return "UNCLEAR"

    except Exception as e:
        logger.error(f"❌ Regime detection failed: {e}")
        return "UNCLEAR"


# ============================================================
# STRATEGY MATCH CHECK
# Checks if the current regime supports the intended strategy
# ============================================================

def is_regime_match(regime: str, strategy_type: str) -> bool:
    """
    Returns True if the market regime supports this strategy type.

    Conservative strategy = trend-following only
    Aggressive strategy   = trades both trend and range

    Args:
        regime:        "TREND" | "RANGE" | "UNCLEAR"
        strategy_type: "conservative" | "aggressive"

    Returns:
        True  → regime is suitable, proceed with signal evaluation
        False → regime mismatch, output HOLD
    """
    if regime == "UNCLEAR":
        # Neither strategy trades in unclear conditions
        return False

    if strategy_type == "conservative":
        # Conservative only trades strong trends
        return regime == "TREND"

    if strategy_type == "aggressive":
        # Aggressive trades both trends and ranges
        return regime in ("TREND", "RANGE")

    return False


# ============================================================
# HUMAN-READABLE SUMMARY
# Used in Claude prompt and end-of-day log
# ============================================================

def regime_summary(df: pd.DataFrame) -> dict:
    """
    Returns a dict with regime + supporting metrics.
    Gets injected into Claude's decision prompt.
    """
    if df.empty or len(df) < 30:
        return {
            "regime": "UNCLEAR",
            "adx": None,
            "ema_slope": None,
            "compressed": None,
            "description": "Insufficient data for regime detection"
        }

    try:
        df_adx     = compute_adx(df)
        adx_val    = round(float(df_adx["adx"].iloc[-1]), 2)
        slope      = round(compute_ema_slope(df), 4)
        compressed = compute_range_compression(df)
        regime     = detect_regime(df)

        descriptions = {
            "TREND":   f"Strong trend detected (ADX {adx_val}). "
                       f"Momentum {'up' if slope > 0 else 'down'}ward.",
            "RANGE":   f"Sideways/ranging market (ADX {adx_val}). "
                       f"{'Price compressed.' if compressed else 'Low directional momentum.'}",
            "UNCLEAR": f"Mixed signals (ADX {adx_val}). Defaulting to HOLD.",
        }

        return {
            "regime":      regime,
            "adx":         adx_val,
            "ema_slope":   slope,
            "compressed":  compressed,
            "description": descriptions[regime],
        }

    except Exception as e:
        logger.error(f"❌ Regime summary failed: {e}")
        return {
            "regime":      "UNCLEAR",
            "adx":         None,
            "ema_slope":   None,
            "compressed":  None,
            "description": f"Error: {e}"
        }
