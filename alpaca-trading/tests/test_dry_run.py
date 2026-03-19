"""
tests/test_dry_run.py
=====================
Level 3 — Runs one full cycle of both strategies.
Fetches real data, computes indicators, calls Claude,
parses decisions — but NEVER places real orders.

This is the final gate before deploying to Render.

Usage:
    cd alpaca-trading
    python3 tests/test_dry_run.py
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
    ALPACA_API_KEY_AGGRESSIVE,
    ALPACA_SECRET_KEY_AGGRESSIVE,
    CONSERVATIVE,
    AGGRESSIVE,
    ANTHROPIC_API_KEY,
)
from shared.alpaca_client import AlpacaClient
from shared.indicators import compute_all, get_latest_signals
from shared.regime_filter import regime_summary, is_regime_match
from shared.news import get_news_sentiment
from shared.earnings import check_earnings_veto
from shared.fear_greed import get_fear_greed
from shared.congressional import get_congressional_signal
from shared.scoring import calculate_score
from conservative.strategy import build_decision_prompt as con_prompt, get_claude_decision as con_claude
from aggressive.strategy import build_decision_prompt as agg_prompt, get_claude_decision as agg_claude

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭️  SKIP"
results = []

# Test with a small set of symbols to keep it fast
TEST_STOCKS = ["AAPL", "NVDA"]
TEST_CRYPTO = ["BTC/USD"]


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
print("  LEVEL 3 — DRY RUN (no orders placed)")
print("=" * 55)
print("  Testing full cycle: data → indicators → Claude → decision")
print("  ⚠️  This will make real Claude API calls (~$0.02 total)\n")

# ============================================================
# SETUP CLIENTS
# ============================================================
section("Setup")
try:
    con_client = AlpacaClient(ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE)
    agg_client = AlpacaClient(ALPACA_API_KEY_AGGRESSIVE,   ALPACA_SECRET_KEY_AGGRESSIVE)
    check("Both Alpaca clients ready", True)

    con_value = con_client.get_portfolio_value()
    agg_value = agg_client.get_portfolio_value()
    check("Portfolio values fetched", True, f"Con: ${con_value:,.2f} | Agg: ${agg_value:,.2f}")

    con_positions = con_client.get_position_symbols()
    agg_positions = agg_client.get_position_symbols()
    con_cash      = con_client.get_cash()
    agg_cash      = agg_client.get_cash()
    check("Positions and cash fetched", True,
          f"Con positions: {len(con_positions)} | Agg positions: {len(agg_positions)}")

except Exception as e:
    check("Setup failed", False, str(e))
    print("\n❌ Cannot proceed without client setup. Check your API keys.")
    sys.exit(1)

# ============================================================
# DATA PIPELINE TEST
# ============================================================
section("Data Pipeline (fetch → indicators → signals)")

good_symbols = []
for symbol in TEST_STOCKS + TEST_CRYPTO:
    try:
        df = con_client.get_bars(symbol, lookback_days=30)
        if df.empty:
            check(f"{symbol} bars", False, "Empty DataFrame")
            continue

        df_ind = compute_all(df)
        if df_ind.empty:
            check(f"{symbol} indicators", False, "Compute failed")
            continue

        signals = get_latest_signals(df_ind)
        if not signals:
            check(f"{symbol} signals", False, "No signals")
            continue

        regime = regime_summary(df_ind)
        check(
            f"{symbol} full pipeline",
            True,
            f"Price: ${signals['price']:,.2f} | RSI: {signals['rsi']} | "
            f"Regime: {regime['regime']} | MACD: {signals['macd']}"
        )
        good_symbols.append((symbol, signals, regime, df_ind))

    except Exception as e:
        check(f"{symbol} pipeline", False, str(e))

if not good_symbols:
    print("\n❌ No symbols passed data pipeline. Cannot test Claude.")
    sys.exit(1)

# ============================================================
# CONSERVATIVE STRATEGY — CLAUDE DECISION TEST
# ============================================================
section("Conservative Strategy — Claude Decisions (DRY RUN)")
print("  → Calling Claude with real market data. No orders will be placed.\n")

con_decisions = []
for symbol, signals, regime, df_ind in good_symbols[:2]:  # Test first 2 symbols
    try:
        # Check regime match
        if not is_regime_match(regime["regime"], "conservative"):
            print(f"  ⏭️   {symbol} — regime {regime['regime']} doesn't match conservative, skipping")
            continue

        news          = get_news_sentiment(symbol)
        earnings      = check_earnings_veto(symbol)
        fear_greed    = get_fear_greed()
        congressional = get_congressional_signal(symbol)
        score         = calculate_score(
            signals=signals,
            regime=regime,
            news=news,
            fear_greed=fear_greed,
            congressional=congressional,
        )

        prompt = con_prompt(
            symbol=symbol,
            signals=signals,
            regime=regime,
            score=score,
            earnings=earnings,
            portfolio_value=con_value,
            today_open_value=con_value,
            open_positions=con_positions,
            cash=con_cash,
        )

        decision = con_claude(prompt)

        valid_actions = ["BUY", "SELL", "HOLD", "STOP_ALL", "STOP_TODAY"]
        is_valid = (
            decision is not None and
            isinstance(decision, dict) and
            decision.get("action") in valid_actions
        )

        check(
            f"{symbol} — Claude decision",
            is_valid,
            f"Action: {decision.get('action', 'N/A')} | "
            f"Confidence: {decision.get('confidence', 'N/A')} | "
            f"{decision.get('reason', 'N/A')[:60]}..."
            if is_valid else f"Got: {decision}"
        )

        if is_valid:
            con_decisions.append(decision)

    except Exception as e:
        check(f"{symbol} Claude call", False, str(e))

if not con_decisions:
    print("  ℹ️  All symbols were HOLD or regime mismatch — this is normal in choppy markets")

# ============================================================
# AGGRESSIVE STRATEGY — CLAUDE DECISION TEST
# ============================================================
section("Aggressive Strategy — Claude Decisions (DRY RUN)")
print("  → Calling Claude with real market data. No orders will be placed.\n")

agg_decisions = []
for symbol, signals, regime, df_ind in good_symbols[:2]:
    try:
        news          = get_news_sentiment(symbol)
        earnings      = check_earnings_veto(symbol)
        fear_greed    = get_fear_greed()
        congressional = get_congressional_signal(symbol)
        score         = calculate_score(
            signals=signals,
            regime=regime,
            news=news,
            fear_greed=fear_greed,
            congressional=congressional,
        )

        prompt = agg_prompt(
            symbol=symbol,
            signals=signals,
            regime=regime,
            score=score,
            earnings=earnings,
            portfolio_value=agg_value,
            today_open_value=agg_value,
            open_positions=agg_positions,
            cash=agg_cash,
        )

        decision = agg_claude(prompt)

        valid_actions = ["BUY", "SELL", "HOLD", "STOP_ALL", "STOP_TODAY"]
        is_valid = (
            decision is not None and
            isinstance(decision, dict) and
            decision.get("action") in valid_actions
        )

        check(
            f"{symbol} — Claude decision",
            is_valid,
            f"Action: {decision.get('action', 'N/A')} | "
            f"Confidence: {decision.get('confidence', 'N/A')} | "
            f"{decision.get('reason', 'N/A')[:60]}..."
            if is_valid else f"Got: {decision}"
        )

        if is_valid:
            agg_decisions.append(decision)

    except Exception as e:
        check(f"{symbol} Claude call", False, str(e))

# ============================================================
# JSON PARSING VALIDATION
# ============================================================
section("JSON Response Validation")

all_decisions = con_decisions + agg_decisions
required_fields = ["action", "ticker", "entry_price", "stop_loss", "take_profit",
                   "position_size_pct", "confidence", "reason"]

for i, d in enumerate(all_decisions):
    missing = [f for f in required_fields if f not in d]
    check(
        f"Decision {i+1} has all required fields",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "All fields present ✓"
    )

    if "position_size_pct" in d:
        pct = d["position_size_pct"]
        check(
            f"Decision {i+1} position size within limits",
            0 <= pct <= 0.20,
            f"{pct:.1%}"
        )

# ============================================================
# RISK GUARDIAN VALIDATION
# ============================================================
section("Risk Guardian — Kill Switch Logic")
from shared.risk_guardian import check_kill_switch, check_daily_stop

check(
    "Kill switch does NOT trigger at $900",
    not check_kill_switch("Test", 900, CONSERVATIVE["portfolio_floor"]),
    "Portfolio $900 > floor $700 ✓"
)
check(
    "Kill switch DOES trigger at $650",
    check_kill_switch("Test", 650, CONSERVATIVE["portfolio_floor"]),
    "Portfolio $650 < floor $700 ✓"
)
check(
    "Daily stop does NOT trigger at 5% loss",
    not check_daily_stop("Test", 950, 1000, CONSERVATIVE["daily_stop_pct"]),
    "5% loss < 15% threshold ✓"
)
check(
    "Daily stop DOES trigger at 16% loss",
    check_daily_stop("Test", 840, 1000, CONSERVATIVE["daily_stop_pct"]),
    "16% loss > 15% threshold ✓"
)

# ============================================================
# SUMMARY
# ============================================================
passed = sum(results)
total  = len(results)

print("\n" + "=" * 55)
if passed == total:
    print(f"  ✅ ALL {total} CHECKS PASSED")
    print(f"  🚀 System is ready to deploy to Render")
    print(f"\n  Next steps:")
    print(f"  1. git add . && git commit -m 'Add test suite'")
    print(f"  2. git push origin main")
    print(f"  3. Deploy on Render with start command: python3 main.py")
else:
    failed = total - passed
    print(f"  ❌ {passed}/{total} PASSED — {failed} check(s) failed")
    print(f"  → Fix failures above before deploying")
print("=" * 55 + "\n")

sys.exit(0 if passed == total else 1)
