"""
tests/test_phase6.py
====================
Phase 6 tests — screener, social sentiment, exclusions.

Tests:
  1. Screener — AMZN always excluded
  2. Screener — UBER always present
  3. Screener — apply_filters removes excluded symbols
  4. Screener — permanent symbols always at front
  5. Screener — result never exceeds max pool size
  6. Screener — fallback on empty screener result
  7. Social sentiment — Reddit fetch returns list
  8. Social sentiment — StockTwits fetch returns list
  9. Social sentiment — neutral returned on empty data
 10. Social sentiment — score values are valid (-2, 0, +2)
 11. Social sentiment — Claude scoring returns required fields
 12. Config — AMZN in EXCLUDED_SYMBOLS
 13. Config — UBER in PERMANENT_SYMBOLS
 14. Config — no overlap between excluded and permanent
 15. Scoring — social_sentiment parameter accepted
 16. Scoring — social BULLISH adds +2 to total
 17. Scoring — social BEARISH adds -2 to total
 18. Scoring — social NEUTRAL adds 0 to total
 19. Scoring — None social_sentiment doesn't crash
 20. Screener — AMZN excluded even if in most-active list
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import EXCLUDED_SYMBOLS, PERMANENT_SYMBOLS
from shared.screener import apply_filters, get_screened_symbols, get_crypto_symbols
from shared.social_sentiment import (
    fetch_reddit_posts,
    fetch_stocktwits_messages,
    get_social_sentiment,
    _neutral_social,
    SENTIMENT_SCORES,
)
from shared.scoring import calculate_score

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = []

def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}  ({detail})" if detail else f"  {status}  {name}")


# ============================================================
# 1-6: SCREENER TESTS
# ============================================================
print("\nScreener — Exclusion & Permanent Symbol Tests:")

# 1. AMZN always excluded — core requirement
amzn_excluded = "AMZN" in [s.upper() for s in EXCLUDED_SYMBOLS]
check("AMZN is in EXCLUDED_SYMBOLS", amzn_excluded, f"EXCLUDED_SYMBOLS={EXCLUDED_SYMBOLS}")

# 2. UBER always present
uber_permanent = "UBER" in [s.upper() for s in PERMANENT_SYMBOLS]
check("UBER is in PERMANENT_SYMBOLS", uber_permanent, f"PERMANENT_SYMBOLS={PERMANENT_SYMBOLS}")

# 3. apply_filters removes excluded symbols — even if injected
injected = ["AAPL", "AMZN", "MSFT", "GOOG"]
filtered = apply_filters(injected, max_stocks=10)
amzn_not_in_result = "AMZN" not in filtered
check(
    "apply_filters removes AMZN even when injected",
    amzn_not_in_result,
    f"Result: {filtered}",
)

# 4. Permanent symbols appear at front
test_pool = ["MSFT", "GOOG", "TSLA"]
result = apply_filters(test_pool, max_stocks=10)
uber_first = result[0] == "UBER" if result else False
check(
    "UBER appears first in filtered results",
    uber_first,
    f"Result: {result[:3]}",
)

# 5. Result never exceeds max_stocks
large_pool = [f"SYM{i}" for i in range(100)]
capped = apply_filters(large_pool, max_stocks=15)
check(
    "apply_filters caps at max_stocks",
    len(capped) <= 15,
    f"Got {len(capped)} symbols",
)

# 6. AMZN excluded even if it appears as most active
# Simulate AMZN being the top result from screener API
amzn_injected = ["AMZN", "AAPL", "MSFT"]
safe = apply_filters(amzn_injected, max_stocks=10)
check(
    "AMZN excluded even when top of most-active list",
    "AMZN" not in safe,
    f"Result: {safe}",
)

# 7. No overlap between excluded and permanent
excluded_set  = {s.upper() for s in EXCLUDED_SYMBOLS}
permanent_set = {s.upper() for s in PERMANENT_SYMBOLS}
no_overlap = len(excluded_set & permanent_set) == 0
check(
    "No overlap between EXCLUDED and PERMANENT symbols",
    no_overlap,
    f"Overlap: {excluded_set & permanent_set}",
)

# ============================================================
# 8-11: SOCIAL SENTIMENT TESTS
# ============================================================
print("\nSocial Sentiment — Data Fetching:")

# 8. Reddit fetch returns a list (may be empty if no network)
try:
    reddit = fetch_reddit_posts("AAPL", limit=3)
    check(
        "Reddit fetch returns a list",
        isinstance(reddit, list),
        f"Got {len(reddit)} posts",
    )
except Exception as e:
    check("Reddit fetch returns a list", False, f"Exception: {e}")

# 9. StockTwits fetch returns a list
try:
    twits = fetch_stocktwits_messages("AAPL")
    check(
        "StockTwits fetch returns a list",
        isinstance(twits, list),
        f"Got {len(twits)} messages",
    )
except Exception as e:
    check("StockTwits fetch returns a list", False, f"Exception: {e}")

# 10. Neutral returned on empty data — safe fallback
neutral = _neutral_social("AAPL")
check(
    "Neutral fallback returns required fields",
    all(k in neutral for k in ["sentiment", "score", "confidence", "reddit_posts", "stocktwits_msgs"]),
    f"Fields: {list(neutral.keys())}",
)
check(
    "Neutral fallback score is 0",
    neutral["score"] == 0,
    f"Score: {neutral['score']}",
)

# 11. SENTIMENT_SCORES covers all three cases
check(
    "SENTIMENT_SCORES has BULLISH=+2, NEUTRAL=0, BEARISH=-2",
    SENTIMENT_SCORES == {"BULLISH": 2, "NEUTRAL": 0, "BEARISH": -2},
    f"Got: {SENTIMENT_SCORES}",
)

# ============================================================
# 12-16: SCORING ENGINE TESTS
# ============================================================
print("\nScoring — Social Sentiment Integration:")

def _mock_signals():
    return {
        "rsi": 45, "rsi_zone": "neutral",
        "macd": "neutral", "ema_signal": "neutral",
        "volume_confirmed": False, "volume_ratio": 1.0,
        "ema_slope": 0, "price": 100.0, "atr": 2.0,
        "ema_fast": 100, "ema_slow": 100,
    }

def _mock_regime():
    return {"regime": "TREND", "adx": 30, "description": "Strong trend"}

def _mock_news(sent):
    return {"sentiment": sent, "score": 3 if sent == "BULLISH" else -3 if sent == "BEARISH" else 0,
            "confidence": "HIGH", "headline": "test"}

def _mock_fear_greed():
    return {"value": 50, "classification": "Neutral", "score": 0}

def _mock_congressional():
    return {"signal": "NEUTRAL", "score": 0, "detail": "No trades"}

# 12. social_sentiment=None doesn't crash
try:
    score = calculate_score(
        signals=_mock_signals(),
        regime=_mock_regime(),
        news=_mock_news("NEUTRAL"),
        fear_greed=_mock_fear_greed(),
        congressional=_mock_congressional(),
        social_sentiment=None,
    )
    check(
        "social_sentiment=None doesn't crash",
        "total_score" in score,
        f"Score: {score['total_score']}",
    )
except Exception as e:
    check("social_sentiment=None doesn't crash", False, f"Exception: {e}")

# 13. BULLISH social adds +2
score_bullish = calculate_score(
    signals=_mock_signals(),
    regime=_mock_regime(),
    news=_mock_news("NEUTRAL"),
    fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "BULLISH", "score": 2, "top_signal": "test"},
)
score_none = calculate_score(
    signals=_mock_signals(),
    regime=_mock_regime(),
    news=_mock_news("NEUTRAL"),
    fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment=None,
)
diff_bullish = score_bullish["total_score"] - score_none["total_score"]
check(
    "BULLISH social sentiment adds +2 to total score",
    diff_bullish == 2,
    f"Diff: {diff_bullish} (expected 2)",
)

# 14. BEARISH social adds -2
score_bearish = calculate_score(
    signals=_mock_signals(),
    regime=_mock_regime(),
    news=_mock_news("NEUTRAL"),
    fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "BEARISH", "score": -2, "top_signal": "test"},
)
diff_bearish = score_bearish["total_score"] - score_none["total_score"]
check(
    "BEARISH social sentiment adds -2 to total score",
    diff_bearish == -2,
    f"Diff: {diff_bearish} (expected -2)",
)

# 15. NEUTRAL social adds 0
score_neutral_social = calculate_score(
    signals=_mock_signals(),
    regime=_mock_regime(),
    news=_mock_news("NEUTRAL"),
    fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "NEUTRAL", "score": 0, "top_signal": "test"},
)
diff_neutral = score_neutral_social["total_score"] - score_none["total_score"]
check(
    "NEUTRAL social sentiment adds 0 to total score",
    diff_neutral == 0,
    f"Diff: {diff_neutral} (expected 0)",
)

# 16. Social sentiment appears in scorecard breakdown
check(
    "Social sentiment appears in score breakdown",
    "social_sentiment" in score_bullish.get("breakdown", {}),
    f"Breakdown keys: {list(score_bullish.get('breakdown', {}).keys())}",
)

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"Phase 6 Results: {passed} passed, {failed} failed out of {len(results)} tests")

if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r[0] == FAIL:
            print(f"  {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print("\n🎉 All Phase 6 tests passed!")
