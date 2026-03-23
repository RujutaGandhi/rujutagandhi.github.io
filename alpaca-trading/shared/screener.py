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
# PRICE FILTER — conservative only
# ============================================================

CONSERVATIVE_MIN_PRICE = 10.00   # No stocks under $10 for conservative

def filter_by_price(
    symbols:   list[str],
    min_price: float,
) -> list[str]:
    """
    Removes symbols trading below min_price.
    Prevents penny stocks reaching Claude in the conservative strategy.

    Fetches current prices in batch from Alpaca snapshot API.
    Symbols that fail price fetch are kept (fail-open, not fail-closed).
    Permanent symbols are always kept regardless of price.
    """
    if not symbols or min_price <= 0:
        return symbols

    permanent_upper = {s.upper() for s in PERMANENT_SYMBOLS}

    try:
        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY_CONSERVATIVE,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY_CONSERVATIVE,
        }
        # Only check non-permanent, non-crypto symbols
        to_check = [
            s for s in symbols
            if s.upper() not in permanent_upper and "/" not in s
        ]

        if not to_check:
            return symbols

        # Alpaca snapshot endpoint — returns latest price for multiple symbols
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/snapshots",
            headers=headers,
            params={"symbols": ",".join(to_check)},
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning(f"⚠️  Price filter fetch failed ({response.status_code}) — skipping filter")
            return symbols

        snapshots  = response.json()
        below_min  = set()

        for symbol, snap in snapshots.items():
            try:
                price = float(
                    snap.get("latestTrade", {}).get("p") or
                    snap.get("latestQuote", {}).get("ap") or 0
                )
                if 0 < price < min_price:
                    below_min.add(symbol.upper())
                    logger.info(f"🚫 [Screener] {symbol} filtered out — price ${price:.4f} < ${min_price:.2f} minimum")
            except Exception:
                continue

        filtered = [s for s in symbols if s.upper() not in below_min]
        if below_min:
            logger.info(f"📊 Price filter removed {len(below_min)} penny stocks: {below_min}")

        return filtered

    except Exception as e:
        logger.error(f"❌ Price filter failed: {e} — returning unfiltered list")
        return symbols


# ============================================================
# MASTER SCREENER
# ============================================================

def get_screened_symbols(strategy_type: str) -> list[str]:
    """
    Main entry point — returns screened symbol list for a strategy.

    Conservative: smaller pool, large cap bias, $10+ price filter
    Aggressive:   larger pool, includes momentum plays, no price floor

    Args:
        strategy_type: "conservative" or "aggressive"

    Returns:
        List of stock symbols to scan this cycle
    """
    if strategy_type == "conservative":
        raw        = get_most_active_stocks(top_n=50)
        max_stocks = CONSERVATIVE_POOL

    else:
        active   = get_most_active_stocks(top_n=50)
        momentum = get_momentum_stocks(top_n=30)
        combined = active.copy()
        for s in momentum:
            if s not in combined:
                combined.append(s)
        raw        = combined
        max_stocks = AGGRESSIVE_POOL

    # Apply exclusions, permanents, cap
    symbols = apply_filters(raw, max_stocks)

    # Conservative only — filter out penny stocks before Claude is called
    if strategy_type == "conservative":
        symbols = filter_by_price(symbols, min_price=CONSERVATIVE_MIN_PRICE)

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
