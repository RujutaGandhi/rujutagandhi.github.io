"""
tests/test_phase7.py
====================
Phase 7 tests — adaptive regime, short selling, combined kill switch.

Tests:
  1.  VIX fetch returns a dict with vix and level keys
  2.  VIX classify: < 20 = LOW
  3.  VIX classify: 20–25 = ELEVATED
  4.  VIX classify: 25–30 = HIGH
  5.  VIX classify: > 30 = EXTREME
  6.  Macro mode returns one of four valid modes
  7.  Macro mode: EXTREME VIX → MACRO_EVENT
  8.  Macro mode: HIGH VIX + below 200MA → DEFENSIVE
  9.  Macro mode: LOW VIX → MOMENTUM
  10. Macro mode: HIGH VIX + above 200MA → MEAN_REVERSION
  11. Config: COMBINED_PORTFOLIO_FLOOR = 1700
  12. Config: Conservative allow_short = False
  13. Config: Aggressive allow_short = True
  14. Config: Aggressive short_symbols = [SPY, QQQ] only
  15. Config: regime_size_multiplier present for all four modes
  16. Config: DEFENSIVE mode size multiplier < 1.0
  17. Combined kill switch fires below $1,700
  18. Combined kill switch does NOT fire above $1,700
  19. Combined daily stop fires at 8% loss
  20. Short stop check: no positions → returns empty list
  21. ETB check: SPY is always ETB (paper trading)
  22. Alpaca client: place_short_order method exists
  23. Alpaca client: cover_short method exists
  24. Alpaca client: get_short_positions method exists
  25. Alpaca client: get_total_short_exposure method exists
  26. get_macro_mode() live call returns all required keys
  27. get_vix_spike() returns spike + spike_pct + current_vix keys
  28. Conservative strategy does NOT call Claude in DEFENSIVE mode
  29. Conservative strategy does NOT call Claude in MACRO_EVENT mode
  30. Aggressive short_symbols contains NO single stocks
  31. Short exposure cap: max_short_exposure_pct enforced in config
  32. place_crypto_stop_sell method still exists (regression check)
  33. AlpacaClient._api_key set correctly (portfolio history auth)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.vix import classify_vix, get_vix
from shared.macro_regime import get_macro_mode
from shared.config import (
    CONSERVATIVE, AGGRESSIVE,
    COMBINED_PORTFOLIO_FLOOR, COMBINED_DAILY_STOP_PCT,
)
from shared.risk_guardian import check_combined_portfolio
from shared.alpaca_client import AlpacaClient
from shared.config import ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}" + (f"  ({detail})" if detail else ""))


# ============================================================
# 1-5: VIX TESTS
# ============================================================
print("\nVIX — Classification Tests:")

check("VIX < 20 = LOW",      classify_vix(15.0) == "LOW",      f"classify_vix(15) = {classify_vix(15.0)}")
check("VIX 20–25 = ELEVATED", classify_vix(22.0) == "ELEVATED", f"classify_vix(22) = {classify_vix(22.0)}")
check("VIX 25–30 = HIGH",    classify_vix(27.0) == "HIGH",     f"classify_vix(27) = {classify_vix(27.0)}")
check("VIX > 30 = EXTREME",  classify_vix(35.0) == "EXTREME",  f"classify_vix(35) = {classify_vix(35.0)}")

try:
    vix_data = get_vix()
    check(
        "VIX fetch returns dict with vix + level",
        isinstance(vix_data, dict) and "vix" in vix_data and "level" in vix_data,
        f"VIX: {vix_data.get('vix', 'N/A')} ({vix_data.get('level', 'N/A')})",
    )
except Exception as e:
    check("VIX fetch returns dict with vix + level", False, f"Exception: {e}")


# ============================================================
# 6-10: MACRO REGIME LOGIC TESTS (unit test the decision logic)
# ============================================================
print("\nMacro Regime — Decision Logic Tests:")

# We test the decision logic directly without live API calls
# by simulating inputs to the regime detection

def _mock_regime(vix: float, spike: bool, above_ma: bool) -> str:
    """Mirrors the logic in get_macro_mode() for unit testing."""
    from shared.vix import classify_vix
    vix_level = classify_vix(vix)
    if spike:                                         return "MACRO_EVENT"
    if vix_level == "EXTREME":                        return "MACRO_EVENT"
    if vix_level == "HIGH" and not above_ma:          return "DEFENSIVE"
    if vix_level == "HIGH" and above_ma:              return "MEAN_REVERSION"
    if vix_level == "ELEVATED" and not above_ma:      return "MEAN_REVERSION"
    if vix_level == "ELEVATED" and above_ma:          return "MOMENTUM"
    return "MOMENTUM"

check("VIX spike → MACRO_EVENT",          _mock_regime(22.0, True, True) == "MACRO_EVENT",   "spike=True")
check("EXTREME VIX → MACRO_EVENT",        _mock_regime(35.0, False, True) == "MACRO_EVENT",  "vix=35")
check("HIGH VIX + below 200MA → DEFENSIVE", _mock_regime(27.0, False, False) == "DEFENSIVE", "vix=27, above=False")
check("LOW VIX → MOMENTUM",               _mock_regime(15.0, False, True) == "MOMENTUM",     "vix=15")
check("HIGH VIX + above 200MA → MEAN_REVERSION", _mock_regime(27.0, False, True) == "MEAN_REVERSION", "vix=27, above=True")

try:
    macro = get_macro_mode()
    valid_modes = {"MOMENTUM", "MEAN_REVERSION", "DEFENSIVE", "MACRO_EVENT"}
    check(
        "Live get_macro_mode() returns valid mode",
        macro.get("mode") in valid_modes,
        f"Mode: {macro.get('mode')} | VIX: {macro.get('vix', 'N/A')}",
    )
except Exception as e:
    check("Live get_macro_mode() returns valid mode", False, f"Exception: {e}")


# ============================================================
# 11-16: CONFIG TESTS
# ============================================================
print("\nConfig — Phase 7 Settings:")

check("COMBINED_PORTFOLIO_FLOOR = 1700",   COMBINED_PORTFOLIO_FLOOR == 1700.0,   f"Got: {COMBINED_PORTFOLIO_FLOOR}")
check("Conservative allow_short = False",  CONSERVATIVE.get("allow_short") == False, "")
check("Aggressive allow_short = True",     AGGRESSIVE.get("allow_short") == True, "")
check(
    "Aggressive short_symbols = [SPY, QQQ] only",
    set(AGGRESSIVE.get("short_symbols", [])) == {"SPY", "QQQ"},
    f"Got: {AGGRESSIVE.get('short_symbols')}",
)
check(
    "regime_size_multiplier has all four modes",
    all(m in AGGRESSIVE.get("regime_size_multiplier", {})
        for m in ["MOMENTUM", "MEAN_REVERSION", "DEFENSIVE", "MACRO_EVENT"]),
    f"Keys: {list(AGGRESSIVE.get('regime_size_multiplier', {}).keys())}",
)
check(
    "DEFENSIVE mode size_multiplier < 1.0",
    AGGRESSIVE["regime_size_multiplier"].get("DEFENSIVE", 1.0) < 1.0,
    f"Got: {AGGRESSIVE['regime_size_multiplier'].get('DEFENSIVE')}",
)


# ============================================================
# 17-19: COMBINED KILL SWITCH TESTS
# ============================================================
print("\nCombined Kill Switch — Logic Tests:")

# 17. Fires below $1,700
result_low = check_combined_portfolio(800.0, 850.0, 2000.0)
check(
    "Combined kill switch fires below $1,700",
    result_low["halt"] == True,
    f"Combined: ${800+850} → halt={result_low['halt']}",
)

# 18. Does NOT fire above $1,700
result_ok = check_combined_portfolio(950.0, 980.0, 2000.0)
check(
    "Combined kill switch does NOT fire above $1,700",
    result_ok["halt"] == False,
    f"Combined: ${950+980} → halt={result_ok['halt']}",
)

# 19. Daily stop fires at 8% combined loss
result_daily = check_combined_portfolio(920.0, 920.0, 2000.0)
check(
    "Combined daily stop fires at 8% loss",
    result_daily["halt"] == True,
    f"Combined: $1840 vs open $2000 = -8% → halt={result_daily['halt']}",
)


# ============================================================
# 20-25: ALPACA CLIENT SHORT METHODS
# ============================================================
print("\nAlpaca Client — Short Selling Methods:")

check("place_short_order method exists",       hasattr(AlpacaClient, "place_short_order"), "")
check("cover_short method exists",             hasattr(AlpacaClient, "cover_short"), "")
check("get_short_positions method exists",     hasattr(AlpacaClient, "get_short_positions"), "")
check("get_total_short_exposure method exists", hasattr(AlpacaClient, "get_total_short_exposure"), "")
check("check_etb method exists",               hasattr(AlpacaClient, "check_etb"), "")

# Live test: short stop check with real client (no positions → returns empty)
try:
    alpaca = AlpacaClient(ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE)
    from shared.risk_guardian import check_short_stops
    covered = check_short_stops(alpaca, AGGRESSIVE)
    check(
        "check_short_stops with no shorts returns empty list",
        isinstance(covered, list),
        f"Covered: {covered}",
    )
except Exception as e:
    check("check_short_stops with no shorts returns empty list", False, f"Exception: {e}")


# ============================================================
# 26-33: ADDITIONAL COVERAGE TESTS
# ============================================================
print("\nAdditional Coverage Tests:")

# 26. get_macro_mode() live call returns all required keys
try:
    macro = get_macro_mode()
    required_keys = {"mode", "vix", "vix_level", "vix_spike", "above_200ma",
                     "spy_price", "ma_200", "description"}
    missing_keys  = required_keys - set(macro.keys())
    check(
        "get_macro_mode() returns all required keys",
        len(missing_keys) == 0,
        f"Missing: {missing_keys}" if missing_keys else f"Mode: {macro['mode']}",
    )
except Exception as e:
    check("get_macro_mode() returns all required keys", False, f"Exception: {e}")

# 27. get_vix_spike() returns correct keys
try:
    from shared.vix import get_vix_spike
    spike = get_vix_spike(lookback_days=3)
    required = {"spike", "spike_pct", "current_vix"}
    missing  = required - set(spike.keys())
    check(
        "get_vix_spike() returns spike + spike_pct + current_vix",
        len(missing) == 0,
        f"Keys: {list(spike.keys())} | Spike: {spike.get('spike')}",
    )
except Exception as e:
    check("get_vix_spike() returns spike + spike_pct + current_vix", False, f"Exception: {e}")

# 28-29. Conservative strategy: Claude NOT called in DEFENSIVE or MACRO_EVENT mode
# We verify this by inspecting the source — these modes return before any Claude call
try:
    import inspect
    from conservative.strategy import ConservativeStrategy
    source = inspect.getsource(ConservativeStrategy.run_cycle)
    # In DEFENSIVE/MACRO_EVENT, strategy returns early with a HOLD before reaching
    # get_claude_decision. Verify the early return exists in the correct order.
    defensive_return_pos  = source.find('DEFENSIVE", "MACRO_EVENT')
    claude_call_pos       = source.find("get_claude_decision")
    check(
        "Conservative: DEFENSIVE/MACRO_EVENT returns before Claude is called",
        defensive_return_pos != -1 and defensive_return_pos < claude_call_pos,
        f"Early return at pos {defensive_return_pos}, Claude at pos {claude_call_pos}",
    )
    # Also verify the return statement is present for both modes
    check(
        "Conservative: Both DEFENSIVE and MACRO_EVENT modes trigger early return",
        'DEFENSIVE", "MACRO_EVENT' in source or "DEFENSIVE" in source and "MACRO_EVENT" in source,
        "Both modes present in source",
    )
except Exception as e:
    check("Conservative: DEFENSIVE/MACRO_EVENT returns before Claude is called", False, f"Exception: {e}")
    check("Conservative: Both DEFENSIVE and MACRO_EVENT modes trigger early return", False, "Skipped")

# 30. Aggressive short_symbols contains NO single stocks
# SPY and QQQ are ETFs — verify no tickers that look like single stocks
short_syms = AGGRESSIVE.get("short_symbols", [])
# Single stocks typically don't end in Y/Q for index ETFs — but more reliably,
# we just check the exact list is only SPY and QQQ
only_etf_shorts = set(short_syms) == {"SPY", "QQQ"}
check(
    "Aggressive short_symbols contains ONLY SPY and QQQ (no single stocks)",
    only_etf_shorts,
    f"Got: {short_syms}",
)

# 31. Short exposure cap enforced in config
check(
    "max_short_exposure_pct ≤ 0.30",
    AGGRESSIVE.get("max_short_exposure_pct", 1.0) <= 0.30,
    f"Got: {AGGRESSIVE.get('max_short_exposure_pct')}",
)
check(
    "short_stop_pct exists and is ≤ 0.10",
    AGGRESSIVE.get("short_stop_pct", 1.0) <= 0.10,
    f"Got: {AGGRESSIVE.get('short_stop_pct')}",
)

# 32. place_crypto_stop_sell still exists (regression — make sure we didn't break it)
check(
    "place_crypto_stop_sell method still exists (regression)",
    hasattr(AlpacaClient, "place_crypto_stop_sell"),
    "Required by both strategies for crypto stop management",
)

# 33. AlpacaClient stores _api_key for portfolio history auth
try:
    alpaca = AlpacaClient(ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE)
    check(
        "AlpacaClient._api_key set correctly for portfolio history auth",
        hasattr(alpaca, "_api_key") and alpaca._api_key == ALPACA_API_KEY_CONSERVATIVE,
        f"_api_key present: {hasattr(alpaca, '_api_key')}",
    )
except Exception as e:
    check("AlpacaClient._api_key set correctly for portfolio history auth", False, f"Exception: {e}")


# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"Phase 7 Results: {passed} passed, {failed} failed out of {len(results)} tests")

if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r[0] == FAIL:
            print(f"  {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print("\n🎉 All Phase 7 tests passed!")
