"""
shared/macro_regime.py
======================
Determines the current macro market regime and maps it to a strategy mode.

Four modes — each triggers different behavior in both strategies:

  MOMENTUM      — Trending market, low VIX. Go long on breakouts.
  MEAN_REVERSION — Range-bound, choppy. Buy oversold, sell overbought.
  DEFENSIVE     — Bear market, high VIX. Conservative: cash. Aggressive: short ETFs.
  MACRO_EVENT   — VIX spike or extreme fear. Both strategies reduce exposure.

Detection logic:
  1. VIX level (LOW/ELEVATED/HIGH/EXTREME)
  2. VIX spike (>20% rise in 3 days) → quantitative macro event trigger
  3. SPY vs 200-day MA (above = bullish trend, below = bearish)
  4. ADX from the asset being evaluated (strong trend vs range)

This replaces narrative-based decisions ("Iran war") with measurable rules.
"""

import logging
from typing import Optional

import requests

from shared.vix import get_vix, get_vix_spike, classify_vix

logger = logging.getLogger(__name__)

SPY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/SPY"

# Mode definitions — what each means for trading
MODES = {
    "MOMENTUM":       "Trending market — go long momentum plays, larger positions",
    "MEAN_REVERSION": "Range-bound — buy oversold, sell overbought, smaller positions",
    "DEFENSIVE":      "Bear market — Conservative holds cash, Aggressive shorts SPY/QQQ",
    "MACRO_EVENT":    "Extreme uncertainty — both strategies reduce to minimum exposure",
}


def get_spy_vs_200ma() -> dict:
    """
    Fetches SPY price and checks if it's above or below 200-day MA.
    Above 200MA = structurally bullish.
    Below 200MA = structurally bearish.
    """
    try:
        headers  = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(
            SPY_URL, headers=headers,
            params={"range": "220d", "interval": "1d"},
            timeout=10,
        )
        if response.status_code != 200:
            return {"above_200ma": True, "spy_price": 0.0, "ma_200": 0.0}

        data   = response.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]

        if len(closes) < 200:
            return {"above_200ma": True, "spy_price": closes[-1] if closes else 0.0, "ma_200": 0.0}

        ma_200    = sum(closes[-200:]) / 200
        spy_price = closes[-1]
        above     = spy_price > ma_200

        logger.info(
            f"📊 SPY ${spy_price:.2f} vs 200MA ${ma_200:.2f} → "
            f"{'ABOVE ✅' if above else 'BELOW ❌'}"
        )
        return {"above_200ma": above, "spy_price": round(spy_price, 2), "ma_200": round(ma_200, 2)}

    except Exception as e:
        logger.error(f"❌ SPY/200MA check failed: {e}")
        return {"above_200ma": True, "spy_price": 0.0, "ma_200": 0.0}


def get_macro_mode() -> dict:
    """
    Main entry point — determines the current macro strategy mode.

    Decision logic (in priority order):
    1. VIX spike >20% in 3 days → MACRO_EVENT (quantitative, not narrative)
    2. VIX EXTREME (>30) → MACRO_EVENT
    3. VIX HIGH (25-30) + SPY below 200MA → DEFENSIVE
    4. VIX HIGH (25-30) + SPY above 200MA → MEAN_REVERSION (bear rally)
    5. VIX ELEVATED (20-25) + SPY below 200MA → MEAN_REVERSION
    6. VIX ELEVATED (20-25) + SPY above 200MA → MOMENTUM (cautious)
    7. VIX LOW (<20) → MOMENTUM (full conviction)

    Returns:
        {
            "mode":        str,    # MOMENTUM | MEAN_REVERSION | DEFENSIVE | MACRO_EVENT
            "vix":         float,
            "vix_level":   str,
            "vix_spike":   bool,
            "above_200ma": bool,
            "description": str,
        }
    """
    vix_data   = get_vix()
    spike_data = get_vix_spike(lookback_days=3)
    spy_data   = get_spy_vs_200ma()

    vix       = vix_data["vix"]
    vix_level = vix_data["level"]
    spike     = spike_data["spike"]
    above_ma  = spy_data["above_200ma"]

    # Priority 1: VIX spike (quantitative macro event trigger)
    if spike:
        mode = "MACRO_EVENT"

    # Priority 2: Extreme fear
    elif vix_level == "EXTREME":
        mode = "MACRO_EVENT"

    # Priority 3: High VIX + below 200MA = bear market
    elif vix_level == "HIGH" and not above_ma:
        mode = "DEFENSIVE"

    # Priority 4: High VIX but above 200MA = bear market rally, cautious
    elif vix_level == "HIGH" and above_ma:
        mode = "MEAN_REVERSION"

    # Priority 5: Elevated VIX + below 200MA = chop
    elif vix_level == "ELEVATED" and not above_ma:
        mode = "MEAN_REVERSION"

    # Priority 6: Elevated VIX + above 200MA = cautious momentum
    elif vix_level == "ELEVATED" and above_ma:
        mode = "MOMENTUM"

    # Priority 7: Low VIX = full momentum
    else:
        mode = "MOMENTUM"

    description = MODES[mode]

    logger.info(
        f"🌍 Macro Regime: {mode} | "
        f"VIX {vix:.1f} ({vix_level}) | "
        f"Spike: {spike} | "
        f"SPY {'above' if above_ma else 'below'} 200MA"
    )

    return {
        "mode":        mode,
        "vix":         vix,
        "vix_level":   vix_level,
        "vix_spike":   spike,
        "above_200ma": above_ma,
        "spy_price":   spy_data["spy_price"],
        "ma_200":      spy_data["ma_200"],
        "description": description,
    }
