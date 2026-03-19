"""
shared/earnings.py
==================
Checks if a symbol has earnings within the next N days.
If yes — returns a VETO that blocks all new trades regardless of score.

Why this matters:
- Earnings = binary event with massive unpredictable volatility
- Even strong signals can be wiped out by a single earnings miss
- No amount of bullish indicators justifies the risk of holding into earnings
- This is a hard veto, not a scored signal

Uses Alpaca's free calendar/earnings endpoint.

Returns:
    {
        "has_upcoming_earnings": bool,
        "earnings_date":         str | None,
        "days_until_earnings":   int | None,
        "veto":                  bool,   # True = block this trade
        "veto_reason":           str,
    }
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import requests

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# How many days before earnings to block new trades
EARNINGS_BLACKOUT_DAYS = 2

# Alpaca corporate actions / calendar endpoint
ALPACA_CALENDAR_URL = "https://data.alpaca.markets/v1beta1/corporate-actions/announcements"


# ============================================================
# FETCH EARNINGS DATE
# ============================================================

def get_earnings_date(symbol: str) -> Optional[str]:
    """
    Fetches the next earnings date for a stock symbol.
    Returns date string "YYYY-MM-DD" or None if not found.

    Note: Crypto has no earnings — always returns None.
    """
    # Crypto never has earnings
    if "/" in symbol or symbol in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "AVAXUSD"):
        return None

    try:
        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY_CONSERVATIVE,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY_CONSERVATIVE,
        }

        today    = datetime.now(ET).date()
        end_date = today + timedelta(days=30)  # Look 30 days ahead

        params = {
            "ca_types": "earnings",
            "symbols":  symbol,
            "since":    today.strftime("%Y-%m-%d"),
            "until":    end_date.strftime("%Y-%m-%d"),
        }

        response = requests.get(
            ALPACA_CALENDAR_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            logger.debug(f"Earnings API returned {response.status_code} for {symbol}")
            return None

        data         = response.json()
        announcements = data.get("announcements", [])

        if not announcements:
            return None

        # Return the earliest upcoming earnings date
        dates = [a.get("ex_date") or a.get("record_date") for a in announcements if a.get("ex_date") or a.get("record_date")]
        if dates:
            return min(dates)

        return None

    except Exception as e:
        logger.error(f"❌ Failed to fetch earnings for {symbol}: {e}")
        return None


# ============================================================
# VETO CHECK
# ============================================================

def check_earnings_veto(symbol: str) -> dict:
    """
    Main entry point — checks if symbol has earnings within
    the blackout window and returns a veto decision.

    Args:
        symbol: e.g. "AAPL", "BTC/USD"

    Returns:
        Dict with veto flag and reasoning
    """
    # Crypto never vetoed for earnings
    if "/" in symbol:
        return _no_veto("Crypto — no earnings calendar")

    earnings_date = get_earnings_date(symbol)

    if not earnings_date:
        return _no_veto("No upcoming earnings found in next 30 days")

    try:
        today          = datetime.now(ET).date()
        earnings_dt    = datetime.strptime(earnings_date, "%Y-%m-%d").date()
        days_until     = (earnings_dt - today).days

        if days_until <= EARNINGS_BLACKOUT_DAYS:
            logger.warning(
                f"⚠️  EARNINGS VETO: {symbol} reports in {days_until} day(s) "
                f"on {earnings_date}"
            )
            return {
                "has_upcoming_earnings": True,
                "earnings_date":         earnings_date,
                "days_until_earnings":   days_until,
                "veto":                  True,
                "veto_reason": (
                    f"Earnings in {days_until} day(s) ({earnings_date}) — "
                    f"no new positions within {EARNINGS_BLACKOUT_DAYS} days of earnings"
                ),
            }

        # Earnings exist but outside blackout window
        return {
            "has_upcoming_earnings": True,
            "earnings_date":         earnings_date,
            "days_until_earnings":   days_until,
            "veto":                  False,
            "veto_reason":           f"Earnings in {days_until} days — outside blackout window",
        }

    except Exception as e:
        logger.error(f"❌ Earnings veto check failed for {symbol}: {e}")
        return _no_veto(f"Error checking earnings — defaulting to no veto")


def _no_veto(reason: str) -> dict:
    """Returns a safe no-veto result."""
    return {
        "has_upcoming_earnings": False,
        "earnings_date":         None,
        "days_until_earnings":   None,
        "veto":                  False,
        "veto_reason":           reason,
    }
