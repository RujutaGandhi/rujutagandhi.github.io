"""
tests/test_connection.py
========================
Level 2 — Validates Alpaca API connections, price fetching,
and indicator computation.

Run this after test_config.py passes.

Usage:
    cd alpaca-trading
    python3 tests/test_connection.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
    ALPACA_API_KEY_AGGRESSIVE,
    ALPACA_SECRET_KEY_AGGRESSIVE,
)
from shared.alpaca_client import AlpacaClient
from shared.indicators import compute_all, get_latest_signals
from shared.regime_filter import detect_regime, regime_summary

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    msg = f"{status}  {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    results.append(condition)
    return condition


def section(title: str):
    print(f"\n{title}:")


print("\n" + "=" * 55)
print("  LEVEL 2 — CONNECTION & DATA TEST")
print("=" * 55)

# ============================================================
# CONSERVATIVE ACCOUNT
# ============================================================
section("Conservative Account — Alpaca Connection")
try:
    con_client = AlpacaClient(
        ALPACA_API_KEY_CONSERVATIVE,
        ALPACA_SECRET_KEY_CONSERVATIVE
    )
    check("Client initialized", True)

    value = con_client.get_portfolio_value()
    check(
        "Portfolio value returned",
        isinstance(value, float) and value > 0,
        f"${value:,.2f}"
    )

    cash = con_client.get_cash()
    check(
        "Cash returned",
        isinstance(cash, float) and cash >= 0,
        f"${cash:,.2f}"
    )

    positions = con_client.get_position_symbols()
    check(
        "Positions returned",
        isinstance(positions, list),
        f"{len(positions)} open positions"
    )

except Exception as e:
    check("Client initialized", False, str(e))
    check("Portfolio value returned", False)
    check("Cash returned", False)
    check("Positions returned", False)

# ============================================================
# AGGRESSIVE ACCOUNT
# ============================================================
section("Aggressive Account — Alpaca Connection")
try:
    agg_client = AlpacaClient(
        ALPACA_API_KEY_AGGRESSIVE,
        ALPACA_SECRET_KEY_AGGRESSIVE
    )
    check("Client initialized", True)

    value = agg_client.get_portfolio_value()
    check(
        "Portfolio value returned",
        isinstance(value, float) and value > 0,
        f"${value:,.2f}"
    )

except Exception as e:
    check("Client initialized", False, str(e))
    check("Portfolio value returned", False)

# ============================================================
# STOCK PRICE FETCHING
# ============================================================
section("Stock Price Fetching")
try:
    price = con_client.get_stock_price("AAPL")
    check(
        "AAPL live price",
        isinstance(price, float) and price > 0,
        f"${price:,.2f}"
    )

    price = con_client.get_stock_price("NVDA")
    check(
        "NVDA live price",
        isinstance(price, float) and price > 0,
        f"${price:,.2f}"
    )

except Exception as e:
    check("AAPL live price", False, str(e))
    check("NVDA live price", False)

# ============================================================
# CRYPTO PRICE FETCHING
# ============================================================
section("Crypto Price Fetching")
try:
    price = con_client.get_crypto_price("BTC/USD")
    check(
        "BTC/USD live price",
        isinstance(price, float) and price > 0,
        f"${price:,.2f}"
    )

    price = con_client.get_crypto_price("ETH/USD")
    check(
        "ETH/USD live price",
        isinstance(price, float) and price > 0,
        f"${price:,.2f}"
    )

except Exception as e:
    check("BTC/USD live price", False, str(e))
    check("ETH/USD live price", False)

# ============================================================
# HISTORICAL DATA + INDICATORS
# ============================================================
section("Historical Bars + Indicator Computation")
try:
    df = con_client.get_bars("AAPL", lookback_days=30)
    check(
        "AAPL historical bars fetched",
        not df.empty and len(df) > 20,
        f"{len(df)} rows"
    )

    df_ind = compute_all(df)
    check(
        "Indicators computed",
        not df_ind.empty,
        f"{len(df_ind.columns)} columns"
    )

    required_cols = ["rsi", "macd_line", "macd_signal", "ema_fast", "ema_slow", "atr", "volume_ratio"]
    missing = [c for c in required_cols if c not in df_ind.columns]
    check(
        "All indicator columns present",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "RSI, MACD, EMA, ATR, Volume ✓"
    )

    signals = get_latest_signals(df_ind)
    check(
        "Latest signals extracted",
        signals is not None and "rsi" in signals,
        f"RSI: {signals.get('rsi', 'N/A')}, Regime signal: {signals.get('ema_signal', 'N/A')}"
        if signals else "No signals returned"
    )

except Exception as e:
    check("AAPL historical bars fetched", False, str(e))
    check("Indicators computed", False)
    check("All indicator columns present", False)
    check("Latest signals extracted", False)

# ============================================================
# REGIME FILTER
# ============================================================
section("Regime Detection")
try:
    df = con_client.get_bars("AAPL", lookback_days=30)
    df_ind = compute_all(df)

    regime = detect_regime(df_ind)
    check(
        "Regime detected",
        regime in ("TREND", "RANGE", "UNCLEAR"),
        f"AAPL regime: {regime}"
    )

    summary = regime_summary(df_ind)
    check(
        "Regime summary returned",
        isinstance(summary, dict) and "regime" in summary,
        f"ADX: {summary.get('adx', 'N/A')}"
    )

except Exception as e:
    check("Regime detected", False, str(e))
    check("Regime summary returned", False)

# ============================================================
# UNIFIED HELPERS
# ============================================================
section("Unified Helper Methods")
try:
    check(
        "is_crypto('BTC/USD') = True",
        con_client.is_crypto("BTC/USD") is True
    )
    check(
        "is_crypto('AAPL') = False",
        con_client.is_crypto("AAPL") is False
    )

    qty = con_client.calculate_qty("AAPL", 1000, 0.05, 150.0)
    check(
        "Position size calculation",
        qty > 0,
        f"5% of $1000 at $150 = {qty} shares"
    )

    qty_crypto = con_client.calculate_qty("BTC/USD", 1000, 0.02, 95000.0)
    check(
        "Crypto position size calculation",
        qty_crypto > 0,
        f"2% of $1000 at $95000 = {qty_crypto} BTC"
    )

except Exception as e:
    check("Helper methods", False, str(e))

# ============================================================
# SUMMARY
# ============================================================
passed = sum(results)
total  = len(results)
print("\n" + "=" * 55)
if passed == total:
    print(f"  ✅ ALL {total} CHECKS PASSED — ready for Level 3")
else:
    print(f"  ❌ {passed}/{total} PASSED — fix failures before proceeding")
    print("  → Check error messages above for details")
print("=" * 55 + "\n")

sys.exit(0 if passed == total else 1)
