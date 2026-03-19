"""
shared/risk_guardian.py
=======================
Central risk management layer — monitors both portfolios every cycle.

Checks:
1. Portfolio floor (permanent kill switch)
2. Daily loss limit (daily stop — resets next day)
3. Market hours (no new trades outside hours)
4. Position correlation (prevents taking same bet twice)

This runs BEFORE either strategy makes any decisions.
If risk checks fail, the cycle is skipped entirely.
"""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from shared.config import CONSERVATIVE, AGGRESSIVE, MARKET_OPEN_HOUR, MARKET_OPEN_MIN, MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN, NO_NEW_TRADES_MINS_BEFORE_CLOSE
from shared.alerts import alert_kill_switch, alert_daily_stop

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ============================================================
# MARKET HOURS
# ============================================================

def is_market_open() -> bool:
    """
    Returns True if US stock market is currently open.
    Crypto trades 24/7 — this only gates stock trades.
    """
    now = datetime.now(ET)

    # Weekend check
    if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False

    market_open  = time(MARKET_OPEN_HOUR,  MARKET_OPEN_MIN)
    market_close = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN)

    return market_open <= now.time() <= market_close


def is_near_market_close() -> bool:
    """
    Returns True if within NO_NEW_TRADES_MINS_BEFORE_CLOSE
    minutes of market close. No new stock trades in this window.
    """
    now = datetime.now(ET)

    if now.weekday() >= 5:
        return False

    market_close = datetime.now(ET).replace(
        hour=MARKET_CLOSE_HOUR,
        minute=MARKET_CLOSE_MIN,
        second=0,
        microsecond=0,
    )

    mins_to_close = (market_close - now).total_seconds() / 60
    return 0 <= mins_to_close <= NO_NEW_TRADES_MINS_BEFORE_CLOSE


def can_trade_stock() -> bool:
    """Stock trades allowed only during market hours, not near close."""
    return is_market_open() and not is_near_market_close()


def can_trade_crypto() -> bool:
    """Crypto trades 24/7 but not near stock market close."""
    return not is_near_market_close()


# ============================================================
# PORTFOLIO RISK CHECKS
# ============================================================

def check_kill_switch(
    strategy_name: str,
    portfolio_value: float,
    floor: float,
) -> bool:
    """
    Returns True if kill switch should trigger (portfolio below floor).
    Sends alert if triggered.
    """
    if portfolio_value <= floor:
        logger.critical(
            f"🔴 [{strategy_name}] KILL SWITCH — "
            f"Portfolio ${portfolio_value:,.2f} below floor ${floor:,.2f}"
        )
        alert_kill_switch(
            strategy_name=strategy_name,
            portfolio_value=portfolio_value,
            floor_value=floor,
        )
        return True
    return False


def check_daily_stop(
    strategy_name: str,
    portfolio_value: float,
    today_open_value: float,
    daily_stop_pct: float,
) -> bool:
    """
    Returns True if daily stop should trigger.
    Sends alert if triggered.
    """
    if not today_open_value or today_open_value == 0:
        return False

    daily_loss_pct = (today_open_value - portfolio_value) / today_open_value

    if daily_loss_pct >= daily_stop_pct:
        logger.warning(
            f"🟡 [{strategy_name}] Daily stop — "
            f"Loss: {daily_loss_pct:.1%} >= threshold {daily_stop_pct:.1%}"
        )
        alert_daily_stop(
            strategy_name=strategy_name,
            portfolio_value=portfolio_value,
            daily_loss_pct=daily_loss_pct * 100,
            threshold_pct=daily_stop_pct * 100,
        )
        return True
    return False


# ============================================================
# POSITION CORRELATION CHECK
# Prevents taking 3 positions that all move together
# e.g. NVDA + AMD + SMCI = all chip stocks = same bet
# ============================================================

# Simple correlation groups — assets that tend to move together
CORRELATION_GROUPS = {
    "mega_cap_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "ai_chips":      ["NVDA", "AMD", "SMCI", "INTC"],
    "ev":            ["TSLA", "RIVN", "LCID"],
    "fintech":       ["HOOD", "COIN", "SOFI", "V", "JPM"],
    "crypto_major":  ["BTCUSD", "BTC/USD"],
    "crypto_eth":    ["ETHUSD", "ETH/USD"],
    "crypto_alt":    ["SOLUSD", "DOGEUSD", "AVAXUSD", "SOL/USD", "DOGE/USD", "AVAX/USD"],
    "ai_software":   ["PLTR", "IONQ", "MSTR"],
}

def check_correlation(
    new_symbol: str,
    open_positions: list[str],
    max_per_group: int = 1,
) -> bool:
    """
    Returns True if adding new_symbol would exceed correlation limit.
    Default: max 1 position per correlation group.

    Args:
        new_symbol:     Symbol we want to add
        open_positions: Currently held symbols
        max_per_group:  Max positions allowed in same group

    Returns:
        True  → correlated, do NOT add this position
        False → safe to add
    """
    new_clean = new_symbol.replace("/", "").upper()

    for group_name, group_symbols in CORRELATION_GROUPS.items():
        group_upper = [s.upper() for s in group_symbols]

        # Is new symbol in this group?
        if new_clean not in group_upper:
            continue

        # Count existing positions in this group
        existing_in_group = sum(
            1 for pos in open_positions
            if pos.replace("/", "").upper() in group_upper
        )

        if existing_in_group >= max_per_group:
            logger.info(
                f"⚠️  Correlation block: {new_symbol} is in group "
                f"'{group_name}' which already has {existing_in_group} position(s)."
            )
            return True  # Correlated — block it

    return False  # Safe to add


# ============================================================
# FULL PRE-CYCLE RISK CHECK
# Call this at the start of every strategy cycle
# ============================================================

def run_risk_checks(
    strategy_name: str,
    portfolio_value: float,
    today_open_value: float,
    config: dict,
    is_killed: bool,
    is_stopped_today: bool,
) -> dict:
    """
    Runs all risk checks before a strategy cycle.

    Returns a status dict:
    {
        "can_trade":      bool,   # False = skip this cycle entirely
        "kill_switch":    bool,   # Permanent halt
        "daily_stop":     bool,   # Stop for today only
        "reason":         str,    # Why trading is blocked (if blocked)
        "stock_allowed":  bool,   # Can we trade stocks this cycle?
        "crypto_allowed": bool,   # Can we trade crypto this cycle?
    }
    """
    # Already killed
    if is_killed:
        return {
            "can_trade":      False,
            "kill_switch":    True,
            "daily_stop":     False,
            "reason":         "Bot permanently halted by kill switch",
            "stock_allowed":  False,
            "crypto_allowed": False,
        }

    # Already stopped today
    if is_stopped_today:
        return {
            "can_trade":      False,
            "kill_switch":    False,
            "daily_stop":     True,
            "reason":         "Daily stop active — resuming tomorrow",
            "stock_allowed":  False,
            "crypto_allowed": False,
        }

    # Kill switch check
    if check_kill_switch(strategy_name, portfolio_value, config["portfolio_floor"]):
        return {
            "can_trade":      False,
            "kill_switch":    True,
            "daily_stop":     False,
            "reason":         f"Portfolio ${portfolio_value:,.2f} below floor ${config['portfolio_floor']:,.2f}",
            "stock_allowed":  False,
            "crypto_allowed": False,
        }

    # Daily stop check
    if check_daily_stop(
        strategy_name, portfolio_value,
        today_open_value, config["daily_stop_pct"]
    ):
        return {
            "can_trade":      False,
            "kill_switch":    False,
            "daily_stop":     True,
            "reason":         "Daily loss threshold exceeded",
            "stock_allowed":  False,
            "crypto_allowed": False,
        }

    # Market hours check
    stock_ok  = can_trade_stock()
    crypto_ok = can_trade_crypto()

    if not stock_ok and not crypto_ok:
        return {
            "can_trade":      False,
            "kill_switch":    False,
            "daily_stop":     False,
            "reason":         "Near market close — no new trades",
            "stock_allowed":  False,
            "crypto_allowed": False,
        }

    # All checks passed
    now = datetime.now(ET).strftime("%H:%M ET")
    logger.info(
        f"[{strategy_name}] ✅ Risk checks passed at {now} — "
        f"Stocks: {'✓' if stock_ok else '✗'} | "
        f"Crypto: {'✓' if crypto_ok else '✗'} | "
        f"Portfolio: ${portfolio_value:,.2f}"
    )

    return {
        "can_trade":      True,
        "kill_switch":    False,
        "daily_stop":     False,
        "reason":         "All checks passed",
        "stock_allowed":  stock_ok,
        "crypto_allowed": crypto_ok,
    }
