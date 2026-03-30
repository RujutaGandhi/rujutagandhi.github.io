"""
conservative/strategy.py
========================
Phase 7: Adaptive regime-aware strategy.

Regime modes:
  MOMENTUM       → Active: trend-follow, normal position sizes
  MEAN_REVERSION → Cautious: smaller positions, tighter stops
  DEFENSIVE      → Cash only: no new longs in bear market
  MACRO_EVENT    → Cash only: extreme uncertainty, sit out
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List

from shared.state import save_crypto_position, remove_crypto_position, get_crypto_positions

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
from shared.social_sentiment import get_social_sentiment
from shared.screener import get_screened_symbols, get_crypto_symbols
from shared.macro_regime import get_macro_mode

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ============================================================
# SYSTEM PROMPTS — one per regime mode
# ============================================================

SYSTEM_PROMPTS = {

"MOMENTUM": """
You are a former institutional portfolio manager with 20 years of experience
at Bridgewater Associates managing risk-first equity strategies. You have
survived the 2008 crash, the 2020 COVID collapse, and the 2022 crypto winter
by always protecting capital first.

CURRENT MARKET MODE: MOMENTUM — trending market, low volatility.
In this environment, you are actively looking for strong trend-following setups.
Position sizes are normal. Ride winners, cut losers quickly.

HARD RULES:
- portfolio_value < 700: output STOP_ALL
- daily_loss_pct > 15: output STOP_TODAY
- Never position_size_pct > 5% stocks, > 2% crypto
- Max 3 open positions
- No trades in last 30 min of market hours
- confidence LOW: output HOLD
- regime not TREND: output HOLD
- Require 3 of 5 indicators to agree

ALWAYS respond in this exact JSON format:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00,
  "stop_loss": 0.00,
  "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "MEDIUM" | "HIGH",
  "reason": "max 2 sentences",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR"
}
""".strip(),

"MEAN_REVERSION": """
You are a former institutional portfolio manager at Bridgewater Associates.
Capital preservation is your mandate.

CURRENT MARKET MODE: MEAN_REVERSION — choppy, range-bound market.
You are cautious. Only take setups where RSI is deeply oversold (<25) and price
is near clear support. Size positions at 60% of normal. Tighter stops than usual.

HARD RULES:
- portfolio_value < 700: output STOP_ALL
- daily_loss_pct > 15: output STOP_TODAY
- Never position_size_pct > 3% stocks (reduced from 5% due to market conditions)
- Max 2 open positions (reduced from 3)
- confidence LOW or MEDIUM: output HOLD (only HIGH conviction in choppy markets)
- Require 4 of 5 indicators to agree (stricter than normal)

ALWAYS respond in this exact JSON format:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00,
  "stop_loss": 0.00,
  "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "MEDIUM" | "HIGH",
  "reason": "max 2 sentences",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR"
}
""".strip(),

}

# Conservative holds cash entirely in DEFENSIVE and MACRO_EVENT —
# Claude is NOT called in those modes. The strategy just returns HOLD.


# ============================================================
# DECISION PROMPT
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
    macro_mode: str,
) -> str:
    daily_pnl     = portfolio_value - today_open_value
    daily_pnl_pct = (daily_pnl / today_open_value * 100) if today_open_value else 0
    positions_str = ", ".join(open_positions) if open_positions else "None"

    # Max positions depends on regime
    max_pos = 3 if macro_mode == "MOMENTUM" else 2

    bullish_signals = 0
    if signals.get("rsi_zone") == "oversold":              bullish_signals += 1
    if signals.get("macd") in ("bullish", "bullish_cross"): bullish_signals += 1
    if signals.get("ema_signal") == "bullish":              bullish_signals += 1
    if signals.get("volume_confirmed"):                     bullish_signals += 1
    if regime.get("regime") == "TREND" and signals.get("ema_slope", 0) > 0:
        bullish_signals += 1

    required = 3 if macro_mode == "MOMENTUM" else 4

    return f"""
CONSERVATIVE STRATEGY — {macro_mode} MODE — DECISION REQUIRED

Portfolio Status:
  Current value:    ${portfolio_value:,.2f}
  Today open value: ${today_open_value:,.2f}
  Daily P&L:        ${daily_pnl:,.2f} ({daily_pnl_pct:.1f}%)
  Cash available:   ${cash:,.2f}
  Open positions:   {positions_str} ({len(open_positions)}/{max_pos} max)

Market Mode: {macro_mode}

Asset: {symbol}
Current price: ${signals.get('price', 0):,.4f}

Technical Signals:
  RSI({INDICATORS['rsi_period']}):    {signals.get('rsi', 'N/A')} → {signals.get('rsi_zone', 'N/A').upper()}
  MACD:          {signals.get('macd', 'N/A').upper()}
  EMA Signal:    {signals.get('ema_signal', 'N/A').upper()}
  ATR:           {signals.get('atr', 'N/A')}
  Volume ratio:  {signals.get('volume_ratio', 'N/A')}x avg → {'CONFIRMED ✓' if signals.get('volume_confirmed') else 'WEAK ✗'}

Bullish signals: {bullish_signals}/5 (need {required} to trade in {macro_mode} mode)

Market Regime (asset-level):
  Regime: {regime.get('regime', 'UNCLEAR')} | ADX: {regime.get('adx', 'N/A')}

{score.get('scorecard', '')}

Score: {score.get('total_score', 0)} points → {'✅ ELIGIBLE' if score.get('total_score', 0) >= 6 else '❌ BELOW THRESHOLD'}
Earnings veto: {'🚫 YES' if earnings.get('veto') else '✅ No'}

Make your final judgment. Capital preservation first.
""".strip()


# ============================================================
# CLAUDE DECISION ENGINE
# ============================================================

def get_claude_decision(prompt: str, macro_mode: str) -> Optional[dict]:
    system = SYSTEM_PROMPTS.get(macro_mode, SYSTEM_PROMPTS["MOMENTUM"])
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Claude returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Claude API error: {e}")
        return None


# ============================================================
# MAIN STRATEGY
# ============================================================

class ConservativeStrategy:

    def __init__(self, alpaca: AlpacaClient):
        self.alpaca           = alpaca
        self.config           = CONSERVATIVE
        self.today_open_value = None
        self.stopped_today    = False
        self.killed           = False
        self.last_date        = None

    def _reset_daily_state(self):
        today = datetime.now(ET).date()
        if self.last_date != today:
            self.last_date        = today
            self.stopped_today    = False
            self.today_open_value = self.alpaca.get_portfolio_value()
            logger.info(f"[Conservative] New day — open: ${self.today_open_value:,.2f}")

    def _check_crypto_stops(self):
        positions = get_crypto_positions()
        if not positions:
            return
        for symbol, pos in list(positions.items()):
            if pos.get("strategy") != "Conservative":
                continue
            try:
                current_price = self.alpaca.get_crypto_price(symbol)
                if not current_price:
                    continue
                if current_price <= pos["stop_price"]:
                    logger.warning(
                        f"[Conservative] 🛑 Crypto stop: {symbol} "
                        f"${current_price:,.2f} <= ${pos['stop_price']:,.2f}"
                    )
                    self.alpaca.place_crypto_stop_sell(symbol, pos["qty"])
                    remove_crypto_position(symbol)
            except Exception as e:
                logger.error(f"[Conservative] Crypto stop error {symbol}: {e}")

    def run_cycle(self) -> List[dict]:
        if self.killed:
            logger.info("[Conservative] Bot killed — skipping.")
            return []

        self._reset_daily_state()

        if self.stopped_today:
            logger.info("[Conservative] Daily stop active — skipping.")
            return []

        self._check_crypto_stops()

        # ── MACRO REGIME CHECK ──────────────────────────────
        macro = get_macro_mode()
        macro_mode = macro["mode"]

        logger.info(
            f"[Conservative] 🌍 Macro mode: {macro_mode} | "
            f"VIX: {macro['vix']:.1f} ({macro['vix_level']}) | "
            f"SPY {'above' if macro['above_200ma'] else 'below'} 200MA"
        )

        # DEFENSIVE or MACRO_EVENT → hold cash, no new longs
        if macro_mode in ("DEFENSIVE", "MACRO_EVENT"):
            logger.info(
                f"[Conservative] 🛡️  {macro_mode} mode — holding cash. "
                f"No new longs in current market conditions."
            )
            return [{
                "action":     "HOLD",
                "symbol":     None,
                "reason":     f"{macro_mode} mode: {macro['description']}",
                "regime":     macro_mode,
                "confidence": "N/A",
                "macro_mode": macro_mode,
            }]

        # Size multiplier for this regime
        size_mult = self.config["regime_size_multiplier"].get(macro_mode, 1.0)

        portfolio_value = self.alpaca.get_portfolio_value()
        cash            = self.alpaca.get_cash()
        open_positions  = self.alpaca.get_position_symbols()
        decisions       = []

        # Kill switch
        if portfolio_value <= self.config["portfolio_floor"]:
            logger.warning(f"[Conservative] 🔴 Kill switch: ${portfolio_value:.2f}")
            self.killed = True
            self.alpaca.cancel_all_orders()
            self.alpaca.close_all_positions()
            return [{"action": "STOP_ALL", "reason": "Portfolio below floor"}]

        # Daily stop
        if self.today_open_value:
            daily_loss_pct = (self.today_open_value - portfolio_value) / self.today_open_value
            if daily_loss_pct >= self.config["daily_stop_pct"]:
                logger.warning(f"[Conservative] 🟡 Daily stop: {daily_loss_pct:.1%}")
                self.stopped_today = True
                return [{"action": "STOP_TODAY", "reason": "Daily loss threshold hit"}]

        max_pos = 3 if macro_mode == "MOMENTUM" else 2
        if len(open_positions) >= max_pos:
            logger.info(f"[Conservative] Max positions ({len(open_positions)}/{max_pos}) — skipping.")
            return []

        # Dynamic symbol list from screener
        stock_symbols  = get_screened_symbols("conservative")
        crypto_symbols = get_crypto_symbols("conservative")
        all_symbols    = stock_symbols + crypto_symbols

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
                if not is_regime_match(regime["regime"], "conservative"):
                    continue

                news          = get_news_sentiment(symbol)
                earnings      = check_earnings_veto(symbol)
                fear_greed    = get_fear_greed()
                congressional = get_congressional_signal(symbol)
                social        = get_social_sentiment(symbol)

                score = calculate_score(
                    signals=signals, regime=regime, news=news,
                    fear_greed=fear_greed, congressional=congressional,
                    social_sentiment=social,
                )

                eligible, reason = is_trade_eligible(score, earnings, "conservative")
                logger.info(f"[Conservative] {symbol}: {score_summary(score, eligible, reason)}")

                if not eligible:
                    continue

                prompt = build_decision_prompt(
                    symbol=symbol, signals=signals, regime=regime,
                    score=score, earnings=earnings,
                    portfolio_value=portfolio_value,
                    today_open_value=self.today_open_value or portfolio_value,
                    open_positions=open_positions, cash=cash,
                    macro_mode=macro_mode,
                )

                decision = get_claude_decision(prompt, macro_mode)
                if not decision:
                    continue

                action = decision.get("action", "HOLD")

                if action == "BUY" and cash > 10:
                    is_crypto = "/" in symbol
                    max_pct   = (
                        self.config["crypto_cap_pct"] if is_crypto
                        else self.config["max_position_pct"]
                    )
                    raw_pct = decision.get("position_size_pct", max_pct)
                    if raw_pct > 1:
                        raw_pct = raw_pct / 100
                    # Apply regime size multiplier
                    position_pct = min(raw_pct, max_pct) * size_mult
                    price        = signals["price"]
                    atr          = signals["atr"]
                    stop_loss    = price - (self.config["atr_stop_multiplier"] * atr)
                    take_profit  = price + (self.config["take_profit_multiplier"] * (price - stop_loss))
                    qty          = self.alpaca.calculate_qty(symbol, portfolio_value, position_pct, price)

                    if qty > 0:
                        order = self.alpaca.place_limit_order(
                            symbol=symbol, side="buy", qty=qty,
                            limit_price=price * 1.001,
                            take_profit=take_profit, stop_loss=stop_loss,
                        )
                        if order:
                            if self.alpaca.is_crypto(symbol):
                                save_crypto_position(
                                    symbol=symbol, entry_price=price,
                                    stop_price=stop_loss, qty=qty,
                                    strategy="Conservative",
                                )
                            alert_trade_executed(
                                strategy_name="Conservative", action="BUY",
                                symbol=symbol, qty=qty, price=price,
                                stop_loss=stop_loss, take_profit=take_profit,
                                reason=decision.get("reason", ""),
                            )
                            open_positions.append(symbol)
                            cash -= portfolio_value * position_pct

                decisions.append({
                    "symbol":     symbol,
                    "action":     action,
                    "reason":     decision.get("reason", ""),
                    "regime":     regime["regime"],
                    "confidence": decision.get("confidence", ""),
                    "macro_mode": macro_mode,
                })

                logger.info(
                    f"[Conservative] {symbol}: {action} | "
                    f"Mode: {macro_mode} | Regime: {regime['regime']} | "
                    f"Confidence: {decision.get('confidence', '')} | "
                    f"{decision.get('reason', '')}"
                )

            except Exception as e:
                logger.error(f"[Conservative] Error {symbol}: {e}")
                continue

        return decisions
