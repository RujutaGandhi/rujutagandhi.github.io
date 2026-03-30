"""
shared/risk_guardian.py
=======================
Central risk management — monitors both portfolios every cycle.

Phase 7 additions:
- Combined portfolio kill switch ($1,700 floor on $2,000 combined)
- Sector exposure check (max 30% any sector)
- Short squeeze monitor (force cover if ETF rises 5% intraday)
- Short stop loss checker (force cover if short up 8% against us)
"""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import List, Optional

from shared.config import (
    CONSERVATIVE, AGGRESSIVE,
    MARKET_OPEN_HOUR, MARKET_OPEN_MIN,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN,
    NO_NEW_TRADES_MINS_BEFORE_CLOSE,
    COMBINED_PORTFOLIO_FLOOR,
    COMBINED_DAILY_STOP_PCT,
    COMBINED_STARTING_CAPITAL,
    SECTOR_MAP, SECTOR_CAP_PCT,
)
from shared.alerts import alert_kill_switch, alert_daily_stop

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ============================================================
# MARKET HOURS
# ============================================================

def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    market_open  = time(MARKET_OPEN_HOUR, MARKET_OPEN_MIN)
    market_close = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN)
    return market_open <= now.time() <= market_close


def is_near_market_close() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN,
        second=0, microsecond=0,
    )
    mins_to_close = (market_close - now).total_seconds() / 60
    return 0 <= mins_to_close <= NO_NEW_TRADES_MINS_BEFORE_CLOSE


def can_trade_stock() -> bool:
    return is_market_open() and not is_near_market_close()


def can_trade_crypto() -> bool:
    return not is_near_market_close()


# ============================================================
# INDIVIDUAL STRATEGY CHECKS (unchanged)
# ============================================================

def check_kill_switch(strategy_name: str, portfolio_value: float,
                      floor: float) -> bool:
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


def check_daily_stop(strategy_name: str, portfolio_value: float,
                     today_open_value: float, daily_stop_pct: float) -> bool:
    if not today_open_value or today_open_value == 0:
        return False
    daily_loss_pct = (today_open_value - portfolio_value) / today_open_value
    if daily_loss_pct >= daily_stop_pct:
        logger.warning(
            f"🟡 [{strategy_name}] Daily stop — "
            f"Loss: {daily_loss_pct:.1%} >= {daily_stop_pct:.1%}"
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
# COMBINED PORTFOLIO KILL SWITCH (Phase 7 — NEW)
# ============================================================

def check_combined_portfolio(
    con_value: float,
    agg_value: float,
    combined_today_open: float,
) -> dict:
    """
    Checks the combined portfolio value across both strategies.
    Fires if total drops below COMBINED_PORTFOLIO_FLOOR ($1,700).
    Also fires if combined daily loss exceeds COMBINED_DAILY_STOP_PCT (8%).

    This protects you when individual strategy floors haven't triggered
    but combined losses are significant.

    Returns:
        {
            "halt":   bool,
            "reason": str,
            "combined_value": float,
        }
    """
    combined_value = con_value + agg_value

    # Combined floor check
    if combined_value <= COMBINED_PORTFOLIO_FLOOR:
        reason = (
            f"Combined portfolio ${combined_value:,.2f} below floor "
            f"${COMBINED_PORTFOLIO_FLOOR:,.2f} — halting both strategies"
        )
        logger.critical(f"🔴🔴 COMBINED KILL SWITCH — {reason}")
        return {"halt": True, "reason": reason, "combined_value": combined_value}

    # Combined daily stop check
    if combined_today_open and combined_today_open > 0:
        daily_loss_pct = (combined_today_open - combined_value) / combined_today_open
        if daily_loss_pct >= COMBINED_DAILY_STOP_PCT:
            reason = (
                f"Combined daily loss {daily_loss_pct:.1%} exceeds "
                f"{COMBINED_DAILY_STOP_PCT:.1%} threshold — halting both strategies today"
            )
            logger.warning(f"🟡🟡 COMBINED DAILY STOP — {reason}")
            return {"halt": True, "reason": reason, "combined_value": combined_value}

    logger.info(
        f"💰 Combined portfolio: ${combined_value:,.2f} "
        f"(Con: ${con_value:,.2f} | Agg: ${agg_value:,.2f})"
    )
    return {"halt": False, "reason": "OK", "combined_value": combined_value}


# ============================================================
# SECTOR EXPOSURE CHECK (Phase 7 — NEW)
# ============================================================

def check_sector_exposure(
    new_symbol: str,
    open_positions: List[str],
    portfolio_value: float,
    position_value: float,
) -> bool:
    """
    Returns True if adding new_symbol would exceed sector cap (30%).
    Prevents being overly concentrated in one sector.

    Args:
        new_symbol:      Symbol we want to add
        open_positions:  Currently held symbols
        portfolio_value: Total portfolio value
        position_value:  Dollar value of the new position we want to add

    Returns:
        True  → would exceed sector cap, do NOT add
        False → safe to add
    """
    new_upper = new_symbol.upper().replace("/", "")

    # Find which sector new_symbol belongs to
    new_sector = None
    for sector, symbols in SECTOR_MAP.items():
        if any(new_upper == s.upper().replace("/", "") for s in symbols):
            new_sector = sector
            break

    if not new_sector:
        return False  # Unknown sector — allow it

    # Count current sector exposure (approximate — assume equal weighting)
    sector_symbols = [s.upper().replace("/", "") for s in SECTOR_MAP[new_sector]]
    positions_in_sector = sum(
        1 for p in open_positions
        if p.upper().replace("/", "") in sector_symbols
    )

    # Rough estimate: each position ≈ portfolio_value / max_positions
    estimated_sector_value = positions_in_sector * (portfolio_value / 5)
    new_sector_value = estimated_sector_value + position_value
    sector_pct = new_sector_value / portfolio_value if portfolio_value > 0 else 0

    if sector_pct > SECTOR_CAP_PCT:
        logger.warning(
            f"⚠️  Sector cap: {new_symbol} would bring {new_sector} "
            f"to ~{sector_pct:.1%} (cap: {SECTOR_CAP_PCT:.1%})"
        )
        return True  # Block it

    return False


# ============================================================
# SHORT POSITION RISK CHECKS (Phase 7 — NEW)
# ============================================================

def check_short_stops(alpaca, config: dict) -> List[str]:
    """
    Checks all open short positions for stop conditions.
    Covers (closes) any short that has hit its stop.

    Two triggers:
    1. Hard stop: short up >8% against us (ETF rose 8%)
    2. Squeeze alert: ETF rose >5% intraday

    Args:
        alpaca: AlpacaClient instance
        config: Strategy config dict (AGGRESSIVE)

    Returns:
        List of symbols that were covered (closed)
    """
    covered = []
    short_positions = alpaca.get_short_positions()

    if not short_positions:
        return covered

    short_stop_pct    = config.get("short_stop_pct", 0.08)
    squeeze_alert_pct = config.get("short_squeeze_pct", 0.05)

    for position in short_positions:
        symbol = position.symbol
        try:
            # unrealized_plpc is negative when short is profitable (price fell)
            # It's positive when short is losing (price rose)
            unrealized_plpc = float(position.unrealized_plpc)

            # Hard stop: position up X% against us
            if unrealized_plpc >= short_stop_pct:
                logger.warning(
                    f"[Short Stop] 🛑 {symbol} hit hard stop: "
                    f"+{unrealized_plpc:.1%} against us (limit: {short_stop_pct:.1%})"
                )
                qty   = abs(float(position.qty))
                order = alpaca.cover_short(symbol, qty)
                if order:
                    covered.append(symbol)
                continue

            # Squeeze alert: intraday move check
            current_price = alpaca.get_stock_price(symbol)
            avg_entry     = float(position.avg_entry_price)
            if current_price and avg_entry > 0:
                intraday_move = (current_price - avg_entry) / avg_entry
                if intraday_move >= squeeze_alert_pct:
                    logger.warning(
                        f"[Squeeze Alert] ⚠️  {symbol} up {intraday_move:.1%} intraday — "
                        f"covering to prevent squeeze"
                    )
                    qty   = abs(float(position.qty))
                    order = alpaca.cover_short(symbol, qty)
                    if order:
                        covered.append(symbol)

        except Exception as e:
            logger.error(f"❌ Short stop check failed for {symbol}: {e}")

    return covered


# ============================================================
# CORRELATION CHECK (unchanged)
# ============================================================

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

def check_correlation(new_symbol: str, open_positions: List[str],
                      max_per_group: int = 1) -> bool:
    new_clean = new_symbol.replace("/", "").upper()
    for group_name, group_symbols in CORRELATION_GROUPS.items():
        group_upper = [s.upper() for s in group_symbols]
        if new_clean not in group_upper:
            continue
        existing = sum(
            1 for pos in open_positions
            if pos.replace("/", "").upper() in group_upper
        )
        if existing >= max_per_group:
            logger.info(
                f"⚠️  Correlation block: {new_symbol} in group "
                f"'{group_name}' already has {existing} position(s)"
            )
            return True
    return False


# ============================================================
# FULL PRE-CYCLE RISK CHECK (updated)
# ============================================================

def run_risk_checks(
    strategy_name: str,
    portfolio_value: float,
    today_open_value: float,
    config: dict,
    is_killed: bool,
    is_stopped_today: bool,
) -> dict:
    if is_killed:
        return {
            "can_trade": False, "kill_switch": True, "daily_stop": False,
            "reason": "Bot permanently halted", "stock_allowed": False, "crypto_allowed": False,
        }

    if is_stopped_today:
        return {
            "can_trade": False, "kill_switch": False, "daily_stop": True,
            "reason": "Daily stop active", "stock_allowed": False, "crypto_allowed": False,
        }

    if check_kill_switch(strategy_name, portfolio_value, config["portfolio_floor"]):
        return {
            "can_trade": False, "kill_switch": True, "daily_stop": False,
            "reason": f"Portfolio ${portfolio_value:,.2f} below floor",
            "stock_allowed": False, "crypto_allowed": False,
        }

    if check_daily_stop(strategy_name, portfolio_value, today_open_value, config["daily_stop_pct"]):
        return {
            "can_trade": False, "kill_switch": False, "daily_stop": True,
            "reason": "Daily loss threshold exceeded",
            "stock_allowed": False, "crypto_allowed": False,
        }

    stock_ok  = can_trade_stock()
    crypto_ok = can_trade_crypto()

    if not stock_ok and not crypto_ok:
        return {
            "can_trade": False, "kill_switch": False, "daily_stop": False,
            "reason": "Near market close — no new trades",
            "stock_allowed": False, "crypto_allowed": False,
        }

    now = datetime.now(ET).strftime("%H:%M ET")
    logger.info(
        f"[{strategy_name}] ✅ Risk checks passed at {now} — "
        f"Stocks: {'✓' if stock_ok else '✗'} | "
        f"Crypto: {'✓' if crypto_ok else '✗'} | "
        f"Portfolio: ${portfolio_value:,.2f}"
    )

    return {
        "can_trade": True, "kill_switch": False, "daily_stop": False,
        "reason": "All checks passed",
        "stock_allowed": stock_ok, "crypto_allowed": crypto_ok,
    }
