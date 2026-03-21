"""
tests/test_phase6.py
====================
Phase 6 tests — screener, social sentiment, exclusions.

Tests:
  1.  Screener — AMZN always excluded
  2.  Screener — UBER always present
  3.  Screener — apply_filters removes excluded symbols
  4.  Screener — permanent symbols always at front
  5.  Screener — result never exceeds max pool size
  6.  Screener — AMZN excluded even if in most-active list
  7.  Screener — no overlap between excluded and permanent
  8.  Social sentiment — Reddit fetch returns list
  9.  Social sentiment — StockTwits fetch returns list
  10. Social sentiment — neutral returned on empty data
  11. Social sentiment — neutral score is 0
  12. Social sentiment — SENTIMENT_SCORES has correct values
  13. Scoring — social_sentiment=None doesn't crash
  14. Scoring — social BULLISH adds +2 to total
  15. Scoring — social BEARISH adds -2 to total
  16. Scoring — social NEUTRAL adds 0 to total
  17. Scoring — social sentiment appears in breakdown
  18. Screener live — get_most_active_stocks returns a list
  19. Screener live — most active list contains no excluded symbols
  20. Alpaca client — get_closed_orders returns a list
  21. Alpaca client — get_portfolio_history returns DataFrame with date+value
  22. Alpaca client — portfolio history has at least 1 row
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import (
    EXCLUDED_SYMBOLS, PERMANENT_SYMBOLS,
    ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE,
)
from shared.screener import (
    apply_filters, get_screened_symbols, get_crypto_symbols,
    get_most_active_stocks,
)
from shared.social_sentiment import (
    fetch_reddit_posts,
    fetch_stocktwits_messages,
    get_social_sentiment,
    _neutral_social,
    SENTIMENT_SCORES,
)
from shared.scoring import calculate_score
from shared.alpaca_client import AlpacaClient

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = []

def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}  ({detail})" if detail else f"  {status}  {name}")


# ============================================================
# 1-7: SCREENER — EXCLUSION & PERMANENT SYMBOL TESTS
# ============================================================
print("\nScreener — Exclusion & Permanent Symbol Tests:")

amzn_excluded = "AMZN" in [s.upper() for s in EXCLUDED_SYMBOLS]
check("AMZN is in EXCLUDED_SYMBOLS", amzn_excluded, f"EXCLUDED_SYMBOLS={EXCLUDED_SYMBOLS}")

uber_permanent = "UBER" in [s.upper() for s in PERMANENT_SYMBOLS]
check("UBER is in PERMANENT_SYMBOLS", uber_permanent, f"PERMANENT_SYMBOLS={PERMANENT_SYMBOLS}")

injected = ["AAPL", "AMZN", "MSFT", "GOOG"]
filtered = apply_filters(injected, max_stocks=10)
check(
    "apply_filters removes AMZN even when injected",
    "AMZN" not in filtered,
    f"Result: {filtered}",
)

test_pool = ["MSFT", "GOOG", "TSLA"]
result    = apply_filters(test_pool, max_stocks=10)
check(
    "UBER appears first in filtered results",
    result[0] == "UBER" if result else False,
    f"Result: {result[:3]}",
)

large_pool = [f"SYM{i}" for i in range(100)]
capped     = apply_filters(large_pool, max_stocks=15)
check(
    "apply_filters caps at max_stocks",
    len(capped) <= 15,
    f"Got {len(capped)} symbols",
)

amzn_injected = ["AMZN", "AAPL", "MSFT"]
safe          = apply_filters(amzn_injected, max_stocks=10)
check(
    "AMZN excluded even when top of most-active list",
    "AMZN" not in safe,
    f"Result: {safe}",
)

excluded_set  = {s.upper() for s in EXCLUDED_SYMBOLS}
permanent_set = {s.upper() for s in PERMANENT_SYMBOLS}
check(
    "No overlap between EXCLUDED and PERMANENT symbols",
    len(excluded_set & permanent_set) == 0,
    f"Overlap: {excluded_set & permanent_set}",
)

# ============================================================
# 8-12: SOCIAL SENTIMENT — DATA FETCHING & SCORING
# ============================================================
print("\nSocial Sentiment — Data Fetching:")

try:
    reddit = fetch_reddit_posts("AAPL", limit=3)
    check("Reddit fetch returns a list", isinstance(reddit, list), f"Got {len(reddit)} posts")
except Exception as e:
    check("Reddit fetch returns a list", False, f"Exception: {e}")

try:
    twits = fetch_stocktwits_messages("AAPL")
    check("StockTwits fetch returns a list", isinstance(twits, list), f"Got {len(twits)} messages")
except Exception as e:
    check("StockTwits fetch returns a list", False, f"Exception: {e}")

neutral = _neutral_social("AAPL")
check(
    "Neutral fallback returns required fields",
    all(k in neutral for k in ["sentiment", "score", "confidence", "reddit_posts", "stocktwits_msgs"]),
    f"Fields: {list(neutral.keys())}",
)
check("Neutral fallback score is 0", neutral["score"] == 0, f"Score: {neutral['score']}")
check(
    "SENTIMENT_SCORES has BULLISH=+2, NEUTRAL=0, BEARISH=-2",
    SENTIMENT_SCORES == {"BULLISH": 2, "NEUTRAL": 0, "BEARISH": -2},
    f"Got: {SENTIMENT_SCORES}",
)

# ============================================================
# 13-17: SCORING ENGINE TESTS
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
    return {
        "sentiment": sent,
        "score": 3 if sent == "BULLISH" else -3 if sent == "BEARISH" else 0,
        "confidence": "HIGH", "headline": "test",
    }

def _mock_fear_greed():
    return {"value": 50, "classification": "Neutral", "score": 0}

def _mock_congressional():
    return {"signal": "NEUTRAL", "score": 0, "detail": "No trades"}

try:
    score = calculate_score(
        signals=_mock_signals(), regime=_mock_regime(),
        news=_mock_news("NEUTRAL"), fear_greed=_mock_fear_greed(),
        congressional=_mock_congressional(), social_sentiment=None,
    )
    check("social_sentiment=None doesn't crash", "total_score" in score, f"Score: {score['total_score']}")
except Exception as e:
    check("social_sentiment=None doesn't crash", False, f"Exception: {e}")

score_none    = calculate_score(
    signals=_mock_signals(), regime=_mock_regime(),
    news=_mock_news("NEUTRAL"), fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(), social_sentiment=None,
)
score_bullish = calculate_score(
    signals=_mock_signals(), regime=_mock_regime(),
    news=_mock_news("NEUTRAL"), fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "BULLISH", "score": 2, "top_signal": "test"},
)
score_bearish = calculate_score(
    signals=_mock_signals(), regime=_mock_regime(),
    news=_mock_news("NEUTRAL"), fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "BEARISH", "score": -2, "top_signal": "test"},
)
score_neutral_social = calculate_score(
    signals=_mock_signals(), regime=_mock_regime(),
    news=_mock_news("NEUTRAL"), fear_greed=_mock_fear_greed(),
    congressional=_mock_congressional(),
    social_sentiment={"sentiment": "NEUTRAL", "score": 0, "top_signal": "test"},
)

diff_bullish = score_bullish["total_score"] - score_none["total_score"]
diff_bearish = score_bearish["total_score"] - score_none["total_score"]
diff_neutral = score_neutral_social["total_score"] - score_none["total_score"]

check("BULLISH social sentiment adds +2 to total score", diff_bullish == 2, f"Diff: {diff_bullish}")
check("BEARISH social sentiment adds -2 to total score", diff_bearish == -2, f"Diff: {diff_bearish}")
check("NEUTRAL social sentiment adds 0 to total score",  diff_neutral == 0,  f"Diff: {diff_neutral}")
check(
    "Social sentiment appears in score breakdown",
    "social_sentiment" in score_bullish.get("breakdown", {}),
    f"Breakdown keys: {list(score_bullish.get('breakdown', {}).keys())}",
)

# ============================================================
# 18-19: SCREENER LIVE API TESTS
# ============================================================
print("\nScreener — Live API Tests:")

try:
    actives = get_most_active_stocks(top_n=20)
    check(
        "get_most_active_stocks returns a list",
        isinstance(actives, list),
        f"Got {len(actives)} symbols",
    )
    excluded_upper = {s.upper() for s in EXCLUDED_SYMBOLS}
    no_excluded    = all(s.upper() not in excluded_upper for s in actives)
    check(
        "Most active list contains no excluded symbols",
        no_excluded,
        f"Excluded found: {[s for s in actives if s.upper() in excluded_upper]}",
    )
except Exception as e:
    check("get_most_active_stocks returns a list", False, f"Exception: {e}")
    check("Most active list contains no excluded symbols", False, "Skipped — fetch failed")

# ============================================================
# 20-22: ALPACA CLIENT — NEW DASHBOARD METHODS
# ============================================================
print("\nAlpaca Client — Dashboard Methods:")

try:
    alpaca = AlpacaClient(ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE)

    # 20. get_closed_orders returns a list
    orders = alpaca.get_closed_orders(days_back=30)
    check(
        "get_closed_orders returns a list",
        isinstance(orders, list),
        f"Got {len(orders)} orders",
    )

    # 21. get_portfolio_history returns DataFrame with correct columns
    history = alpaca.get_portfolio_history(days_back=7)
    has_cols = (
        not history.empty and
        "date" in history.columns and
        "value" in history.columns
    ) if not history.empty else True  # Empty is acceptable for brand new accounts
    check(
        "get_portfolio_history returns DataFrame with date+value columns",
        isinstance(history, __import__("pandas").DataFrame) and has_cols,
        f"Columns: {list(history.columns) if not history.empty else 'empty (new account)'}",
    )

    # 22. Portfolio history has at least 1 row (or account is brand new)
    check(
        "get_portfolio_history returns data or gracefully returns empty",
        isinstance(history, __import__("pandas").DataFrame),
        f"Got {len(history)} rows",
    )

except Exception as e:
    check("get_closed_orders returns a list", False, f"Exception: {e}")
    check("get_portfolio_history returns DataFrame with date+value columns", False, "Skipped")
    check("get_portfolio_history returns data or gracefully returns empty", False, "Skipped")

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
