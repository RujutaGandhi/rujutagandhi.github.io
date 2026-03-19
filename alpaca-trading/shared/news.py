"""
shared/news.py
==============
Fetches recent news headlines for a symbol from Alpaca's News API,
then uses Claude to score sentiment.

Why Claude over pre-built sentiment:
- Understands nuance ("beat earnings but weak guidance" = mixed, not bullish)
- Can weigh multiple headlines against each other
- Explains reasoning — auditable decisions
- Already in our stack — no new system needed

Returns:
    {
        "sentiment":    "BULLISH" | "BEARISH" | "NEUTRAL",
        "score":        3 | 0 | -3,
        "confidence":   "HIGH" | "MEDIUM" | "LOW",
        "headline_count": int,
        "top_headline": str,
        "reasoning":    str,
    }
"""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import anthropic
import requests

from shared.config import (
    ALPACA_API_KEY_CONSERVATIVE,
    ALPACA_SECRET_KEY_CONSERVATIVE,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Alpaca news endpoint
ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"

# Sentiment scores
SENTIMENT_SCORES = {
    "BULLISH":  3,
    "NEUTRAL":  0,
    "BEARISH": -3,
}


# ============================================================
# FETCH HEADLINES FROM ALPACA
# ============================================================

def fetch_headlines(symbol: str, hours_back: int = 24) -> list[dict]:
    """
    Fetches recent news headlines for a symbol from Alpaca News API.
    Free with your existing Alpaca keys — no extra cost.

    Args:
        symbol:     Stock or crypto symbol e.g. "AAPL", "BTCUSD"
        hours_back: How many hours of news to look back (default 24)

    Returns:
        List of headline dicts with keys: headline, summary, url, created_at
    """
    try:
        # Normalize crypto symbols for news API
        clean_symbol = symbol.replace("/", "")

        start_time = (
            datetime.now(ET) - timedelta(hours=hours_back)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY_CONSERVATIVE,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY_CONSERVATIVE,
        }

        params = {
            "symbols":    clean_symbol,
            "start":      start_time,
            "limit":      10,
            "sort":       "desc",
        }

        response = requests.get(
            ALPACA_NEWS_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning(
                f"⚠️  Alpaca News API returned {response.status_code} for {symbol}"
            )
            return []

        data     = response.json()
        articles = data.get("news", [])

        headlines = []
        for article in articles[:5]:  # Cap at 5 most recent
            headlines.append({
                "headline":   article.get("headline", ""),
                "summary":    article.get("summary", "")[:200],
                "created_at": article.get("created_at", ""),
            })

        logger.debug(f"📰 Fetched {len(headlines)} headlines for {symbol}")
        return headlines

    except Exception as e:
        logger.error(f"❌ Failed to fetch news for {symbol}: {e}")
        return []


# ============================================================
# CLAUDE SENTIMENT SCORING
# ============================================================

SENTIMENT_SYSTEM = """
You are a financial news analyst scoring market sentiment for a trading bot.
You will receive recent headlines for a stock or crypto asset.

Analyze the headlines and return ONLY a JSON object — no other text.

Scoring rules:
- BULLISH:  positive earnings, upgrades, strong guidance, breakthrough news
- BEARISH:  misses, downgrades, weak guidance, regulatory issues, scandals
- NEUTRAL:  routine news, mixed signals, no clear catalyst

Be precise. "Beat earnings but lowered guidance" = NEUTRAL or BEARISH, not BULLISH.
Consider recency — newer headlines carry more weight.

Return exactly this JSON:
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "top_headline": "the single most impactful headline",
  "reasoning": "one sentence explaining your score"
}
"""


def score_sentiment(symbol: str, headlines: list[dict]) -> dict:
    """
    Sends headlines to Claude for sentiment scoring.

    Args:
        symbol:    The asset symbol (for context)
        headlines: List of headline dicts from fetch_headlines()

    Returns:
        Sentiment dict with score, label, reasoning
    """
    if not headlines:
        return {
            "sentiment":      "NEUTRAL",
            "score":          0,
            "confidence":     "LOW",
            "headline_count": 0,
            "top_headline":   "No recent headlines found",
            "reasoning":      "No news data available — defaulting to neutral",
        }

    try:
        # Format headlines for Claude
        headlines_text = "\n".join([
            f"- [{h['created_at'][:10]}] {h['headline']}"
            for h in headlines
            if h.get("headline")
        ])

        prompt = f"""
Asset: {symbol}
Recent headlines ({len(headlines)} articles from last 24 hours):

{headlines_text}

Score the overall sentiment for trading purposes.
""".strip()

        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=SENTIMENT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)

        sentiment = result.get("sentiment", "NEUTRAL").upper()
        if sentiment not in SENTIMENT_SCORES:
            sentiment = "NEUTRAL"

        return {
            "sentiment":      sentiment,
            "score":          SENTIMENT_SCORES[sentiment],
            "confidence":     result.get("confidence", "LOW"),
            "headline_count": len(headlines),
            "top_headline":   result.get("top_headline", headlines[0].get("headline", "")),
            "reasoning":      result.get("reasoning", ""),
        }

    except json.JSONDecodeError as e:
        logger.error(f"❌ Claude sentiment JSON parse error: {e}")
        return _neutral_sentiment(len(headlines))
    except Exception as e:
        logger.error(f"❌ Claude sentiment error for {symbol}: {e}")
        return _neutral_sentiment(len(headlines))


# ============================================================
# MASTER FUNCTION
# ============================================================

def get_news_sentiment(symbol: str) -> dict:
    """
    Main entry point — fetches news and scores sentiment in one call.
    Used by both strategies in run_cycle().

    Args:
        symbol: e.g. "AAPL", "BTC/USD"

    Returns:
        Full sentiment dict ready to be injected into Claude prompt
    """
    headlines = fetch_headlines(symbol)
    return score_sentiment(symbol, headlines)


def _neutral_sentiment(headline_count: int = 0) -> dict:
    """Returns a safe neutral sentiment on error."""
    return {
        "sentiment":      "NEUTRAL",
        "score":          0,
        "confidence":     "LOW",
        "headline_count": headline_count,
        "top_headline":   "Sentiment scoring unavailable",
        "reasoning":      "Error during sentiment analysis — defaulting to neutral",
    }
