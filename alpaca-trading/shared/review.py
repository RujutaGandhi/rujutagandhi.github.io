"""
shared/review.py
================
End-of-day review — fires at 4:05pm ET every trading day.

What it does:
1. Reads today's trade logs for both strategies
2. Sends to Claude with performance data
3. Claude outputs structured JSON adjustments
4. Adjustments saved to state.json via state.py
5. Next morning both strategies wake up with updated parameters

This creates a genuine self-improvement loop:
  Day 1 → trades → review → adjust
  Day 2 → improved trades → review → adjust further
  ...
"""

import json
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional

import anthropic

from shared.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from shared.state import load_state, save_state, apply_adjustments
from shared.alerts import send_email
from shared.config import ALERT_EMAIL_TO, ALERT_EMAIL_FROM

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Log files
CONSERVATIVE_LOG = Path("logs/conservative.log")
AGGRESSIVE_LOG   = Path("logs/aggressive.log")

# ============================================================
# REVIEW SYSTEM PROMPT
# ============================================================

REVIEW_SYSTEM = """
You are a quantitative trading strategist reviewing the daily performance
of an AI trading bot. Your job is to analyze what worked, what didn't,
and output precise parameter adjustments for tomorrow.

Be analytical, not emotional. Focus on patterns, not individual trades.
If the bot made no trades today, analyze why and suggest if thresholds
should be loosened or if the market conditions justified the inactivity.

ALWAYS respond with valid JSON only — no other text, no markdown fences.

Output this exact structure:
{
  "performance_summary": "2-3 sentence summary of today",
  "what_worked": "what signal patterns produced good outcomes",
  "what_failed": "what led to losses or missed opportunities",
  "conservative_adjustments": {
    "rsi_buy_threshold": <int 20-40>,
    "rsi_sell_threshold": <int 60-80>,
    "volume_multiplier": <float 1.0-2.0>,
    "atr_stop_multiplier": <float 1.0-4.0>,
    "strategy_mode": "TREND" | "RANGE" | "BOTH",
    "score_threshold": <int 3-9>,
    "notes": "one sentence on what to watch tomorrow"
  },
  "aggressive_adjustments": {
    "rsi_buy_threshold": <int 20-40>,
    "rsi_sell_threshold": <int 60-80>,
    "volume_multiplier": <float 1.0-2.0>,
    "atr_stop_multiplier": <float 1.0-4.0>,
    "strategy_mode": "TREND" | "RANGE" | "BOTH",
    "score_threshold": <int 3-9>,
    "notes": "one sentence on what to watch tomorrow"
  }
}

Rules for adjustments:
- Only change thresholds if there's clear evidence they need changing
- Don't overreact to a single bad trade — look for patterns
- If no trades today, consider loosening score_threshold by 1 point max
- If multiple stop-losses hit, consider tightening atr_stop_multiplier
- Never suggest the same value as current if no change is needed — just keep it
"""


# ============================================================
# LOG READER
# ============================================================

def read_todays_trades(log_file: Path) -> list[dict]:
    """
    Reads today's trade decisions from a strategy log file.
    Returns only entries from today.
    """
    if not log_file.exists():
        return []

    today  = date.today().isoformat()
    trades = []

    try:
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("timestamp", "")[:10] == today:
                        trades.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"❌ Failed to read log {log_file}: {e}")

    return trades


# ============================================================
# REVIEW PROMPT BUILDER
# ============================================================

def build_review_prompt(
    con_trades:   list[dict],
    agg_trades:   list[dict],
    con_settings: dict,
    agg_settings: dict,
    con_value:    float,
    agg_value:    float,
) -> str:
    """Builds the daily review prompt with today's full trading data."""

    today = date.today().isoformat()

    def summarize_trades(trades: list[dict]) -> str:
        if not trades:
            return "No trades executed today."

        buys   = [t for t in trades if t.get("action") == "BUY"]
        sells  = [t for t in trades if t.get("action") == "SELL"]
        holds  = [t for t in trades if t.get("action") == "HOLD"]
        stops  = [t for t in trades if t.get("action") in ("STOP_ALL", "STOP_TODAY")]

        lines = [
            f"Total decisions: {len(trades)}",
            f"BUYs: {len(buys)} | SELLs: {len(sells)} | HOLDs: {len(holds)} | STOPs: {len(stops)}",
        ]

        for t in trades[-10:]:  # Last 10 decisions
            lines.append(
                f"  [{t.get('timestamp', '')[:16]}] "
                f"{t.get('action', '?')} {t.get('symbol', '?')} — "
                f"Regime: {t.get('regime', '?')} | "
                f"Confidence: {t.get('confidence', '?')} | "
                f"{t.get('reason', '')[:80]}"
            )

        return "\n".join(lines)

    return f"""
DAILY TRADING REVIEW — {today}

═══════════════════════════════════════
CONSERVATIVE STRATEGY
═══════════════════════════════════════
Portfolio value: ${con_value:,.2f} (started at $1,000.00)
P&L: ${con_value - 1000:+,.2f} ({(con_value - 1000) / 1000 * 100:+.2f}%)

Current settings:
  RSI buy/sell:      {con_settings.get('rsi_buy_threshold')}/{con_settings.get('rsi_sell_threshold')}
  Volume multiplier: {con_settings.get('volume_multiplier')}x
  ATR stop:          {con_settings.get('atr_stop_multiplier')}x
  Strategy mode:     {con_settings.get('strategy_mode')}
  Score threshold:   {con_settings.get('score_threshold')} pts

Today's activity:
{summarize_trades(con_trades)}

═══════════════════════════════════════
AGGRESSIVE STRATEGY
═══════════════════════════════════════
Portfolio value: ${agg_value:,.2f} (started at $1,000.00)
P&L: ${agg_value - 1000:+,.2f} ({(agg_value - 1000) / 1000 * 100:+.2f}%)

Current settings:
  RSI buy/sell:      {agg_settings.get('rsi_buy_threshold')}/{agg_settings.get('rsi_sell_threshold')}
  Volume multiplier: {agg_settings.get('volume_multiplier')}x
  ATR stop:          {agg_settings.get('atr_stop_multiplier')}x
  Strategy mode:     {agg_settings.get('strategy_mode')}
  Score threshold:   {agg_settings.get('score_threshold')} pts

Today's activity:
{summarize_trades(agg_trades)}

═══════════════════════════════════════
Analyze both strategies and output JSON adjustments for tomorrow.
Focus on patterns across the day, not individual trades.
""".strip()


# ============================================================
# CLAUDE REVIEW
# ============================================================

def get_claude_review(prompt: str) -> Optional[dict]:
    """Sends the daily review to Claude and parses the JSON response."""
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=REVIEW_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.error(f"❌ Review JSON parse error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Claude review error: {e}")
        return None


# ============================================================
# EMAIL SUMMARY
# ============================================================

def send_review_email(review: dict, con_value: float, agg_value: float):
    """Sends a daily summary email with Claude's review and adjustments."""
    today   = date.today().isoformat()
    subject = f"📊 Daily Trading Review — {today}"

    con_adj = review.get("conservative_adjustments", {})
    agg_adj = review.get("aggressive_adjustments", {})

    body = f"""
Daily Trading Bot Review — {today}

PERFORMANCE
──────────────────────────────────
Conservative: ${con_value:,.2f} ({(con_value - 1000) / 1000 * 100:+.2f}%)
Aggressive:   ${agg_value:,.2f} ({(agg_value - 1000) / 1000 * 100:+.2f}%)
Combined:     ${con_value + agg_value:,.2f} ({(con_value + agg_value - 2000) / 2000 * 100:+.2f}%)

CLAUDE'S ANALYSIS
──────────────────────────────────
{review.get('performance_summary', 'No summary available')}

What worked: {review.get('what_worked', 'N/A')}
What failed: {review.get('what_failed', 'N/A')}

TOMORROW'S ADJUSTMENTS
──────────────────────────────────
Conservative:
  Score threshold:   {con_adj.get('score_threshold', 'unchanged')}
  RSI buy/sell:      {con_adj.get('rsi_buy_threshold', 'unchanged')}/{con_adj.get('rsi_sell_threshold', 'unchanged')}
  ATR stop:          {con_adj.get('atr_stop_multiplier', 'unchanged')}x
  Strategy mode:     {con_adj.get('strategy_mode', 'unchanged')}
  Note: {con_adj.get('notes', '')}

Aggressive:
  Score threshold:   {agg_adj.get('score_threshold', 'unchanged')}
  RSI buy/sell:      {agg_adj.get('rsi_buy_threshold', 'unchanged')}/{agg_adj.get('rsi_sell_threshold', 'unchanged')}
  ATR stop:          {agg_adj.get('atr_stop_multiplier', 'unchanged')}x
  Strategy mode:     {agg_adj.get('strategy_mode', 'unchanged')}
  Note: {agg_adj.get('notes', '')}
    """.strip()

    send_email(subject, body)


# ============================================================
# MASTER REVIEW RUNNER
# ============================================================

def run_daily_review(con_alpaca, agg_alpaca):
    """
    Main entry point — called by main.py at 4:05pm ET.

    Args:
        con_alpaca: Conservative AlpacaClient instance
        agg_alpaca: Aggressive AlpacaClient instance
    """
    logger.info("📊 Starting end-of-day review...")

    try:
        # Read today's trades
        con_trades = read_todays_trades(CONSERVATIVE_LOG)
        agg_trades = read_todays_trades(AGGRESSIVE_LOG)

        logger.info(
            f"Review: {len(con_trades)} conservative decisions, "
            f"{len(agg_trades)} aggressive decisions today"
        )

        # Get current portfolio values
        con_value = con_alpaca.get_portfolio_value()
        agg_value = agg_alpaca.get_portfolio_value()

        # Load current settings
        state        = load_state()
        con_settings = state.get("conservative", {})
        agg_settings = state.get("aggressive", {})

        # Build and send review prompt to Claude
        prompt = build_review_prompt(
            con_trades=con_trades,
            agg_trades=agg_trades,
            con_settings=con_settings,
            agg_settings=agg_settings,
            con_value=con_value,
            agg_value=agg_value,
        )

        review = get_claude_review(prompt)

        if not review:
            logger.error("❌ Review failed — keeping current settings")
            return

        # Apply adjustments with safety bounds
        state = apply_adjustments(
            state, "conservative",
            review.get("conservative_adjustments", {})
        )
        state = apply_adjustments(
            state, "aggressive",
            review.get("aggressive_adjustments", {})
        )

        # Save updated state
        save_state(state)

        # Send email summary
        send_review_email(review, con_value, agg_value)

        logger.info("✅ Daily review complete — adjustments saved for tomorrow")

    except Exception as e:
        logger.error(f"❌ Daily review failed: {e}", exc_info=True)
