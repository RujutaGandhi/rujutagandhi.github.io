"""
tests/test_phase5.py
====================
Phase 5 tests — self-tuning review loop.

Covers:
- shared/state.py  (load, save, apply, bounds checking)
- shared/review.py (log reader, Claude review, structure)

Usage:
    cd alpaca-trading
    python3 tests/test_phase5.py
"""

import sys
import os
import json
import tempfile
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
print("  PHASE 5 TESTS — Self-Tuning Review Loop")
print("=" * 55)


# ============================================================
# STATE — LOAD DEFAULT
# ============================================================
section("State — Default Loading (shared/state.py)")
try:
    from shared.state import (
        load_state, save_state, apply_adjustments,
        get_settings, DEFAULT_STATE, ADJUSTMENT_BOUNDS
    )

    # Test default state structure
    state = load_state()
    check(
        "State loads without error",
        isinstance(state, dict),
        "Dict returned ✓"
    )
    check(
        "Conservative settings present",
        "conservative" in state,
        "conservative key found ✓"
    )
    check(
        "Aggressive settings present",
        "aggressive" in state,
        "aggressive key found ✓"
    )

    required_fields = [
        "rsi_buy_threshold", "rsi_sell_threshold",
        "volume_multiplier", "atr_stop_multiplier",
        "strategy_mode", "score_threshold", "notes"
    ]
    for field in required_fields:
        check(
            f"Conservative has '{field}'",
            field in state.get("conservative", {}),
            f"Value: {state.get('conservative', {}).get(field)}"
        )

except Exception as e:
    check("state module import", False, str(e))


# ============================================================
# STATE — SAVE AND RELOAD
# ============================================================
section("State — Save and Reload")
try:
    import shared.state as state_module

    # Temporarily redirect state file to a temp file
    original_state_file = state_module.STATE_FILE
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    state_module.STATE_FILE = temp_path

    # Save test state
    test_state = DEFAULT_STATE.copy()
    test_state["conservative"]["rsi_buy_threshold"] = 25
    save_result = save_state(test_state)
    check(
        "State saves successfully",
        save_result is True,
        f"Saved to {temp_path.name}"
    )

    # Reload and verify
    reloaded = load_state()
    check(
        "Saved values persist after reload",
        reloaded.get("conservative", {}).get("rsi_buy_threshold") == 25,
        f"Got: {reloaded.get('conservative', {}).get('rsi_buy_threshold')}"
    )

    # Cleanup
    state_module.STATE_FILE = original_state_file
    temp_path.unlink(missing_ok=True)

except Exception as e:
    check("state save/reload", False, str(e))


# ============================================================
# STATE — ADJUSTMENT BOUNDS
# ============================================================
section("State — Adjustment Bounds Checking")
try:
    state = load_state()

    # Valid adjustment — within bounds
    valid_adj = {
        "rsi_buy_threshold":   28,
        "rsi_sell_threshold":  72,
        "volume_multiplier":   1.3,
        "atr_stop_multiplier": 1.8,
        "strategy_mode":       "TREND",
        "score_threshold":     7,
        "notes":               "Test adjustment",
    }
    updated = apply_adjustments(state, "conservative", valid_adj)
    check(
        "Valid adjustments applied",
        updated["conservative"]["rsi_buy_threshold"] == 28,
        f"RSI threshold: {updated['conservative']['rsi_buy_threshold']}"
    )
    check(
        "Strategy mode updated",
        updated["conservative"]["strategy_mode"] == "TREND",
        "TREND ✓"
    )
    check(
        "Notes updated",
        updated["conservative"]["notes"] == "Test adjustment",
        "Notes saved ✓"
    )

    # Out-of-bounds adjustment — should be rejected
    state2 = load_state()
    bad_adj = {
        "rsi_buy_threshold":   5,    # Below min of 20
        "score_threshold":     99,   # Above max of 9
        "volume_multiplier":   10.0, # Above max of 2.0
    }
    before_rsi = state2["conservative"]["rsi_buy_threshold"]
    updated2 = apply_adjustments(state2, "conservative", bad_adj)
    check(
        "Out-of-bounds RSI rejected",
        updated2["conservative"]["rsi_buy_threshold"] == before_rsi,
        f"Kept original: {before_rsi}"
    )
    check(
        "Out-of-bounds score_threshold rejected",
        updated2["conservative"]["score_threshold"] != 99,
        f"Kept original: {updated2['conservative']['score_threshold']}"
    )

    # Invalid strategy mode
    state3  = load_state()
    bad_mode = {"strategy_mode": "INVALID_MODE"}
    before_mode = state3["conservative"]["strategy_mode"]
    updated3 = apply_adjustments(state3, "conservative", bad_mode)
    check(
        "Invalid strategy_mode rejected",
        updated3["conservative"]["strategy_mode"] == before_mode,
        f"Kept original: {before_mode}"
    )

    # History gets recorded
    check(
        "Adjustment history recorded",
        len(updated.get("history", [])) > 0,
        f"{len(updated.get('history', []))} entries"
    )

except Exception as e:
    check("adjustment bounds", False, str(e))


# ============================================================
# STATE — GET SETTINGS
# ============================================================
section("State — get_settings helper")
try:
    con_settings = get_settings("conservative")
    agg_settings = get_settings("aggressive")

    check(
        "get_settings('conservative') returns dict",
        isinstance(con_settings, dict) and "rsi_buy_threshold" in con_settings,
        f"RSI threshold: {con_settings.get('rsi_buy_threshold')}"
    )
    check(
        "get_settings('aggressive') returns dict",
        isinstance(agg_settings, dict) and "score_threshold" in agg_settings,
        f"Score threshold: {agg_settings.get('score_threshold')}"
    )

except Exception as e:
    check("get_settings", False, str(e))


# ============================================================
# REVIEW — LOG READER
# ============================================================
section("Review — Log Reader (shared/review.py)")
try:
    from shared.review import read_todays_trades, build_review_prompt

    # Test with non-existent log
    result = read_todays_trades(Path("logs/nonexistent.log"))
    check(
        "Non-existent log returns empty list",
        result == [],
        "Graceful fallback ✓"
    )

    # Test with a temp log file containing today's entries
    today = date.today().isoformat()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", delete=False
    ) as f:
        temp_log = Path(f.name)
        # Write today's entries
        f.write(json.dumps({
            "timestamp": f"{today}T10:00:00",
            "strategy": "Conservative",
            "action": "HOLD",
            "symbol": "AAPL",
            "reason": "Below threshold",
            "regime": "TREND",
            "confidence": "MEDIUM"
        }) + "\n")
        f.write(json.dumps({
            "timestamp": f"{today}T11:00:00",
            "strategy": "Conservative",
            "action": "BUY",
            "symbol": "NVDA",
            "reason": "Strong signals",
            "regime": "TREND",
            "confidence": "HIGH"
        }) + "\n")
        # Write yesterday's entry (should be filtered out)
        f.write(json.dumps({
            "timestamp": "2020-01-01T10:00:00",
            "strategy": "Conservative",
            "action": "BUY",
            "symbol": "TSLA",
            "reason": "Old entry",
            "regime": "TREND",
            "confidence": "HIGH"
        }) + "\n")

    trades = read_todays_trades(temp_log)
    check(
        "Log reader returns today's trades only",
        len(trades) == 2,
        f"Got {len(trades)} trades (expected 2, filtered out yesterday)"
    )
    check(
        "Trades have correct structure",
        all("action" in t and "symbol" in t for t in trades),
        "All trades have required fields ✓"
    )

    temp_log.unlink(missing_ok=True)

except Exception as e:
    check("review log reader", False, str(e))


# ============================================================
# REVIEW — PROMPT BUILDER
# ============================================================
section("Review — Prompt Builder")
try:
    mock_con_trades = [
        {"timestamp": f"{date.today().isoformat()}T10:00:00",
         "action": "BUY", "symbol": "AAPL",
         "reason": "Strong signals", "regime": "TREND", "confidence": "HIGH"},
        {"timestamp": f"{date.today().isoformat()}T11:00:00",
         "action": "HOLD", "symbol": "NVDA",
         "reason": "Below threshold", "regime": "TREND", "confidence": "LOW"},
    ]
    mock_agg_trades = [
        {"timestamp": f"{date.today().isoformat()}T10:00:00",
         "action": "BUY", "symbol": "BTC/USD",
         "reason": "Momentum signal", "regime": "TREND", "confidence": "MEDIUM"},
    ]

    con_settings = get_settings("conservative")
    agg_settings = get_settings("aggressive")

    prompt = build_review_prompt(
        con_trades=mock_con_trades,
        agg_trades=mock_agg_trades,
        con_settings=con_settings,
        agg_settings=agg_settings,
        con_value=1050.0,
        agg_value=980.0,
    )

    check(
        "Review prompt is non-empty string",
        isinstance(prompt, str) and len(prompt) > 100,
        f"{len(prompt)} chars"
    )
    check(
        "Prompt includes portfolio values",
        "$1,050.00" in prompt and "$980.00" in prompt,
        "Portfolio values present ✓"
    )
    check(
        "Prompt includes trade activity",
        "AAPL" in prompt or "BTC/USD" in prompt,
        "Trade symbols present ✓"
    )
    check(
        "Prompt includes current settings",
        str(con_settings.get("score_threshold")) in prompt,
        "Settings present ✓"
    )

except Exception as e:
    check("review prompt builder", False, str(e))


# ============================================================
# REVIEW — CLAUDE REVIEW (live API call)
# ============================================================
section("Review — Claude Review (live API call)")
print("  ⚠️  This makes one real Claude API call (~$0.01)\n")
try:
    from shared.review import get_claude_review

    mock_prompt = f"""
DAILY TRADING REVIEW — {date.today().isoformat()}

CONSERVATIVE STRATEGY
Portfolio value: $1,050.00 (started at $1,000.00)
P&L: +$50.00 (+5.00%)
Current settings: RSI 30/70, volume 1.2x, ATR 1.5x, mode TREND, threshold 6
Today: 1 BUY (AAPL +3%), 2 HOLDs

AGGRESSIVE STRATEGY
Portfolio value: $980.00 (started at $1,000.00)
P&L: -$20.00 (-2.00%)
Current settings: RSI 35/65, volume 1.1x, ATR 2.5x, mode BOTH, threshold 4
Today: 1 BUY (BTC/USD -2%), 1 HOLD

Analyze and output JSON adjustments.
"""

    review = get_claude_review(mock_prompt)
    check(
        "Claude review returns a dict",
        isinstance(review, dict),
        f"Type: {type(review).__name__}"
    )
    check(
        "Review has performance_summary",
        isinstance(review.get("performance_summary"), str) and len(review.get("performance_summary", "")) > 0,
        review.get("performance_summary", "missing")[:60]
    )
    check(
        "Review has conservative_adjustments",
        isinstance(review.get("conservative_adjustments"), dict),
        f"Keys: {list(review.get('conservative_adjustments', {}).keys())}"
    )
    check(
        "Review has aggressive_adjustments",
        isinstance(review.get("aggressive_adjustments"), dict),
        f"Keys: {list(review.get('aggressive_adjustments', {}).keys())}"
    )

    # Verify adjustment values are within safe bounds
    con_adj = review.get("conservative_adjustments", {})
    agg_adj = review.get("aggressive_adjustments", {})

    if "rsi_buy_threshold" in con_adj:
        check(
            "Conservative RSI threshold in bounds",
            20 <= con_adj["rsi_buy_threshold"] <= 40,
            f"Value: {con_adj['rsi_buy_threshold']}"
        )
    if "score_threshold" in agg_adj:
        check(
            "Aggressive score threshold in bounds",
            3 <= agg_adj["score_threshold"] <= 9,
            f"Value: {agg_adj['score_threshold']}"
        )

except Exception as e:
    check("Claude review call", False, str(e))


# ============================================================
# SUMMARY
# ============================================================
passed = sum(results)
total  = len(results)
print("\n" + "=" * 55)
if passed == total:
    print(f"  ✅ ALL {total} CHECKS PASSED — Phase 5 fully validated")
    print(f"  🚀 Ready to deploy to Render")
else:
    failed = total - passed
    print(f"  ❌ {passed}/{total} PASSED — {failed} check(s) failed")
    print(f"  → Fix failures above before deploying")
print("=" * 55 + "\n")

sys.exit(0 if passed == total else 1)
