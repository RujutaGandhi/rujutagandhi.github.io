"""
shared/social_sentiment.py
===========================
Fetches Reddit and StockTwits sentiment for a symbol,
then uses Claude to score the combined social signal.

Why social sentiment matters:
- Retail momentum often shows up on Reddit/StockTwits
  before it shows up in price
- r/wallstreetbets moves can be significant for small/mid caps
- StockTwits is finance-specific, higher signal-to-noise
  than general Twitter

Both APIs are free with no authentication required for
basic public data.

Returns:
    {
        "sentiment":      "BULLISH" | "BEARISH" | "NEUTRAL",
        "score":          2 | 0 | -2,
        "confidence":     "HIGH" | "MEDIUM" | "LOW",
        "reddit_posts":   int,
        "stocktwits_msgs": int,
        "top_signal":     str,
        "reasoning":      str,
    }
"""

import json
import logging
from typing import Optional

import anthropic
import requests

from shared.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

# Free public API endpoints
REDDIT_URL      = "https://www.reddit.com/search.json"
STOCKTWITS_URL  = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

SENTIMENT_SCORES = {
    "BULLISH":  2,
    "NEUTRAL":  0,
    "BEARISH": -2,
}


# ============================================================
# REDDIT
# ============================================================

def fetch_reddit_posts(symbol: str, limit: int = 10) -> list[dict]:
    """
    Fetches recent Reddit posts mentioning a symbol.
    Uses public search API — no auth needed.
    Searches r/wallstreetbets, r/stocks, r/investing.
    """
    try:
        headers = {"User-Agent": "TradingBot/1.0 (research)"}
        params  = {
            "q":       f"{symbol} stock",
            "sort":    "new",
            "limit":   limit,
            "t":       "day",
            "subreddit": "wallstreetbets+stocks+investing+stockmarket",
        }

        response = requests.get(
            REDDIT_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            logger.debug(f"Reddit API returned {response.status_code} for {symbol}")
            return []

        data  = response.json()
        posts = data.get("data", {}).get("children", [])

        results = []
        for post in posts[:5]:
            p = post.get("data", {})
            results.append({
                "title":     p.get("title", ""),
                "score":     p.get("score", 0),
                "subreddit": p.get("subreddit", ""),
                "url":       p.get("url", ""),
            })

        logger.debug(f"Reddit: {len(results)} posts for {symbol}")
        return results

    except Exception as e:
        logger.debug(f"Reddit fetch failed for {symbol}: {e}")
        return []


# ============================================================
# STOCKTWITS
# ============================================================

def fetch_stocktwits_messages(symbol: str) -> list[dict]:
    """
    Fetches recent StockTwits messages for a symbol.
    Public API — no auth needed for basic stream.
    StockTwits users often tag messages as Bullish/Bearish.
    """
    try:
        # StockTwits uses no slash for crypto: BTCUSD not BTC/USD
        clean_symbol = symbol.replace("/", "")

        response = requests.get(
            STOCKTWITS_URL.format(symbol=clean_symbol),
            timeout=10,
        )

        if response.status_code != 200:
            logger.debug(f"StockTwits API returned {response.status_code} for {symbol}")
            return []

        data     = response.json()
        messages = data.get("messages", [])

        results = []
        for msg in messages[:10]:
            sentiment_tag = None
            entities = msg.get("entities", {})
            sentiment = entities.get("sentiment", {})
            if sentiment:
                sentiment_tag = sentiment.get("basic", None)

            results.append({
                "body":      msg.get("body", "")[:200],
                "sentiment": sentiment_tag,  # "Bullish", "Bearish", or None
                "likes":     msg.get("likes", {}).get("total", 0),
            })

        logger.debug(f"StockTwits: {len(results)} messages for {symbol}")
        return results

    except Exception as e:
        logger.debug(f"StockTwits fetch failed for {symbol}: {e}")
        return []


# ============================================================
# CLAUDE SOCIAL SENTIMENT SCORING
# ============================================================

SOCIAL_SENTIMENT_SYSTEM = """
You are a financial analyst scoring social media sentiment for a trading bot.
You will receive Reddit posts and StockTwits messages about a stock or crypto.

Analyze the sentiment and return ONLY a JSON object — no other text.

Scoring rules:
- BULLISH:  predominantly positive posts, buying signals, hype, catalysts
- BEARISH:  predominantly negative posts, selling pressure, FUD, warnings
- NEUTRAL:  mixed signals, low activity, or irrelevant noise

Weight by quality: StockTwits Bullish/Bearish tags > Reddit score/upvotes > raw text.
Be skeptical of hype without substance. Reddit wallstreetbets posts can be noise.

Return exactly this JSON:
{
  "sentiment":  "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "top_signal": "the single most meaningful signal from the data",
  "reasoning":  "one sentence explaining the score"
}
"""


def score_social_sentiment(
    symbol:     str,
    reddit:     list[dict],
    stocktwits: list[dict],
) -> dict:
    """
    Sends Reddit + StockTwits data to Claude for sentiment scoring.
    """
    if not reddit and not stocktwits:
        return _neutral_social(symbol)

    try:
        # Format Reddit posts
        reddit_text = ""
        if reddit:
            reddit_text = "Reddit posts (last 24h):\n"
            for p in reddit:
                reddit_text += f"  [{p['subreddit']}] {p['title']} (score: {p['score']})\n"

        # Format StockTwits — include their own sentiment tags
        twits_text = ""
        if stocktwits:
            bullish_count = sum(1 for m in stocktwits if m.get("sentiment") == "Bullish")
            bearish_count = sum(1 for m in stocktwits if m.get("sentiment") == "Bearish")
            twits_text = (
                f"\nStockTwits messages (recent):\n"
                f"  Tagged Bullish: {bullish_count} | Tagged Bearish: {bearish_count}\n"
            )
            for m in stocktwits[:5]:
                tag = f"[{m['sentiment']}]" if m.get("sentiment") else ""
                twits_text += f"  {tag} {m['body'][:100]}\n"

        prompt = f"""
Asset: {symbol}

{reddit_text}
{twits_text}

Score the overall social media sentiment for trading purposes.
Be conservative — social media is noisy. Only score BULLISH/BEARISH
if there's clear, consistent signal across multiple sources.
""".strip()

        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=SOCIAL_SENTIMENT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result    = json.loads(raw)
        sentiment = result.get("sentiment", "NEUTRAL").upper()
        if sentiment not in SENTIMENT_SCORES:
            sentiment = "NEUTRAL"

        return {
            "sentiment":       sentiment,
            "score":           SENTIMENT_SCORES[sentiment],
            "confidence":      result.get("confidence", "LOW"),
            "reddit_posts":    len(reddit),
            "stocktwits_msgs": len(stocktwits),
            "top_signal":      result.get("top_signal", ""),
            "reasoning":       result.get("reasoning", ""),
        }

    except Exception as e:
        logger.error(f"❌ Social sentiment scoring failed for {symbol}: {e}")
        return _neutral_social(symbol)


# ============================================================
# MASTER FUNCTION
# ============================================================

def get_social_sentiment(symbol: str) -> dict:
    """
    Main entry point — fetches Reddit + StockTwits data
    and scores sentiment in one call.

    Args:
        symbol: e.g. "AAPL", "UBER", "BTC/USD"

    Returns:
        Social sentiment dict ready for scoring engine
    """
    reddit     = fetch_reddit_posts(symbol)
    stocktwits = fetch_stocktwits_messages(symbol)
    return score_social_sentiment(symbol, reddit, stocktwits)


def _neutral_social(symbol: str) -> dict:
    """Returns safe neutral sentiment on error or no data."""
    return {
        "sentiment":       "NEUTRAL",
        "score":           0,
        "confidence":      "LOW",
        "reddit_posts":    0,
        "stocktwits_msgs": 0,
        "top_signal":      "No social data available",
        "reasoning":       "Insufficient social media data — defaulting to neutral",
    }
