"""
shared/scoring.py
=================
Weighted signal scoring engine — replaces simple vote counting.

All signals feed into a point total. Thresholds determine
whether Claude gets called at all, and with what context.

Point System:
─────────────────────────────────────────────────────
SIGNAL                  BULLISH    BEARISH    NOTES
─────────────────────────────────────────────────────
News sentiment          +3         -3         Claude-scored
Social sentiment        +2         -2         Reddit + StockTwits
Congressional trades    +2         -1         45-day lag
Regime (ADX)            +2          0         TREND only
Fear & Greed            +2         -1         Macro filter
RSI                     +1         -1         Momentum
MACD                    +1         -1         Trend
EMA crossover           +1         -1         Trend filter
Volume ratio            +1          0         Confirmation
─────────────────────────────────────────────────────
Earnings veto           BLOCKS TRADE ENTIRELY (hard veto)
─────────────────────────────────────────────────────

Thresholds:
  Conservative: 6+ points to trade
  Aggressive:   4+ points to trade

Max possible bullish score: 15 points
Min possible bearish score: -10 points
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# THRESHOLDS
# ============================================================
CONSERVATIVE_THRESHOLD = 6
AGGRESSIVE_THRESHOLD   = 4


# ============================================================
# SCORE CALCULATOR
# ============================================================

def calculate_score(
    signals:          dict,
    regime:           dict,
    news:             dict,
    fear_greed:       dict,
    congressional:    dict,
    social_sentiment: dict = None,
) -> dict:
    """
    Calculates the full weighted score for a trading setup.

    Args:
        signals:       From indicators.get_latest_signals()
        regime:        From regime_filter.regime_summary()
        news:          From news.get_news_sentiment()
        fear_greed:    From fear_greed.get_fear_greed()
        congressional: From congressional.get_congressional_signal()

    Returns:
        {
            "total_score":    int,
            "bullish_score":  int,
            "bearish_score":  int,
            "breakdown":      dict,   # Per-signal contribution
            "direction":      "BULLISH" | "BEARISH" | "NEUTRAL",
            "scorecard":      str,    # Human-readable for Claude prompt
        }
    """
    breakdown = {}
    bullish   = 0
    bearish   = 0

    # ── News Sentiment (+3 / -3) ─────────────────────────────
    news_sentiment = news.get("sentiment", "NEUTRAL")
    if news_sentiment == "BULLISH":
        pts = 3
        bullish += pts
    elif news_sentiment == "BEARISH":
        pts = -3
        bearish += abs(pts)
    else:
        pts = 0

    breakdown["news_sentiment"] = {
        "signal": news_sentiment,
        "points": pts,
        "detail": news.get("top_headline", "No headline"),
    }

    # ── Social Sentiment (+2 / -2) ───────────────────────────
    social = social_sentiment or {}
    social_sent = social.get("sentiment", "NEUTRAL")
    if social_sent == "BULLISH":
        social_pts = 2
        bullish   += social_pts
    elif social_sent == "BEARISH":
        social_pts = -2
        bearish   += 2
    else:
        social_pts = 0

    breakdown["social_sentiment"] = {
        "signal": social_sent,
        "points": social_pts,
        "detail": social.get("top_signal", "No social data"),
    }

    # ── Congressional Trades (+2 / -1) ───────────────────────
    cong_signal = congressional.get("signal", "NEUTRAL")
    cong_pts    = congressional.get("points", 0)
    if cong_pts > 0:
        bullish += cong_pts
    elif cong_pts < 0:
        bearish += abs(cong_pts)

    breakdown["congressional"] = {
        "signal": cong_signal,
        "points": cong_pts,
        "detail": congressional.get("summary", "No data"),
    }

    # ── Regime / ADX (+2 / 0) ────────────────────────────────
    regime_label = regime.get("regime", "UNCLEAR")
    if regime_label == "TREND":
        regime_pts = 2
        bullish   += regime_pts
    else:
        regime_pts = 0

    breakdown["regime"] = {
        "signal": regime_label,
        "points": regime_pts,
        "detail": f"ADX: {regime.get('adx', 'N/A')}",
    }

    # ── Fear & Greed (+2 to -1) ──────────────────────────────
    fg_pts   = fear_greed.get("points", 0)
    fg_label = fear_greed.get("label", "Neutral")
    if fg_pts > 0:
        bullish += fg_pts
    elif fg_pts < 0:
        bearish += abs(fg_pts)

    breakdown["fear_greed"] = {
        "signal": fg_label,
        "points": fg_pts,
        "detail": f"Score: {fear_greed.get('score', 'N/A')}/100",
    }

    # ── RSI (+1 / -1) ────────────────────────────────────────
    rsi_zone = signals.get("rsi_zone", "neutral")
    if rsi_zone == "oversold":
        rsi_pts  = 1
        bullish += rsi_pts
    elif rsi_zone == "overbought":
        rsi_pts  = -1
        bearish += 1
    else:
        rsi_pts = 0

    breakdown["rsi"] = {
        "signal": rsi_zone.upper(),
        "points": rsi_pts,
        "detail": f"RSI: {signals.get('rsi', 'N/A')}",
    }

    # ── MACD (+1 / -1) ───────────────────────────────────────
    macd = signals.get("macd", "neutral")
    if macd in ("bullish", "bullish_cross"):
        macd_pts  = 1
        bullish  += macd_pts
    elif macd in ("bearish", "bearish_cross"):
        macd_pts  = -1
        bearish  += 1
    else:
        macd_pts = 0

    breakdown["macd"] = {
        "signal": macd.upper(),
        "points": macd_pts,
        "detail": "Crossover signal" if "cross" in macd else "Trend signal",
    }

    # ── EMA Crossover (+1 / -1) ──────────────────────────────
    ema_signal = signals.get("ema_signal", "neutral")
    if ema_signal == "bullish":
        ema_pts  = 1
        bullish += ema_pts
    elif ema_signal == "bearish":
        ema_pts  = -1
        bearish += 1
    else:
        ema_pts = 0

    breakdown["ema"] = {
        "signal": ema_signal.upper(),
        "points": ema_pts,
        "detail": f"EMA9: {signals.get('ema_fast', 'N/A')} vs EMA21: {signals.get('ema_slow', 'N/A')}",
    }

    # ── Volume Confirmation (+1 / 0) ─────────────────────────
    vol_confirmed = signals.get("volume_confirmed", False)
    vol_pts       = 1 if vol_confirmed else 0
    if vol_pts:
        bullish += vol_pts

    breakdown["volume"] = {
        "signal": "CONFIRMED" if vol_confirmed else "WEAK",
        "points": vol_pts,
        "detail": f"Volume ratio: {signals.get('volume_ratio', 'N/A')}x avg",
    }

    # ── Final Score ──────────────────────────────────────────
    total_score = bullish - bearish

    if total_score > 0:
        direction = "BULLISH"
    elif total_score < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    scorecard = _build_scorecard(breakdown, total_score, bullish, bearish)

    return {
        "total_score":   total_score,
        "bullish_score": bullish,
        "bearish_score": bearish,
        "breakdown":     breakdown,
        "direction":     direction,
        "scorecard":     scorecard,
    }


# ============================================================
# TRADE ELIGIBILITY
# ============================================================

def is_trade_eligible(
    score:         dict,
    earnings:      dict,
    strategy_type: str,
) -> tuple[bool, str]:
    """
    Determines if a setup is eligible to trade.

    Args:
        score:         From calculate_score()
        earnings:      From earnings.check_earnings_veto()
        strategy_type: "conservative" | "aggressive"

    Returns:
        (eligible: bool, reason: str)
    """
    # Hard veto — earnings always blocks
    if earnings.get("veto"):
        return False, earnings.get("veto_reason", "Earnings veto")

    total = score.get("total_score", 0)

    if strategy_type == "conservative":
        if total >= CONSERVATIVE_THRESHOLD:
            return True, f"Score {total} >= threshold {CONSERVATIVE_THRESHOLD}"
        return False, f"Score {total} below conservative threshold ({CONSERVATIVE_THRESHOLD})"

    if strategy_type == "aggressive":
        if total >= AGGRESSIVE_THRESHOLD:
            return True, f"Score {total} >= threshold {AGGRESSIVE_THRESHOLD}"
        return False, f"Score {total} below aggressive threshold ({AGGRESSIVE_THRESHOLD})"

    return False, "Unknown strategy type"


# ============================================================
# SCORECARD FORMATTER
# Produces the human-readable block injected into Claude prompt
# ============================================================

def _build_scorecard(
    breakdown:   dict,
    total_score: int,
    bullish:     int,
    bearish:     int,
) -> str:
    """Builds a formatted scorecard string for Claude's prompt."""

    lines = ["Signal Scorecard:"]
    lines.append(f"{'─' * 52}")

    signal_order = [
        "news_sentiment", "social_sentiment", "congressional", "regime",
        "fear_greed", "rsi", "macd", "ema", "volume"
    ]

    labels = {
        "news_sentiment":   "News Sentiment (Claude)",
        "social_sentiment": "Social Sentiment (Reddit/ST)",
        "congressional":    "Congressional Trades",
        "regime":           "Market Regime (ADX)",
        "fear_greed":       "Fear & Greed Index",
        "rsi":              "RSI",
        "macd":             "MACD",
        "ema":              "EMA Crossover",
        "volume":           "Volume Confirmation",
    }

    for key in signal_order:
        if key not in breakdown:
            continue
        item   = breakdown[key]
        label  = labels.get(key, key)
        signal = item.get("signal", "N/A")
        pts    = item.get("points", 0)
        detail = item.get("detail", "")
        pt_str = f"+{pts}" if pts > 0 else str(pts)
        lines.append(f"  {label:<28} {signal:<14} {pt_str:>4} pts   {detail}")

    lines.append(f"{'─' * 52}")
    lines.append(f"  {'Total Score:':<28} {'':14} {total_score:>+4} pts")
    lines.append(f"  (Bullish: +{bullish} | Bearish: -{bearish})")

    return "\n".join(lines)


# ============================================================
# QUICK SUMMARY FOR LOGGING
# ============================================================

def score_summary(score: dict, eligible: bool, reason: str) -> str:
    """Returns a one-line summary for logging."""
    return (
        f"Score: {score['total_score']} "
        f"(B:{score['bullish_score']} / S:{score['bearish_score']}) | "
        f"{'✅ ELIGIBLE' if eligible else '⏭️  SKIP'}: {reason}"
    )
