"""
conservative/strategy.py
========================
Conservative strategy — disciplined, trend-following.

Rules:
- Trades large cap stocks + BTC/ETH only
- Requires 3 of 5 indicators to agree
- Only trades in TREND regime
- Max 3 open positions
- Max 5% position size (2% for crypto)
- Daily stop: 15% loss
- Kill switch: portfolio < $700
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List

import anthropic

from shared.config import CONSERVATIVE, INDICATORS, CLAUDE_MODEL, CLAUDE_MAX_TOKENS, ANTHROPIC_API_KEY
from shared.alpaca_client import AlpacaClient
from shared.indicators import compute_all, get_latest_signals
from shared.regime_filter import detect_regime, is_regime_match, regime_summary
from shared.alerts import alert_trade_executed

from shared.news import get_news_sentiment
from shared.earnings import check_earnings_veto
from shared.fear_greed import get_fear_greed
from shared.congressional import get_congressional_signal
from shared.scoring import calculate_score, is_trade_eligible, score_summary

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ============================================================
# SYSTEM PROMPT — Conservative persona + hard rules
# ============================================================

SYSTEM_PROMPT = """
You are a former institutional portfolio manager with 20 years of experience
at Bridgewater Associates managing risk-first equity strategies. You have
survived the 2008 crash, the 2020 COVID collapse, and the 2022 crypto winter
by always protecting capital first. You are disciplined, patient, and
methodical. You would rather miss 10 good trades than take 1 bad one.

You are now managing a $1,000 paper trading portfolio of large-cap US stocks and BTC/ETH.
Your core philosophy: capital preservation first, growth second. Every decision
must pass your strict risk filter before execution.

HARD RULES — cannot be overridden under any circumstances:
- If portfolio_value < 700: output STOP_ALL immediately
- If daily_loss_pct > 15: output STOP_TODAY immediately
- Never recommend position_size_pct > 5% for stocks
- Never recommend position_size_pct > 2% for crypto
- Maximum 3 open positions at any time
- No new trades in last 30 minutes of market hours
- If confidence is LOW: output HOLD
- If regime is not TREND: output HOLD
- Require at least 3 of 5 indicators to agree before BUY or SELL

You will receive pre-filtered setups where indicators partially agree.
Your job is final judgment — be strict.

ALWAYS respond in this exact JSON format, nothing else:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00,
  "stop_loss": 0.00,
  "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "MEDIUM" | "HIGH",
  "reason": "max 2 sentences explaining your decision",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR"
}
""".strip()


# ============================================================
# DECISION PROMPT — injected with live data each cycle
# ============================================================

def build_decision_prompt(
    symbol: str,
    signals: dict,
    regime: dict,
    score: dict,
    earnings: dict,
    portfolio_value: float,
    today_open_value: float,
    open_positions: list,
    cash: float,
) -> str:
    """Builds the per-cycle prompt with live market data."""

    daily_pnl      = portfolio_value - today_open_value
    daily_pnl_pct  = (daily_pnl / today_open_value * 100) if today_open_value else 0
    positions_str  = ", ".join(open_positions) if open_positions else "None"

    # Count how many indicators agree on bullish signal
    bullish_signals = 0
    if signals.get("rsi_zone") == "oversold":         bullish_signals += 1
    if signals.get("macd") in ("bullish", "bullish_cross"): bullish_signals += 1
    if signals.get("ema_signal") == "bullish":         bullish_signals += 1
    if signals.get("volume_confirmed"):                bullish_signals += 1
    if regime.get("regime") == "TREND" and signals.get("ema_slope", 0) > 0:
        bullish_signals += 1

    # Count bearish signals
    bearish_signals = 0
    if signals.get("rsi_zone") == "overbought":        bearish_signals += 1
    if signals.get("macd") in ("bearish", "bearish_cross"): bearish_signals += 1
    if signals.get("ema_signal") == "bearish":         bearish_signals += 1
    if signals.get("volume_confirmed") and bearish_signals >= 2: bearish_signals += 1

    return f"""
CONSERVATIVE STRATEGY — DECISION REQUIRED

Portfolio Status:
  Current value:    ${portfolio_value:,.2f}
  Today open value: ${today_open_value:,.2f}
  Daily P&L:        ${daily_pnl:,.2f} ({daily_pnl_pct:.1f}%)
  Cash available:   ${cash:,.2f}
  Open positions:   {positions_str} ({len(open_positions)}/3 max)

Asset: {symbol}
Current price: ${signals.get('price', 0):,.4f}

Technical Signals:
  RSI({INDICATORS['rsi_period']}):    {signals.get('rsi', 'N/A')} → {signals.get('rsi_zone', 'N/A').upper()}
  MACD:          {signals.get('macd', 'N/A').upper()}
  EMA Signal:    {signals.get('ema_signal', 'N/A').upper()} (fast: {signals.get('ema_fast', 'N/A')}, slow: {signals.get('ema_slow', 'N/A')})
  ATR:           {signals.get('atr', 'N/A')} (use for stop sizing: stop = price - 1.5×ATR)
  Volume ratio:  {signals.get('volume_ratio', 'N/A')}x avg → {'CONFIRMED ✓' if signals.get('volume_confirmed') else 'WEAK ✗'}

Signal Agreement:
  Bullish signals: {bullish_signals}/5
  Bearish signals: {bearish_signals}/5
  Required to trade: 3/5 minimum

Market Regime:
  Regime:      {regime.get('regime', 'UNCLEAR')}
  ADX:         {regime.get('adx', 'N/A')}
  Description: {regime.get('description', 'N/A')}

{score.get('scorecard', '')}

Conservative threshold: 6 points minimum to trade.
Current score: {score.get('total_score', 0)} points → {'✅ ELIGIBLE' if score.get('total_score', 0) >= 6 else '❌ BELOW THRESHOLD — output HOLD'}
Earnings veto: {'🚫 YES — ' + earnings.get('veto_reason', '') if earnings.get('veto') else '✅ No earnings veto'}

Make your final judgment. Be strict.
""".strip()


# ============================================================
# CLAUDE DECISION ENGINE
# ============================================================

def get_claude_decision(prompt: str) -> Optional[dict]:
    """
    Sends prompt to Claude, parses JSON response.
    Returns None if Claude fails or returns invalid JSON.
    """
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        decision = json.loads(raw)
        logger.debug(f"Claude decision: {decision}")
        return decision

    except json.JSONDecodeError as e:
        logger.error(f"❌ Claude returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Claude API error: {e}")
        return None


# ============================================================
# MAIN STRATEGY RUNNER
# ============================================================

class ConservativeStrategy:

    def __init__(self, alpaca: AlpacaClient):
        self.alpaca          = alpaca
        self.config          = CONSERVATIVE
        self.today_open_value = None
        self.stopped_today   = False
        self.killed          = False
        self.last_date       = None

    def _reset_daily_state(self):
        """Resets daily tracking at start of each new trading day."""
        today = datetime.now(ET).date()
        if self.last_date != today:
            self.last_date        = today
            self.stopped_today    = False
            self.today_open_value = self.alpaca.get_portfolio_value()
            logger.info(
                f"[Conservative] New day — open value: ${self.today_open_value:,.2f}"
            )

    def run_cycle(self) -> List[dict]:
        """
        Runs one full hourly cycle across all symbols.
        Returns list of decisions made this cycle.
        """
        if self.killed:
            logger.info("[Conservative] Bot killed — skipping cycle.")
            return []

        self._reset_daily_state()

        if self.stopped_today:
            logger.info("[Conservative] Daily stop active — skipping cycle.")
            return []

        portfolio_value = self.alpaca.get_portfolio_value()
        cash            = self.alpaca.get_cash()
        open_positions  = self.alpaca.get_position_symbols()
        decisions       = []

        # Check kill switch first
        if portfolio_value <= self.config["portfolio_floor"]:
            logger.warning(
                f"[Conservative] 🔴 Kill switch: ${portfolio_value:.2f} "
                f"< ${self.config['portfolio_floor']}"
            )
            self.killed = True
            self.alpaca.cancel_all_orders()
            self.alpaca.close_all_positions()
            return [{"action": "STOP_ALL", "reason": "Portfolio below floor"}]

        # Check daily stop
        if self.today_open_value:
            daily_loss_pct = (
                (self.today_open_value - portfolio_value) / self.today_open_value
            )
            if daily_loss_pct >= self.config["daily_stop_pct"]:
                logger.warning(
                    f"[Conservative] 🟡 Daily stop: {daily_loss_pct:.1%} loss today"
                )
                self.stopped_today = True
                return [{"action": "STOP_TODAY", "reason": "Daily loss threshold hit"}]

        # Skip if max positions reached
        if len(open_positions) >= self.config["max_open_positions"]:
            logger.info(
                f"[Conservative] Max positions reached ({len(open_positions)}/3) — skipping."
            )
            return []

        # Scan each symbol
        all_symbols = self.config["stocks"] + self.config["crypto"]

        for symbol in all_symbols:
            # Skip if already holding
            alpaca_symbol = symbol.replace("/", "")
            if alpaca_symbol in open_positions or symbol in open_positions:
                continue

            try:
                # Fetch price history
                df = self.alpaca.get_bars(symbol, lookback_days=30)
                if df.empty:
                    continue

                # Compute indicators
                df = compute_all(df)
                if df.empty:
                    continue

                # Get latest signals
                signals = get_latest_signals(df)
                if not signals:
                    continue

                # Check regime
                regime = regime_summary(df)
                if not is_regime_match(regime["regime"], "conservative"):
                    logger.debug(
                        f"[Conservative] {symbol} — regime mismatch "
                        f"({regime['regime']}), skipping."
                    )
                    continue

                # Build prompt and get Claude's decision
                # Gather all signals
                news          = get_news_sentiment(symbol)
                earnings      = check_earnings_veto(symbol)
                fear_greed    = get_fear_greed()
                congressional = get_congressional_signal(symbol)

                # Calculate weighted score
                score = calculate_score(
                    signals=signals,
                    regime=regime,
                    news=news,
                    fear_greed=fear_greed,
                    congressional=congressional,
                )

                # Check eligibility before calling Claude
                eligible, reason = is_trade_eligible(score, earnings, "conservative")
                logger.info(f"[Conservative] {symbol}: {score_summary(score, eligible, reason)}")

                if not eligible:
                    continue

                # Build prompt and get Claude's decision
                prompt = build_decision_prompt(
                    symbol=symbol,
                    signals=signals,
                    regime=regime,
                    score=score,
                    earnings=earnings,
                    portfolio_value=portfolio_value,
                    today_open_value=self.today_open_value or portfolio_value,
                    open_positions=open_positions,
                    cash=cash,
                )

                decision = get_claude_decision(prompt)
                if not decision:
                    continue

                action = decision.get("action", "HOLD")

                # Execute if BUY
                if action == "BUY" and cash > 10:
                    is_crypto   = "/" in symbol
                    max_pct     = (
                        self.config["crypto_cap_pct"] if is_crypto
                        else self.config["max_position_pct"]
                    )
                    raw_pct = decision.get("position_size_pct", max_pct)
                    # Normalize if Claude returns whole number (e.g. 10 instead of 0.10)
                    if raw_pct > 1:
                        raw_pct = raw_pct / 100
                    position_pct = min(raw_pct, max_pct)
                    price        = signals["price"]
                    atr          = signals["atr"]
                    stop_loss    = price - (self.config["atr_stop_multiplier"] * atr)
                    take_profit  = price + (
                        self.config["take_profit_multiplier"] *
                        (price - stop_loss)
                    )
                    qty = self.alpaca.calculate_qty(
                        symbol, portfolio_value, position_pct, price
                    )

                    if qty > 0:
                        order = self.alpaca.place_limit_order(
                            symbol=symbol,
                            side="buy",
                            qty=qty,
                            limit_price=price * 1.001,  # 0.1% above for fill
                            take_profit=take_profit,
                            stop_loss=stop_loss,
                        )
                        if order:
                            alert_trade_executed(
                                strategy_name="Conservative",
                                action="BUY",
                                symbol=symbol,
                                qty=qty,
                                price=price,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                reason=decision.get("reason", ""),
                            )
                            open_positions.append(symbol)
                            cash -= portfolio_value * position_pct

                decisions.append({
                    "symbol":   symbol,
                    "action":   action,
                    "reason":   decision.get("reason", ""),
                    "regime":   regime["regime"],
                    "confidence": decision.get("confidence", ""),
                })

                logger.info(
                    f"[Conservative] {symbol}: {action} | "
                    f"Regime: {regime['regime']} | "
                    f"Confidence: {decision.get('confidence', '')} | "
                    f"{decision.get('reason', '')}"
                )

            except Exception as e:
                logger.error(f"[Conservative] Error processing {symbol}: {e}")
                continue

        return decisions
