"""
tests/test_config.py
====================
Level 1 — Validates all API keys are present and readable.
Run this first before anything else.

Usage:
    cd alpaca-trading
    python3 tests/test_config.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
    ALPACA_API_KEY_AGGRESSIVE,
    ALPACA_SECRET_KEY_AGGRESSIVE,
    ALPACA_BASE_URL,
    ANTHROPIC_API_KEY,
    ALERT_EMAIL_FROM,
    ALERT_EMAIL_PASSWORD,
    ALERT_EMAIL_TO,
    CONSERVATIVE,
    AGGRESSIVE,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def check(name: str, condition: bool, hint: str = ""):
    status = PASS if condition else FAIL
    msg = f"{status}  {name}"
    if not condition and hint:
        msg += f"\n        → {hint}"
    print(msg)
    results.append(condition)


print("\n" + "=" * 55)
print("  LEVEL 1 — CONFIG VALIDATION")
print("=" * 55 + "\n")

# --- Alpaca Conservative ---
print("Alpaca — Conservative Account:")
check(
    "API key present",
    bool(ALPACA_API_KEY_CONSERVATIVE) and "your_" not in str(ALPACA_API_KEY_CONSERVATIVE),
    "Set ALPACA_API_KEY_CONSERVATIVE in .env"
)
check(
    "Secret key present",
    bool(ALPACA_SECRET_KEY_CONSERVATIVE) and "your_" not in str(ALPACA_SECRET_KEY_CONSERVATIVE),
    "Set ALPACA_SECRET_KEY_CONSERVATIVE in .env"
)

print("\nAlpaca — Aggressive Account:")
check(
    "API key present",
    bool(ALPACA_API_KEY_AGGRESSIVE) and "your_" not in str(ALPACA_API_KEY_AGGRESSIVE),
    "Set ALPACA_API_KEY_AGGRESSIVE in .env"
)
check(
    "Secret key present",
    bool(ALPACA_SECRET_KEY_AGGRESSIVE) and "your_" not in str(ALPACA_SECRET_KEY_AGGRESSIVE),
    "Set ALPACA_SECRET_KEY_AGGRESSIVE in .env"
)

print("\nAlpaca — Base URL:")
check(
    "Base URL is paper trading",
    ALPACA_BASE_URL == "https://paper-api.alpaca.markets",
    f"Expected paper URL, got: {ALPACA_BASE_URL}"
)

print("\nAnthropic:")
check(
    "API key present",
    bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY.startswith("sk-ant-"),
    "Set ANTHROPIC_API_KEY in .env — should start with sk-ant-"
)

print("\nEmail Alerts:")
check(
    "From address present",
    bool(ALERT_EMAIL_FROM) and "@" in str(ALERT_EMAIL_FROM),
    "Set ALERT_EMAIL_FROM in .env"
)
check(
    "App password present",
    bool(ALERT_EMAIL_PASSWORD) and "your_" not in str(ALERT_EMAIL_PASSWORD),
    "Set ALERT_EMAIL_PASSWORD in .env"
)
check(
    "To address present",
    bool(ALERT_EMAIL_TO) and "@" in str(ALERT_EMAIL_TO),
    "Set ALERT_EMAIL_TO in .env"
)

print("\nStrategy Config:")
check(
    "Conservative starting capital = $1,000",
    CONSERVATIVE["starting_capital"] == 1000.0,
    f"Got: {CONSERVATIVE['starting_capital']}"
)
check(
    "Aggressive starting capital = $1,000",
    AGGRESSIVE["starting_capital"] == 1000.0,
    f"Got: {AGGRESSIVE['starting_capital']}"
)
check(
    "Conservative kill switch = $700",
    CONSERVATIVE["portfolio_floor"] == 700,
    f"Got: {CONSERVATIVE['portfolio_floor']}"
)
check(
    "Aggressive kill switch = $600",
    AGGRESSIVE["portfolio_floor"] == 600,
    f"Got: {AGGRESSIVE['portfolio_floor']}"
)
check(
    "Conservative max position = 5%",
    CONSERVATIVE["max_position_pct"] == 0.05,
    f"Got: {CONSERVATIVE['max_position_pct']}"
)
check(
    "Aggressive max position = 15%",
    AGGRESSIVE["max_position_pct"] == 0.15,
    f"Got: {AGGRESSIVE['max_position_pct']}"
)

# --- Summary ---
passed = sum(results)
total  = len(results)
print("\n" + "=" * 55)
if passed == total:
    print(f"  ✅ ALL {total} CHECKS PASSED — ready for Level 2")
else:
    print(f"  ❌ {passed}/{total} PASSED — fix failures before proceeding")
print("=" * 55 + "\n")

sys.exit(0 if passed == total else 1)
