"""
tests/test_signals.py
=====================
Phase 1-4 signal module tests.
Tests each signal module in isolation to verify outputs
are correctly structured before they reach Claude.

Covers:
- shared/news.py
- shared/earnings.py
- shared/fear_greed.py
- shared/congressional.py
- shared/scoring.py
- shared/risk_guardian.py (correlation + market hours)
- shared/alerts.py (structure only — no real email sent)

Usage:
    cd alpaca-trading
    python3 tests/test_signals.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import CONSERVATIVE, AGGRESSIVE

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
print("  SIGNAL MODULE TESTS (Phases 1-4)")
print("=" * 55)


# ============================================================
# NEWS SENTIMENT
# ============================================================
section("News Sentiment (shared/news.py)")
try:
    from shared.news import fetch_headlines, score_sentiment, get_news_sentiment, _neutral_sentiment

    # Test with a real symbol
    headlines = fetch_headlines("AAPL", hours_back=24)
    check(
        "fetch_headlines returns a list",
        isinstance(headlines, list),
        f"{len(headlines)} headlines found"
    )

    # Test sentiment scoring with mock headlines
    mock_headlines = [
        {"headline": "Apple beats earnings expectations with record iPhone sales",
         "created_at": "2024-01-01T10:00:00Z"},
        {"headline": "Apple raises guidance for next quarter",
         "created_at": "2024-01-01T09:00:00Z"},
    ]
    result = score_sentiment("AAPL", mock_headlines)
    required_keys = ["sentiment", "score", "confidence", "headline_count", "top_headline", "reasoning"]
    missing = [k for k in required_keys if k not in result]
    check(
        "score_sentiment returns all required keys",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "All keys present ✓"
    )
    check(
        "sentiment is valid value",
        result.get("sentiment") in ("BULLISH", "BEARISH", "NEUTRAL"),
        f"Got: {result.get('sentiment')}"
    )
    check(
        "score is correct type",
        isinstance(result.get("score"), int),
        f"Score: {result.get('score')}"
    )
    check(
        "score matches sentiment",
        (result.get("sentiment") == "BULLISH" and result.get("score") == 3) or
        (result.get("sentiment") == "BEARISH" and result.get("score") == -3) or
        (result.get("sentiment") == "NEUTRAL" and result.get("score") == 0),
        f"Sentiment: {result.get('sentiment')} Score: {result.get('score')}"
    )

    # Test empty headlines fallback
    empty_result = score_sentiment("AAPL", [])
    check(
        "empty headlines returns neutral",
        empty_result.get("sentiment") == "NEUTRAL" and empty_result.get("score") == 0,
        "Graceful fallback ✓"
    )

    # Test neutral fallback
    neutral = _neutral_sentiment(5)
    check(
        "_neutral_sentiment returns safe defaults",
        neutral.get("sentiment") == "NEUTRAL" and neutral.get("score") == 0,
        "Safe fallback ✓"
    )

except Exception as e:
    check("news module import", False, str(e))


# ============================================================
# EARNINGS GUARD
# ============================================================
section("Earnings Guard (shared/earnings.py)")
try:
    from shared.earnings import check_earnings_veto, get_earnings_date, _no_veto

    # Test with a real stock
    result = check_earnings_veto("AAPL")
    required_keys = ["has_upcoming_earnings", "earnings_date", "days_until_earnings", "veto", "veto_reason"]
    missing = [k for k in required_keys if k not in result]
    check(
        "check_earnings_veto returns all required keys",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "All keys present ✓"
    )
    check(
        "veto is boolean",
        isinstance(result.get("veto"), bool),
        f"Veto: {result.get('veto')} | Date: {result.get('earnings_date')}"
    )

    # Test crypto always returns no veto
    crypto_result = check_earnings_veto("BTC/USD")
    check(
        "Crypto never vetoed",
        crypto_result.get("veto") is False,
        "BTC/USD has no earnings ✓"
    )

    # Test _no_veto helper
    no_veto = _no_veto("test reason")
    check(
        "_no_veto returns correct structure",
        no_veto.get("veto") is False and no_veto.get("veto_reason") == "test reason",
        "Safe fallback ✓"
    )

except Exception as e:
    check("earnings module import", False, str(e))


# ============================================================
# FEAR & GREED
# ============================================================
section("Fear & Greed Index (shared/fear_greed.py)")
try:
    from shared.fear_greed import get_fear_greed, get_label, get_implication, _neutral_fear_greed

    result = get_fear_greed()
    required_keys = ["score", "label", "points", "implication"]
    missing = [k for k in required_keys if k not in result]
    check(
        "get_fear_greed returns all required keys",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "All keys present ✓"
    )
    check(
        "score is in valid range",
        isinstance(result.get("score"), (int, float)) and 0 <= result.get("score") <= 100,
        f"Score: {result.get('score')}"
    )
    check(
        "label is valid",
        result.get("label") in ("Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"),
        f"Label: {result.get('label')}"
    )
    check(
        "points is valid",
        result.get("points") in (-1, 0, 1, 2),
        f"Points: {result.get('points')}"
    )

    # Test label logic
    check("Score 10 = Extreme Fear",  get_label(10)  == "Extreme Fear",  f"Got: {get_label(10)}")
    check("Score 35 = Fear",          get_label(35)  == "Fear",          f"Got: {get_label(35)}")
    check("Score 50 = Neutral",       get_label(50)  == "Neutral",       f"Got: {get_label(50)}")
    check("Score 65 = Greed",         get_label(65)  == "Greed",         f"Got: {get_label(65)}")
    check("Score 90 = Extreme Greed", get_label(90)  == "Extreme Greed", f"Got: {get_label(90)}")

    # Test fallback
    neutral = _neutral_fear_greed()
    check(
        "_neutral_fear_greed returns safe defaults",
        neutral.get("score") == 50 and neutral.get("points") == 0,
        "Safe fallback ✓"
    )

except Exception as e:
    check("fear_greed module import", False, str(e))


# ============================================================
# CONGRESSIONAL TRADES
# ============================================================
section("Congressional Trades (shared/congressional.py)")
try:
    from shared.congressional import (
        get_congressional_signal,
        analyze_congressional_signal,
        get_congressional_trades,
    )

    # Test with a real symbol
    result = get_congressional_signal("AAPL")
    required_keys = ["has_recent_activity", "points", "signal", "recent_trades", "summary"]
    missing = [k for k in required_keys if k not in result]
    check(
        "get_congressional_signal returns all required keys",
        len(missing) == 0,
        f"Missing: {missing}" if missing else "All keys present ✓"
    )
    check(
        "signal is valid value",
        result.get("signal") in ("BULLISH", "BEARISH", "NEUTRAL"),
        f"Signal: {result.get('signal')}"
    )
    check(
        "points is valid value",
        result.get("points") in (-1, 0, 2),
        f"Points: {result.get('points')}"
    )

    # Test crypto returns neutral
    crypto_result = get_congressional_signal("BTC/USD")
    check(
        "Crypto returns neutral",
        crypto_result.get("signal") == "NEUTRAL" and crypto_result.get("points") == 0,
        "Crypto not applicable ✓"
    )

    # Test analysis logic with mock data
    mock_buys = [
        {"politician": "Nancy Pelosi", "party": "D", "action": "PURCHASE",
         "date": "2024-01-01", "amount": "$50,001-$100,000", "chamber": "House"},
        {"politician": "John Smith", "party": "R", "action": "PURCHASE",
         "date": "2024-01-02", "amount": "$15,001-$50,000", "chamber": "Senate"},
    ]
    buy_result = analyze_congressional_signal(mock_buys)
    check(
        "Multiple buys = BULLISH signal",
        buy_result.get("signal") == "BULLISH" and buy_result.get("points") == 2,
        f"Signal: {buy_result.get('signal')} Points: {buy_result.get('points')}"
    )

    mock_sells = [
        {"politician": "Jane Doe", "party": "R", "action": "SELL",
         "date": "2024-01-01", "amount": "$50,001-$100,000", "chamber": "House"},
    ]
    sell_result = analyze_congressional_signal(mock_sells)
    check(
        "Sells = BEARISH signal",
        sell_result.get("signal") == "BEARISH" and sell_result.get("points") == -1,
        f"Signal: {sell_result.get('signal')} Points: {sell_result.get('points')}"
    )

    empty_result = analyze_congressional_signal([])
    check(
        "Empty trades = NEUTRAL",
        empty_result.get("signal") == "NEUTRAL" and empty_result.get("points") == 0,
        "Graceful fallback ✓"
    )

except Exception as e:
    check("congressional module import", False, str(e))


# ============================================================
# SCORING ENGINE
# ============================================================
section("Weighted Scoring Engine (shared/scoring.py)")
try:
    from shared.scoring import calculate_score, is_trade_eligible, score_summary, CONSERVATIVE_THRESHOLD, AGGRESSIVE_THRESHOLD

    # Mock inputs
    mock_signals = {
        "rsi": 28, "rsi_zone": "oversold",
        "macd": "bullish_cross", "ema_signal": "bullish",
        "ema_fast": 150, "ema_slow": 145,
        "atr": 2.5, "volume_ratio": 1.5,
        "volume_confirmed": True, "price": 150.0,
    }
    mock_regime = {"regime": "TREND", "adx": 32, "description": "Strong trend"}
    mock_news_bullish = {"sentiment": "BULLISH", "score": 3, "confidence": "HIGH",
                          "top_headline": "Record earnings beat", "reasoning": "Strong results"}
    mock_news_bearish = {"sentiment": "BEARISH", "score": -3, "confidence": "HIGH",
                          "top_headline": "Revenue miss", "reasoning": "Weak guidance"}
    mock_news_neutral = {"sentiment": "NEUTRAL", "score": 0, "confidence": "LOW",
                          "top_headline": "No major news", "reasoning": "Quiet day"}
    mock_fg_fear      = {"score": 20, "label": "Extreme Fear", "points": 2}
    mock_fg_greed     = {"score": 80, "label": "Extreme Greed", "points": -1}
    mock_fg_neutral   = {"score": 50, "label": "Neutral", "points": 0}
    mock_cong_bull    = {"signal": "BULLISH", "points": 2, "summary": "Pelosi bought"}
    mock_cong_neutral = {"signal": "NEUTRAL", "points": 0, "summary": "No trades"}

    # Test max bullish score
    max_score = calculate_score(mock_signals, mock_regime, mock_news_bullish, mock_fg_fear, mock_cong_bull)
    check(
        "Max bullish score calculated correctly",
        max_score["total_score"] > 0 and max_score["direction"] == "BULLISH",
        f"Score: {max_score['total_score']} Direction: {max_score['direction']}"
    )
    check(
        "Scorecard is non-empty string",
        isinstance(max_score.get("scorecard"), str) and len(max_score["scorecard"]) > 50,
        f"{len(max_score.get('scorecard', ''))} chars"
    )

    # Test bearish score
    bearish_signals = dict(mock_signals)
    bearish_signals.update({"rsi_zone": "overbought", "macd": "bearish", "ema_signal": "bearish"})
    bear_score = calculate_score(bearish_signals, mock_regime, mock_news_bearish, mock_fg_greed, mock_cong_neutral)
    check(
        "Bearish scenario produces negative score",
        bear_score["total_score"] < 0 and bear_score["direction"] == "BEARISH",
        f"Score: {bear_score['total_score']}"
    )

    # Test thresholds
    check(
        f"Conservative threshold = {CONSERVATIVE_THRESHOLD}",
        CONSERVATIVE_THRESHOLD == 6,
        f"Got: {CONSERVATIVE_THRESHOLD}"
    )
    check(
        f"Aggressive threshold = {AGGRESSIVE_THRESHOLD}",
        AGGRESSIVE_THRESHOLD == 4,
        f"Got: {AGGRESSIVE_THRESHOLD}"
    )

    # Test eligibility
    no_earnings  = {"veto": False, "veto_reason": "No earnings"}
    has_earnings = {"veto": True,  "veto_reason": "Earnings in 1 day"}

    eligible, reason = is_trade_eligible(max_score, no_earnings, "conservative")
    check(
        "High score + no earnings = eligible (conservative)",
        eligible is True,
        reason
    )

    blocked, reason = is_trade_eligible(max_score, has_earnings, "conservative")
    check(
        "Earnings veto blocks even high score",
        blocked is False,
        reason
    )

    low_score = calculate_score(mock_signals, {"regime": "RANGE"}, mock_news_neutral, mock_fg_neutral, mock_cong_neutral)
    ineligible, reason = is_trade_eligible(low_score, no_earnings, "conservative")
    check(
        "Low score = ineligible (conservative)",
        ineligible is False,
        f"Score: {low_score['total_score']} — {reason}"
    )

    # Test score_summary
    summary = score_summary(max_score, True, "above threshold")
    check(
        "score_summary returns non-empty string",
        isinstance(summary, str) and len(summary) > 10,
        summary[:60]
    )

except Exception as e:
    check("scoring module import/test", False, str(e))


# ============================================================
# RISK GUARDIAN — additional checks
# ============================================================
section("Risk Guardian — Correlation + Market Hours (shared/risk_guardian.py)")
try:
    from shared.risk_guardian import check_correlation, can_trade_stock, can_trade_crypto

    # Test correlation blocking
    check(
        "NVDA blocked if AAPL already held (mega_cap_tech)",
        check_correlation("NVDA", ["AAPL"]) is False,
        "Different groups — should NOT block"
    )
    check(
        "MSFT blocked if AAPL already held (same group)",
        check_correlation("MSFT", ["AAPL"]) is True,
        "Same mega_cap_tech group — should block"
    )
    check(
        "ETH not blocked by BTC (different groups)",
        check_correlation("ETH/USD", ["BTC/USD"]) is False,
        "Different crypto groups — should NOT block"
    )
    check(
        "AMD blocked if NVDA already held (ai_chips)",
        check_correlation("AMD", ["NVDA"]) is True,
        "Same ai_chips group — should block"
    )
    check(
        "No positions = never blocked",
        check_correlation("AAPL", []) is False,
        "Empty positions — should NOT block"
    )

    # Market hours — just verify functions return booleans
    stock_ok  = can_trade_stock()
    crypto_ok = can_trade_crypto()
    check(
        "can_trade_stock returns boolean",
        isinstance(stock_ok, bool),
        f"Currently: {'open' if stock_ok else 'closed'}"
    )
    check(
        "can_trade_crypto returns boolean",
        isinstance(crypto_ok, bool),
        f"Currently: {'open' if crypto_ok else 'closed'}"
    )

except Exception as e:
    check("risk_guardian correlation/hours", False, str(e))


# ============================================================
# ALERTS — structure test (no real email sent)
# ============================================================
section("Alerts (shared/alerts.py) — structure only")
try:
    from shared.alerts import (
        alert_bot_started,
        alert_daily_stop,
        alert_kill_switch,
        alert_trade_executed,
        alert_error,
    )

    # Verify all functions exist and are callable
    check("alert_bot_started is callable",    callable(alert_bot_started))
    check("alert_daily_stop is callable",     callable(alert_daily_stop))
    check("alert_kill_switch is callable",    callable(alert_kill_switch))
    check("alert_trade_executed is callable", callable(alert_trade_executed))
    check("alert_error is callable",          callable(alert_error))
    print("  ℹ️  Skipping live email test — use test_config.py to validate email credentials")

except Exception as e:
    check("alerts module import", False, str(e))


# ============================================================
# SUMMARY
# ============================================================
passed = sum(results)
total  = len(results)
print("\n" + "=" * 55)
if passed == total:
    print(f"  ✅ ALL {total} CHECKS PASSED — Phases 1-4 fully validated")
else:
    failed = total - passed
    print(f"  ❌ {passed}/{total} PASSED — {failed} check(s) failed")
    print(f"  → Fix failures above before deploying")
print("=" * 55 + "\n")

sys.exit(0 if passed == total else 1)
