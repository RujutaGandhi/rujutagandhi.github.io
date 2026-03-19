"""
aggressive/strategy.py
======================
Aggressive strategy — momentum-driven, higher risk tolerance.

Rules:
- Trades large cap + small cap stocks + BTC/ETH + altcoins
- Requires only 2 of 5 indicators to agree
- Trades in both TREND and RANGE regimes
- Max 5 open positions
- Max 15% position size (20% for crypto)
- Daily stop: 20% loss
- Kill switch: portfolio < $600
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List

import anthropic

from shared.config import AGGRESSIVE, INDICATORS, CLAUDE_MODEL, CLAUDE_MAX_TOKENS, ANTHROPIC_API_KEY
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
# SYSTEM PROMPT — Aggressive persona + hard rules
# ============================================================

SYSTEM_PROMPT = """
You are a former prop trader at Citadel with 15 years of experience in
momentum and breakout strategies across equities and crypto. You have
a track record of finding asymmetric risk/reward setups early. You are
opportunistic, decisive, and comfortable with volatility. You cut losers
fast and let winners run.

You are now managing a $1,000 paper trading portfolio across large-cap stocks,
small-cap momentum plays, and crypto. Your edge is acting decisively on
emerging signals before they become obvious to the crowd.

HARD RULES — cannot be overridden under any circumstances:
- If portfolio_value < 600: output STOP_ALL immediately
- If daily_loss_pct > 20: output STOP_TODAY immediately
- Never recommend position_size_pct > 15% for stocks
- Never recommend position_size_pct > 20% for crypto
- Maximum 5 open positions at any time
- No new trades in last 30 minutes of market hours
- If confidence is LOW: output HOLD

Unlike the conservative strategy, you can trade in both TREND and RANGE regimes.
In TREND: favor momentum and breakout setups.
In RANGE: favor mean reversion (buy oversold, sell overbought).
You only need 2 of 5 indicators to agree — but size smaller on lower conviction.

ALWAYS respond in this exact JSON format, nothing else:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00,
  "stop_loss": 0.00,
  "take_profit": 0.00,
  "position_size_pct": 0.00,  # decimal form e.g. 0.10 means 10%, never exceed 0.15 for stocks or 0.20 for crypto
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "reason": "max 2 sentences explaining your decision",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR",
  "strategy_type": "momentum" | "mean_reversion" | "breakout" | "hold"
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

    daily_pnl     = portfolio_value - today_open_value
    daily_pnl_pct = (daily_pnl / today_open_value * 100) if today_open_value else 0
    positions_str = ", ".join(open_positions) if open_positions else "None"

    # Signal counts
    bullish_signals = 0
    if signals.get("rsi_zone") == "oversold":              bullish_signals += 1
    if signals.get("macd") in ("bullish", "bullish_cross"): bullish_signals += 1
    if signals.get("ema_signal") == "bullish":              bullish_signals += 1
    if signals.get("volume_confirmed"):                     bullish_signals += 1
    if regime.get("regime") == "TREND":                     bullish_signals += 1

    bearish_signals = 0
    if signals.get("rsi_zone") == "overbought":             bearish_signals += 1
    if signals.get("macd") in ("bearish", "bearish_cross"): bearish_signals += 1
    if signals.get("ema_signal") == "bearish":              bearish_signals += 1
    if signals.get("volume_confirmed") and bearish_signals >= 1: bearish_signals += 1

    # Suggest strategy type based on regime
    if regime.get("regime") == "TREND":
        strategy_hint = "Consider momentum or breakout strategy."
    elif regime.get("regime") == "RANGE":
        strategy_hint = "Consider mean reversion — buy oversold, sell overbought."
    else:
        strategy_hint = "Mixed signals — favor HOLD."

    return f"""
AGGRESSIVE STRATEGY — DECISION REQUIRED

Portfolio Status:
  Current value:    ${portfolio_value:,.2f}
  Today open value: ${today_open_value:,.2f}
  Daily P&L:        ${daily_pnl:,.2f} ({daily_pnl_pct:.1f}%)
  Cash available:   ${cash:,.2f}
  Open positions:   {positions_str} ({len(open_positions)}/5 max)

Asset: {symbol}
Current price: ${signals.get('price', 0):,.4f}

Technical Signals:
  RSI({INDICATORS['rsi_period']}):    {signals.get('rsi', 'N/A')} → {signals.get('rsi_zone', 'N/A').upper()}
  MACD:          {signals.get('macd', 'N/A').upper()}
  EMA Signal:    {signals.get('ema_signal', 'N/A').upper()} (fast: {signals.get('ema_fast', 'N/A')}, slow: {signals.get('ema_slow', 'N/A')})
  ATR:           {signals.get('atr', 'N/A')} (stop sizing: stop = price - 2.5×ATR)
  Volume ratio:  {signals.get('volume_ratio', 'N/A')}x avg → {'CONFIRMED ✓' if signals.get('volume_confirmed') else 'WEAK ✗'}

Signal Agreement:
  Bullish signals: {bullish_signals}/5
  Bearish signals: {bearish_signals}/5
  Required to trade: 2/5 minimum

Market Regime:
  Regime:      {regime.get('regime', 'UNCLEAR')}
  ADX:         {regime.get('adx', 'N/A')}
  Description: {regime.get('description', 'N/A')}

Strategy hint: {strategy_hint}

Size guidance:
  2 signals agree → use 5–8% position size
  3 signals agree → use 8–12% position size
  4+ signals agree → use 12–15% position size (stocks) / up to 20% (crypto)

{score.get('scorecard', '')}

Aggressive threshold: 4 points minimum to trade.
Current score: {score.get('total_score', 0)} points → {'✅ ELIGIBLE' if score.get('total_score', 0) >= 4 else '❌ BELOW THRESHOLD — output HOLD'}
Earnings veto: {'🚫 YES — ' + earnings.get('veto_reason', '') if earnings.get('veto') else '✅ No earnings veto'}

Make your final judgment. Be decisive.
""".strip()


# ============================================================
# CLAUDE DECISION ENGINE
# ============================================================

def get_claude_decision(prompt: str) -> Optional[dict]:
    """Sends prompt to Claude, parses JSON response."""
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        decision = json.loads(raw)
        logger.debug(f"Claude (aggressive) decision: {decision}")
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

class AggressiveStrategy:

    def __init__(self, alpaca: AlpacaClient):
        self.alpaca           = alpaca
        self.config           = AGGRESSIVE
        self.today_open_value = None
        self.stopped_today    = False
        self.killed           = False
        self.last_date        = None

    def _reset_daily_state(self):
        """Resets daily tracking at start of each new trading day."""
        today = datetime.now(ET).date()
        if self.last_date != today:
            self.last_date        = today
            self.stopped_today    = False
            self.today_open_value = self.alpaca.get_portfolio_value()
            logger.info(
                f"[Aggressive] New day — open value: ${self.today_open_value:,.2f}"
            )

    def run_cycle(self) -> List[dict]:
        """
        Runs one full hourly cycle across all symbols.
        Returns list of decisions made this cycle.
        """
        if self.killed:
            logger.info("[Aggressive] Bot killed — skipping cycle.")
            return []

        self._reset_daily_state()

        if self.stopped_today:
            logger.info("[Aggressive] Daily stop active — skipping cycle.")
            return []

        portfolio_value = self.alpaca.get_portfolio_value()
        cash            = self.alpaca.get_cash()
        open_positions  = self.alpaca.get_position_symbols()
        decisions       = []

        # Kill switch check
        if portfolio_value <= self.config["portfolio_floor"]:
            logger.warning(
                f"[Aggressive] 🔴 Kill switch: ${portfolio_value:.2f} "
                f"< ${self.config['portfolio_floor']}"
            )
            self.killed = True
            self.alpaca.cancel_all_orders()
            self.alpaca.close_all_positions()
            return [{"action": "STOP_ALL", "reason": "Portfolio below floor"}]

        # Daily stop check
        if self.today_open_value:
            daily_loss_pct = (
                (self.today_open_value - portfolio_value) / self.today_open_value
            )
            if daily_loss_pct >= self.config["daily_stop_pct"]:
                logger.warning(
                    f"[Aggressive] 🟡 Daily stop: {daily_loss_pct:.1%} loss today"
                )
                self.stopped_today = True
                return [{"action": "STOP_TODAY", "reason": "Daily loss threshold hit"}]

        # Skip if max positions reached
        if len(open_positions) >= self.config["max_open_positions"]:
            logger.info(
                f"[Aggressive] Max positions reached ({len(open_positions)}/5) — skipping."
            )
            return []

        # Scan all symbols
        all_symbols = self.config["stocks"] + self.config["crypto"]

        for symbol in all_symbols:
            alpaca_symbol = symbol.replace("/", "")
            if alpaca_symbol in open_positions or symbol in open_positions:
                continue

            try:
                df = self.alpaca.get_bars(symbol, lookback_days=30)
                if df.empty:
                    continue

                df = compute_all(df)
                if df.empty:
                    continue

                signals = get_latest_signals(df)
                if not signals:
                    continue

                regime = regime_summary(df)

                # Aggressive trades TREND and RANGE — only skip UNCLEAR
                if not is_regime_match(regime["regime"], "aggressive"):
                    logger.debug(
                        f"[Aggressive] {symbol} — regime UNCLEAR, skipping."
                    )
                    continue

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
                eligible, reason = is_trade_eligible(score, earnings, "aggressive")
                logger.info(f"[Aggressive] {symbol}: {score_summary(score, eligible, reason)}")

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

                # Execute BUY
                if action == "BUY" and cash > 10:
                    is_crypto    = "/" in symbol
                    max_pct      = (
                        self.config["crypto_cap_pct"] if is_crypto
                        else self.config["max_position_pct"]
                    )
                   
                    raw_pct = decision.get("position_size_pct", max_pct * 0.5)
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
                            limit_price=price * 1.002,  # 0.2% above for faster fills
                            take_profit=take_profit,
                            stop_loss=stop_loss,
                        )
                        if order:
                            alert_trade_executed(
                                strategy_name="Aggressive",
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
                    "symbol":        symbol,
                    "action":        action,
                    "reason":        decision.get("reason", ""),
                    "regime":        regime["regime"],
                    "confidence":    decision.get("confidence", ""),
                    "strategy_type": decision.get("strategy_type", ""),
                })

                logger.info(
                    f"[Aggressive] {symbol}: {action} | "
                    f"Regime: {regime['regime']} | "
                    f"Type: {decision.get('strategy_type', '')} | "
                    f"Confidence: {decision.get('confidence', '')} | "
                    f"{decision.get('reason', '')}"
                )

            except Exception as e:
                logger.error(f"[Aggressive] Error processing {symbol}: {e}")
                continue

        return decisions
