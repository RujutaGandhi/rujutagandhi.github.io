"""
shared/vix.py
=============
Fetches live VIX level from Yahoo Finance (free, no API key needed).

VIX = CBOE Volatility Index — Wall Street's "fear gauge."
Higher VIX = more market fear = more uncertainty.

VIX Levels:
  < 20        = LOW       — calm market, momentum strategies work
  20–25       = ELEVATED  — caution, reduce position sizes
  25–30       = HIGH      — defensive posture
  > 30        = EXTREME   — macro event mode, minimal trading
"""

import logging
import requests

logger = logging.getLogger(__name__)

VIX_URL      = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
VIX_LOW      = 20
VIX_ELEVATED = 25
VIX_HIGH     = 30


def get_vix() -> dict:
    """
    Fetches current VIX from Yahoo Finance.
    Returns: {"vix": float, "level": str}
    """
    try:
        headers  = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(VIX_URL, headers=headers, timeout=10)
        if response.status_code != 200:
            return _default_vix()
        data  = response.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        vix   = float(price)
        level = classify_vix(vix)
        logger.info(f"📊 VIX: {vix:.2f} → {level}")
        return {"vix": vix, "level": level}
    except Exception as e:
        logger.error(f"❌ VIX fetch failed: {e}")
        return _default_vix()


def classify_vix(vix: float) -> str:
    if vix < VIX_LOW:      return "LOW"
    elif vix < VIX_ELEVATED: return "ELEVATED"
    elif vix < VIX_HIGH:   return "HIGH"
    else:                  return "EXTREME"


def get_vix_spike(lookback_days: int = 3) -> dict:
    """
    Checks if VIX spiked >20% in the last N days.
    Quantitative trigger for MACRO_EVENT mode — no narrative needed.
    """
    try:
        headers  = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(
            VIX_URL, headers=headers,
            params={"range": f"{lookback_days}d", "interval": "1d"},
            timeout=10,
        )
        if response.status_code != 200:
            return {"spike": False, "spike_pct": 0.0, "current_vix": 20.0}
        data    = response.json()
        closes  = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes  = [c for c in closes if c is not None]
        if len(closes) < 2:
            return {"spike": False, "spike_pct": 0.0, "current_vix": closes[-1] if closes else 20.0}
        spike_pct   = ((closes[-1] - closes[0]) / closes[0]) * 100
        spike       = spike_pct >= 20.0
        if spike:
            logger.warning(f"⚠️  VIX spike: {closes[0]:.1f}→{closes[-1]:.1f} (+{spike_pct:.1f}%)")
        return {"spike": spike, "spike_pct": round(spike_pct, 2), "current_vix": round(closes[-1], 2)}
    except Exception as e:
        logger.error(f"❌ VIX spike check failed: {e}")
        return {"spike": False, "spike_pct": 0.0, "current_vix": 20.0}


def _default_vix() -> dict:
    return {"vix": 22.0, "level": "ELEVATED"}
