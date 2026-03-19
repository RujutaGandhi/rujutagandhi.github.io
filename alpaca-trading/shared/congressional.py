"""
shared/congressional.py
=======================
Checks for recent congressional trading activity on a symbol.

Why this matters:
- Members of Congress must disclose trades within 45 days (STOCK Act)
- Politicians on key committees often trade ahead of policy decisions
- Congressional buying = insider-adjacent signal with legal public data
- Used as a CONFIRMATION signal — boosts conviction on already-bullish setups

Data source: Capitol Trades API (free, no key required)
Delay: Up to 45 days (legal disclosure window)

Returns:
    {
        "has_recent_activity": bool,
        "points":              int (-1, 0, or +2),
        "signal":              "BULLISH" | "BEARISH" | "NEUTRAL",
        "recent_trades":       list of trade dicts,
        "summary":             str,
    }
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import requests

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Capitol Trades API (free, no key)
CAPITOL_TRADES_URL = "https://www.capitoltrades.com/api/trades"

# How many days back to check for trades
LOOKBACK_DAYS = 45

# Point values
CONGRESSIONAL_POINTS = {
    "BULLISH":  2,   # Recent buying by politicians
    "BEARISH": -1,   # Recent selling by politicians
    "NEUTRAL":  0,   # No recent activity
}


def get_congressional_trades(symbol: str) -> list[dict]:
    """
    Fetches recent congressional trades for a symbol.

    Args:
        symbol: Stock ticker e.g. "AAPL" (crypto not applicable)

    Returns:
        List of trade dicts with politician, action, date, amount
    """
    # Crypto not applicable
    if "/" in symbol:
        return []

    try:
        since = (
            datetime.now(ET) - timedelta(days=LOOKBACK_DAYS)
        ).strftime("%Y-%m-%d")

        params = {
            "ticker":   symbol.upper(),
            "dateFrom": since,
            "pageSize": 10,
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
            "Accept":     "application/json",
        }

        response = requests.get(
            CAPITOL_TRADES_URL,
            params=params,
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            logger.debug(
                f"Capitol Trades API returned {response.status_code} for {symbol}"
            )
            return []

        data   = response.json()
        trades = data.get("trades", []) or data.get("data", [])

        parsed = []
        for trade in trades[:5]:  # Cap at 5 most recent
            parsed.append({
                "politician": trade.get("politician", {}).get("name", "Unknown"),
                "party":      trade.get("politician", {}).get("party", "Unknown"),
                "action":     trade.get("type", "unknown").upper(),
                "date":       trade.get("txDate", ""),
                "amount":     trade.get("amount", "Unknown"),
                "chamber":    trade.get("politician", {}).get("chamber", "Unknown"),
            })

        logger.debug(f"📊 Found {len(parsed)} congressional trades for {symbol}")
        return parsed

    except Exception as e:
        logger.error(f"❌ Congressional trades fetch failed for {symbol}: {e}")
        return []


def analyze_congressional_signal(trades: list[dict]) -> dict:
    """
    Analyzes congressional trades to produce a signal.

    Logic:
    - More buys than sells → BULLISH (+2 pts)
    - More sells than buys → BEARISH (-1 pt)
    - Equal or no trades  → NEUTRAL (0 pts)
    """
    if not trades:
        return {
            "has_recent_activity": False,
            "points":              0,
            "signal":              "NEUTRAL",
            "recent_trades":       [],
            "summary":             "No congressional trades in last 45 days",
        }

    buys  = [t for t in trades if "BUY"  in t.get("action", "").upper() or "PURCHASE" in t.get("action", "").upper()]
    sells = [t for t in trades if "SELL" in t.get("action", "").upper()]

    if len(buys) > len(sells):
        signal = "BULLISH"
        summary = (
            f"{len(buys)} congressional purchase(s) in last 45 days. "
            f"Most recent: {buys[0]['politician']} ({buys[0]['party']}) "
            f"bought {buys[0]['amount']} on {buys[0]['date']}"
        )
    elif len(sells) > len(buys):
        signal = "BEARISH"
        summary = (
            f"{len(sells)} congressional sale(s) in last 45 days. "
            f"Most recent: {sells[0]['politician']} ({sells[0]['party']}) "
            f"sold {sells[0]['amount']} on {sells[0]['date']}"
        )
    else:
        signal  = "NEUTRAL"
        summary = f"{len(trades)} congressional trade(s) — equal buys and sells, no clear signal"

    return {
        "has_recent_activity": True,
        "points":              CONGRESSIONAL_POINTS[signal],
        "signal":              signal,
        "recent_trades":       trades,
        "summary":             summary,
    }


def get_congressional_signal(symbol: str) -> dict:
    """
    Main entry point — fetches and analyzes congressional trades.

    Args:
        symbol: e.g. "AAPL", "BTC/USD"

    Returns:
        Signal dict ready for injection into scoring engine
    """
    # Crypto not applicable
    if "/" in symbol:
        return {
            "has_recent_activity": False,
            "points":              0,
            "signal":              "NEUTRAL",
            "recent_trades":       [],
            "summary":             "Congressional trades not applicable for crypto",
        }

    trades = get_congressional_trades(symbol)
    return analyze_congressional_signal(trades)
