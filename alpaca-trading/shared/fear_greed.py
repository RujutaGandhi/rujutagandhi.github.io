"""
shared/fear_greed.py
====================
Fetches the CNN Fear & Greed Index as a macro market filter.

Why this matters:
- Single number (0-100) that captures overall market sentiment
- Extreme Fear (<25)  = market oversold = contrarian BUY opportunity
- Extreme Greed (>75) = market overbought = reduce risk, be cautious
- Adds macro context that technical indicators completely miss

Free — no API key required.
Updates once per day.

Returns:
    {
        "score":        int (0-100),
        "label":        "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed",
        "points":       int (-1 to +2),
        "implication":  str,
        "raw_data":     dict,
    }
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# CNN Fear & Greed API (free, no key needed)
FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# Point values per zone (used in scoring engine)
FEAR_GREED_POINTS = {
    "Extreme Fear":  2,   # Strong contrarian buy signal
    "Fear":          1,   # Mild buy lean
    "Neutral":       0,   # No adjustment
    "Greed":         0,   # Slight caution but no penalty
    "Extreme Greed": -1,  # Reduce risk
}

# Zone boundaries
ZONES = [
    (0,  25,  "Extreme Fear"),
    (25, 45,  "Fear"),
    (45, 55,  "Neutral"),
    (55, 75,  "Greed"),
    (75, 100, "Extreme Greed"),
]


def get_label(score: float) -> str:
    """Returns the Fear & Greed label for a given score."""
    for low, high, label in ZONES:
        if low <= score <= high:
            return label
    return "Neutral"


def get_implication(label: str, score: int) -> str:
    """Returns a plain English trading implication."""
    implications = {
        "Extreme Fear": (
            f"Market in extreme fear (score: {score}). "
            "Historically a contrarian buy opportunity — "
            "aggressive strategy may find oversold setups."
        ),
        "Fear": (
            f"Market fearful (score: {score}). "
            "Slightly favorable for contrarian entries. "
            "Focus on strong fundamentals."
        ),
        "Neutral": (
            f"Market sentiment neutral (score: {score}). "
            "No macro bias — let technical signals lead."
        ),
        "Greed": (
            f"Market greedy (score: {score}). "
            "Exercise normal caution. "
            "Avoid chasing momentum."
        ),
        "Extreme Greed": (
            f"Market in extreme greed (score: {score}). "
            "Elevated risk of correction. "
            "Conservative strategy should reduce position sizes."
        ),
    }
    return implications.get(label, "Neutral market conditions.")


def get_fear_greed() -> dict:
    """
    Fetches the current Fear & Greed index from CNN.
    Returns a scored dict ready for injection into Claude prompt.

    Falls back to neutral (score 50) on any error —
    never crashes the bot over a macro indicator.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
            "Accept":     "application/json",
        }

        response = requests.get(
            FEAR_GREED_URL,
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning(
                f"⚠️  Fear & Greed API returned {response.status_code} — using neutral"
            )
            return _neutral_fear_greed()

        data  = response.json()
        score = round(float(data.get("fear_and_greed", {}).get("score", 50)))
        label = get_label(score)

        result = {
            "score":       score,
            "label":       label,
            "points":      FEAR_GREED_POINTS.get(label, 0),
            "implication": get_implication(label, score),
            "raw_data":    data.get("fear_and_greed", {}),
        }

        logger.debug(f"Fear & Greed: {score} ({label}) → {result['points']} pts")
        return result

    except Exception as e:
        logger.error(f"❌ Fear & Greed fetch failed: {e}")
        return _neutral_fear_greed()


def _neutral_fear_greed() -> dict:
    """Returns neutral Fear & Greed on error — safe fallback."""
    return {
        "score":       50,
        "label":       "Neutral",
        "points":      0,
        "implication": "Fear & Greed data unavailable — neutral assumption",
        "raw_data":    {},
    }
