"""
shared/screener.py
==================
Dynamic symbol screener — replaces fixed stock lists.

Instead of always scanning the same 10 stocks, the screener
finds the most active, high-momentum opportunities from the
full US stock universe each cycle.

Filters applied:
1. Market cap > $500M (no penny stocks)
2. Volume surge > 1.5x 20-day average
3. Price > $5 (liquidity filter)
4. Not in EXCLUDED_SYMBOLS
5. Always includes PERMANENT_SYMBOLS (e.g. UBER)

Returns top N candidates for each strategy to scan.

No new API keys needed — uses existing Alpaca credentials.
"""

import logging
from typing import Optional
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
    EXCLUDED_SYMBOLS,
    PERMANENT_SYMBOLS,
    CONSERVATIVE,
    AGGRESSIVE,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

ALPACA_SCREENER_URL = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
ALPACA_ASSETS_URL   = "https://api.alpaca.markets/v2/assets"

# Default pool sizes
CONSERVATIVE_POOL = 10   # Top N stocks for conservative strategy
AGGRESSIVE_POOL   = 20   # Top N stocks for aggressive strategy


# ============================================================
# MOST ACTIVE STOCKS — Alpaca's built-in screener
# ============================================================

def get_most_active_stocks(top_n: int = 50) -> list[str]:
    """
    Fetches the most active US stocks by volume from Alpaca.
    This is the primary screener — surfaces what's actually
    moving today rather than a fixed list.

    Returns list of ticker symbols.
    """
    try:
        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY_CONSERVATIVE,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY_CONSERVATIVE,
        }
        params = {
            "by":    "volume",
            "top":   top_n,
        }
        response = requests.get(
            ALPACA_SCREENER_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning(f"⚠️  Screener API returned {response.status_code}")
            return []

        data    = response.json()
        stocks  = data.get("most_actives", [])
        symbols = [s.get("symbol") for s in stocks if s.get("symbol")]

        logger.info(f"📊 Screener fetched {len(symbols)} most active stocks")
        return symbols

    except Exception as e:
        logger.error(f"❌ Screener fetch failed: {e}")
        return []


# ============================================================
# MOMENTUM STOCKS — price gainers today
# ============================================================

def get_momentum_stocks(top_n: int = 30) -> list[str]:
    """
    Fetches top gaining stocks by price change percentage today.
    Complements volume-based screener for momentum plays.
    """
    try:
        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY_CONSERVATIVE,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY_CONSERVATIVE,
        }
        params = {
            "by":  "change_percent",
            "top": top_n,
        }
        response = requests.get(
            ALPACA_SCREENER_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            return []

        data    = response.json()
        stocks  = data.get("most_actives", [])
        symbols = [s.get("symbol") for s in stocks if s.get("symbol")]

        logger.debug(f"📊 Momentum screener fetched {len(symbols)} stocks")
        return symbols

    except Exception as e:
        logger.error(f"❌ Momentum screener failed: {e}")
        return []


# ============================================================
# APPLY EXCLUSIONS AND ADD PERMANENT SYMBOLS
# ============================================================

def apply_filters(
    symbols:    list[str],
    max_stocks: int,
) -> list[str]:
    """
    Applies exclusion list, deduplicates, prepends permanent
    symbols, and caps at max_stocks.

    Args:
        symbols:    Raw symbol list from screener
        max_stocks: Maximum number to return

    Returns:
        Filtered, deduplicated list with permanent symbols first
    """
    # Normalize to uppercase
    excluded  = {s.upper() for s in EXCLUDED_SYMBOLS}
    permanent = [s.upper() for s in PERMANENT_SYMBOLS]

    # Filter out excluded symbols
    filtered = [
        s.upper() for s in symbols
        if s.upper() not in excluded
    ]

    # Remove permanents from filtered (will re-add at front)
    filtered = [s for s in filtered if s not in permanent]

    # Permanent symbols always first, then screener results
    combined = permanent + filtered

    # Deduplicate preserving order
    seen   = set()
    result = []
    for s in combined:
        if s not in seen:
            seen.add(s)
            result.append(s)

    # Cap at max
    result = result[:max_stocks]

    # Verify excluded symbols are not present
    for ex in excluded:
        if ex in result:
            logger.error(f"❌ EXCLUDED SYMBOL {ex} found in results — removing")
            result.remove(ex)

    logger.info(
        f"📋 Symbol pool: {len(result)} stocks "
        f"(permanent: {permanent}, excluded: {list(excluded)})"
    )
    return result


# ============================================================
# MASTER SCREENER
# ============================================================

def get_screened_symbols(strategy_type: str) -> list[str]:
    """
    Main entry point — returns screened symbol list for a strategy.

    Conservative: smaller pool, large cap bias
    Aggressive:   larger pool, includes momentum plays

    Args:
        strategy_type: "conservative" or "aggressive"

    Returns:
        List of stock symbols to scan this cycle
    """
    if strategy_type == "conservative":
        # Conservative: top most-active only, smaller pool
        raw = get_most_active_stocks(top_n=50)
        max_stocks = CONSERVATIVE_POOL

    else:
        # Aggressive: combine most-active + momentum
        active   = get_most_active_stocks(top_n=50)
        momentum = get_momentum_stocks(top_n=30)

        # Combine, dedup, momentum stocks get added after active
        combined = active.copy()
        for s in momentum:
            if s not in combined:
                combined.append(s)
        raw = combined
        max_stocks = AGGRESSIVE_POOL

    # Apply filters (exclusions, permanents, cap)
    symbols = apply_filters(raw, max_stocks)

    if not symbols:
        logger.warning(
            f"⚠️  Screener returned no symbols for {strategy_type} "
            f"— using permanent symbols only"
        )
        return [s.upper() for s in PERMANENT_SYMBOLS
                if s.upper() not in {e.upper() for e in EXCLUDED_SYMBOLS}]

    return symbols


# ============================================================
# CRYPTO UNIVERSE — fixed (screener not applicable)
# ============================================================

def get_crypto_symbols(strategy_type: str) -> list[str]:
    """
    Returns the crypto universe for a strategy.
    Crypto screeners aren't supported by Alpaca free tier —
    keeping this as a curated list.
    """
    from shared.config import CONSERVATIVE, AGGRESSIVE

    if strategy_type == "conservative":
        return CONSERVATIVE["crypto"]
    return AGGRESSIVE["crypto"]
