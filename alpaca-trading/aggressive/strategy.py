"""
aggressive/strategy.py
======================
Phase 7: Adaptive regime-aware strategy + ETF short selling.

Regime modes:
  MOMENTUM       → Long momentum plays, larger positions
  MEAN_REVERSION → Mean reversion plays, smaller positions
  DEFENSIVE      → SHORT SPY/QQQ only (no new longs)
  MACRO_EVENT    → 50% reduced positions, selective longs only
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
from shared.state import save_crypto_position, remove_crypto_position, get_crypto_positions
from shared.macro_regime import get_macro_mode
from shared.risk_guardian import check_short_stops
from shared.social_sentiment import get_social_sentiment
from shared.screener import get_screened_symbols, get_crypto_symbols

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ============================================================
# SYSTEM PROMPTS — one per regime mode
# ============================================================

SYSTEM_PROMPTS = {

"MOMENTUM": """
You are a former prop trader at Citadel with 15 years of experience.
Momentum and breakout strategies are your edge.

CURRENT MARKET MODE: MOMENTUM — trending market, low volatility.
Go long on the strongest momentum plays. Larger position sizes are acceptable.
You only need 2 of 5 indicators to agree.

HARD RULES:
- portfolio_value < 600: STOP_ALL
- daily_loss_pct > 20: STOP_TODAY
- Never position_size_pct > 15% stocks, > 20% crypto
- Max 5 open positions
- confidence LOW: HOLD

ALWAYS respond in this exact JSON:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00, "stop_loss": 0.00, "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "reason": "max 2 sentences",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR",
  "strategy_type": "momentum" | "mean_reversion" | "breakout" | "hold"
}
""".strip(),

"MEAN_REVERSION": """
You are a former prop trader at Citadel. In range-bound markets you excel
at mean reversion — buying oversold, selling overbought.

CURRENT MARKET MODE: MEAN_REVERSION — choppy, sideways market.
Only take setups where RSI < 28 (deeply oversold) near clear support.
Size at 70% of normal. Quick exits — don't hold reversions long.

HARD RULES:
- portfolio_value < 600: STOP_ALL
- daily_loss_pct > 20: STOP_TODAY
- Never position_size_pct > 10% (reduced from 15%)
- Max 3 open positions (reduced from 5)
- confidence LOW or MEDIUM: HOLD

ALWAYS respond in this exact JSON:
{
  "action": "BUY" | "SELL" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00, "stop_loss": 0.00, "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "reason": "max 2 sentences",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR",
  "strategy_type": "momentum" | "mean_reversion" | "breakout" | "hold"
}
""".strip(),

"DEFENSIVE": """
You are a former prop trader at Citadel. In bear markets you profit from
shorting indices and holding defensive assets.

CURRENT MARKET MODE: DEFENSIVE — bear market, high VIX, S&P below 200MA.
You are evaluating whether to SHORT SPY or QQQ. Only short if bearish signals
are strong and consistent. The short will be a market order — you manage stops.

HARD RULES:
- portfolio_value < 600: STOP_ALL
- Only output SHORT or HOLD — no BUY in defensive mode
- If confidence is LOW or MEDIUM: output HOLD
- Need 3+ bearish signals to short

ALWAYS respond in this exact JSON:
{
  "action": "SHORT" | "HOLD" | "STOP_ALL",
  "ticker": "SPY" | "QQQ" | null,
  "entry_price": 0.00,
  "position_size_pct": 0.00,
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "reason": "max 2 sentences explaining why shorting or holding",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR"
}
""".strip(),

"MACRO_EVENT": """
You are a former prop trader at Citadel. During macro events (VIX spike,
geopolitical shock) you reduce exposure significantly and wait for clarity.

CURRENT MARKET MODE: MACRO_EVENT — extreme uncertainty, VIX spiking.
Be very selective. Only the highest conviction setups. Size at 50% of normal.
When in doubt, HOLD.

HARD RULES:
- portfolio_value < 600: STOP_ALL
- daily_loss_pct > 20: STOP_TODAY
- Never position_size_pct > 7% (50% of normal max)
- Max 2 open positions
- confidence below HIGH: HOLD

ALWAYS respond in this exact JSON:
{
  "action": "BUY" | "HOLD" | "STOP_ALL" | "STOP_TODAY",
  "ticker": "SYMBOL or null",
  "entry_price": 0.00, "stop_loss": 0.00, "take_profit": 0.00,
  "position_size_pct": 0.00,
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "reason": "max 2 sentences",
  "indicators_agreed": 0,
  "regime": "TREND" | "RANGE" | "UNCLEAR",
  "strategy_type": "momentum" | "mean_reversion" | "breakout" | "hold"
}
""".strip(),

}


# ============================================================
# DECISION PROMPT — LONG SETUPS
# ============================================================

def build_decision_prompt(symbol, signals, regime, score, earnings,
                          portfolio_value, today_open_value,
                          open_positions, cash, macro_mode) -> str:
    daily_pnl     = portfolio_value - today_open_value
    daily_pnl_pct = (daily_pnl / today_open_value * 100) if today_open_value else 0
    positions_str = ", ".join(open_positions) if open_positions else "None"

    max_pos = {"MOMENTUM": 5, "MEAN_REVERSION": 3, "MACRO_EVENT": 2}.get(macro_mode, 5)

    bullish_signals = 0
    if signals.get("rsi_zone") == "oversold":               bullish_signals += 1
    if signals.get("macd") in ("bullish", "bullish_cross"):  bullish_signals += 1
    if signals.get("ema_signal") == "bullish":               bullish_signals += 1
    if signals.get("volume_confirmed"):                      bullish_signals += 1
    if regime.get("regime") == "TREND":                      bullish_signals += 1

    bearish_signals = 0
    if signals.get("rsi_zone") == "overbought":              bearish_signals += 1
    if signals.get("macd") in ("bearish", "bearish_cross"):  bearish_signals += 1
    if signals.get("ema_signal") == "bearish":               bearish_signals += 1
    if signals.get("volume_confirmed") and bearish_signals >= 1: bearish_signals += 1

    regime_hints = {
        "MOMENTUM":       "Favor momentum and breakout setups.",
        "MEAN_REVERSION": "Favor mean reversion — buy deeply oversold only.",
        "MACRO_EVENT":    "Extreme caution — only highest conviction setups.",
    }

    return f"""
AGGRESSIVE STRATEGY — {macro_mode} MODE

Portfolio: ${portfolio_value:,.2f} | Cash: ${cash:,.2f}
Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:.1f}%)
Positions: {positions_str} ({len(open_positions)}/{max_pos} max)

Asset: {symbol} @ ${signals.get('price', 0):,.4f}
RSI: {signals.get('rsi', 'N/A')} ({signals.get('rsi_zone', 'N/A').upper()})
MACD: {signals.get('macd', 'N/A').upper()} | EMA: {signals.get('ema_signal', 'N/A').upper()}
Volume: {signals.get('volume_ratio', 'N/A')}x | ATR: {signals.get('atr', 'N/A')}

Bullish: {bullish_signals}/5 | Bearish: {bearish_signals}/5
Regime: {regime.get('regime')} | ADX: {regime.get('adx', 'N/A')}

{score.get('scorecard', '')}

Score: {score.get('total_score', 0)} | Earnings veto: {'YES' if earnings.get('veto') else 'No'}
Mode hint: {regime_hints.get(macro_mode, '')}

Make your decision.
""".strip()


def build_short_prompt(symbol, signals, regime, portfolio_value,
                       today_open_value, cash, open_positions,
                       short_exposure_pct) -> str:
    """Prompt for SHORT decisions in DEFENSIVE mode."""
    daily_pnl = portfolio_value - today_open_value
    daily_pnl_pct = (daily_pnl / today_open_value * 100) if today_open_value else 0

    bearish_signals = 0
    if signals.get("rsi_zone") == "overbought":              bearish_signals += 1
    if signals.get("macd") in ("bearish", "bearish_cross"):  bearish_signals += 1
    if signals.get("ema_signal") == "bearish":               bearish_signals += 1
    if signals.get("volume_confirmed") and bearish_signals >= 1: bearish_signals += 1

    return f"""
AGGRESSIVE STRATEGY — DEFENSIVE MODE — SHORT EVALUATION

Portfolio: ${portfolio_value:,.2f} | Cash: ${cash:,.2f}
Daily P&L: ${daily_pnl:,.2f} ({daily_pnl_pct:.1f}%)
Current short exposure: {short_exposure_pct:.1%} (max 30%)
Open positions: {len(open_positions)}

Evaluating SHORT on: {symbol} (ETF — index short, not single stock)
Current price: ${signals.get('price', 0):,.4f}

Bearish signals: {bearish_signals}/4
RSI: {signals.get('rsi', 'N/A')} ({signals.get('rsi_zone', 'N/A').upper()})
MACD: {signals.get('macd', 'N/A').upper()} | EMA: {signals.get('ema_signal', 'N/A').upper()}
Volume: {signals.get('volume_ratio', 'N/A')}x | ATR: {signals.get('atr', 'N/A')}
Regime: {regime.get('regime')} | ADX: {regime.get('adx', 'N/A')}

Market context: High VIX, S&P below 200-day MA, bear market conditions.

Should we SHORT {symbol} now? Need HIGH confidence and 3+ bearish signals.
""".strip()


# ============================================================
# CLAUDE DECISION ENGINE
# ============================================================

def get_claude_decision(prompt: str, macro_mode: str) -> Optional[dict]:
    system = SYSTEM_PROMPTS.get(macro_mode, SYSTEM_PROMPTS["MOMENTUM"])
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=CLAUDE_MAX_TOKENS,
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
        logger.error(f"❌ Claude invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Claude API error: {e}")
        return None


# ============================================================
# MAIN STRATEGY
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
        today = datetime.now(ET).date()
        if self.last_date != today:
            self.last_date        = today
            self.stopped_today    = False
            self.today_open_value = self.alpaca.get_portfolio_value()
            logger.info(f"[Aggressive] New day — open: ${self.today_open_value:,.2f}")

    def _check_crypto_stops(self):
        positions = get_crypto_positions()
        if not positions:
            return
        for symbol, pos in list(positions.items()):
            if pos.get("strategy") != "Aggressive":
                continue
            try:
                current_price = self.alpaca.get_crypto_price(symbol)
                if not current_price:
                    continue
                if current_price <= pos["stop_price"]:
                    logger.warning(
                        f"[Aggressive] 🛑 Crypto stop: {symbol} "
                        f"${current_price:,.2f} <= ${pos['stop_price']:,.2f}"
                    )
                    self.alpaca.place_crypto_stop_sell(symbol, pos["qty"])
                    remove_crypto_position(symbol)
            except Exception as e:
                logger.error(f"[Aggressive] Crypto stop error {symbol}: {e}")

    def _run_defensive_mode(self, macro: dict) -> List[dict]:
        """
        DEFENSIVE mode: evaluate SPY and QQQ as short candidates.
        ETF shorts only — no single stocks.
        Hard stops managed by risk_guardian.check_short_stops().
        """
        decisions       = []
        portfolio_value = self.alpaca.get_portfolio_value()
        cash            = self.alpaca.get_cash()
        open_positions  = self.alpaca.get_position_symbols()

        # Check and close any short positions hitting stops first
        covered = check_short_stops(self.alpaca, self.config)
        for sym in covered:
            logger.info(f"[Aggressive] Short stop triggered — covered {sym}")
            decisions.append({
                "action": "COVER_SHORT", "symbol": sym,
                "reason": "Short stop loss triggered", "regime": "DEFENSIVE",
                "confidence": "N/A", "macro_mode": "DEFENSIVE",
            })

        # Current short exposure
        short_exposure      = self.alpaca.get_total_short_exposure()
        max_short_exposure  = portfolio_value * self.config["max_short_exposure_pct"]

        if short_exposure >= max_short_exposure:
            logger.info(
                f"[Aggressive] Max short exposure reached "
                f"(${short_exposure:,.2f} / ${max_short_exposure:,.2f})"
            )
            return decisions

        # Evaluate short candidates (SPY and QQQ only)
        for symbol in self.config["short_symbols"]:
            if symbol in open_positions:
                continue  # Already have a position (long or short)

            try:
                df = self.alpaca.get_bars(symbol, lookback_days=30)
                if df.empty:
                    continue

                df      = compute_all(df)
                signals = get_latest_signals(df)
                regime  = regime_summary(df)

                if not signals:
                    continue

                prompt   = build_short_prompt(
                    symbol=symbol, signals=signals, regime=regime,
                    portfolio_value=portfolio_value,
                    today_open_value=self.today_open_value or portfolio_value,
                    cash=cash, open_positions=open_positions,
                    short_exposure_pct=short_exposure / portfolio_value if portfolio_value else 0,
                )
                decision = get_claude_decision(prompt, "DEFENSIVE")

                if not decision:
                    continue

                action = decision.get("action", "HOLD")

                if action == "SHORT" and decision.get("confidence") == "HIGH":
                    raw_pct      = decision.get("position_size_pct", 0.10)
                    if raw_pct > 1:
                        raw_pct = raw_pct / 100
                    position_pct = min(raw_pct, self.config["max_short_exposure_pct"])
                    price        = signals["price"]
                    qty          = self.alpaca.calculate_qty(
                        symbol, portfolio_value, position_pct, price
                    )

                    if qty > 0:
                        order = self.alpaca.place_short_order(symbol, qty)
                        if order:
                            logger.info(
                                f"[Aggressive] 📉 SHORT opened: {qty} {symbol} "
                                f"@ ${price:.2f} | {decision.get('reason', '')}"
                            )
                            alert_trade_executed(
                                strategy_name="Aggressive",
                                action="SHORT",
                                symbol=symbol, qty=qty, price=price,
                                stop_loss=price * (1 + self.config["short_stop_pct"]),
                                take_profit=price * 0.90,
                                reason=decision.get("reason", ""),
                            )
                            short_exposure += portfolio_value * position_pct

                decisions.append({
                    "action":     action,
                    "symbol":     symbol,
                    "reason":     decision.get("reason", ""),
                    "regime":     "DEFENSIVE",
                    "confidence": decision.get("confidence", ""),
                    "macro_mode": "DEFENSIVE",
                })

                logger.info(
                    f"[Aggressive] {symbol}: {action} (DEFENSIVE) | "
                    f"Confidence: {decision.get('confidence', '')} | "
                    f"{decision.get('reason', '')}"
                )

            except Exception as e:
                logger.error(f"[Aggressive] Defensive mode error {symbol}: {e}")

        return decisions

    def run_cycle(self) -> List[dict]:
        if self.killed:
            logger.info("[Aggressive] Bot killed — skipping.")
            return []

        self._reset_daily_state()

        if self.stopped_today:
            logger.info("[Aggressive] Daily stop active — skipping.")
            return []

        self._check_crypto_stops()

        # ── MACRO REGIME CHECK ──────────────────────────────
        macro      = get_macro_mode()
        macro_mode = macro["mode"]

        logger.info(
            f"[Aggressive] 🌍 Macro mode: {macro_mode} | "
            f"VIX: {macro['vix']:.1f} ({macro['vix_level']}) | "
            f"SPY {'above' if macro['above_200ma'] else 'below'} 200MA"
        )

        portfolio_value = self.alpaca.get_portfolio_value()
        cash            = self.alpaca.get_cash()
        open_positions  = self.alpaca.get_position_symbols()
        decisions       = []

        # Kill switch
        if portfolio_value <= self.config["portfolio_floor"]:
            logger.warning(f"[Aggressive] 🔴 Kill switch: ${portfolio_value:.2f}")
            self.killed = True
            self.alpaca.cancel_all_orders()
            self.alpaca.close_all_positions()
            return [{"action": "STOP_ALL", "reason": "Portfolio below floor"}]

        # Daily stop
        if self.today_open_value:
            daily_loss_pct = (self.today_open_value - portfolio_value) / self.today_open_value
            if daily_loss_pct >= self.config["daily_stop_pct"]:
                logger.warning(f"[Aggressive] 🟡 Daily stop: {daily_loss_pct:.1%}")
                self.stopped_today = True
                return [{"action": "STOP_TODAY", "reason": "Daily loss threshold hit"}]

        # ── DEFENSIVE MODE → short ETFs instead of going long ──
        if macro_mode == "DEFENSIVE":
            return self._run_defensive_mode(macro)

        # ── LONG MODES: MOMENTUM, MEAN_REVERSION, MACRO_EVENT ──
        allow_long = self.config["regime_allow_long"].get(macro_mode, True)
        size_mult  = self.config["regime_size_multiplier"].get(macro_mode, 1.0)
        max_pos    = {"MOMENTUM": 5, "MEAN_REVERSION": 3, "MACRO_EVENT": 2}.get(macro_mode, 5)

        # Still check short stops even in non-defensive modes
        covered = check_short_stops(self.alpaca, self.config)
        for sym in covered:
            decisions.append({
                "action": "COVER_SHORT", "symbol": sym,
                "reason": "Short stop triggered", "regime": macro_mode,
                "confidence": "N/A", "macro_mode": macro_mode,
            })

        if not allow_long:
            logger.info(f"[Aggressive] {macro_mode} mode — no new longs permitted.")
            return decisions

        if len(open_positions) >= max_pos:
            logger.info(f"[Aggressive] Max positions ({len(open_positions)}/{max_pos}).")
            return decisions

        # Dynamic symbol list
        stock_symbols  = get_screened_symbols("aggressive")
        crypto_symbols = get_crypto_symbols("aggressive")
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
                if not is_regime_match(regime["regime"], "aggressive"):
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

                eligible, reason = is_trade_eligible(score, earnings, "aggressive")
                logger.info(f"[Aggressive] {symbol}: {score_summary(score, eligible, reason)}")

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
                    raw_pct = decision.get("position_size_pct", max_pct * 0.5)
                    if raw_pct > 1:
                        raw_pct = raw_pct / 100
                    position_pct = min(raw_pct, max_pct) * size_mult
                    price        = signals["price"]
                    atr          = signals["atr"]
                    stop_loss    = price - (self.config["atr_stop_multiplier"] * atr)
                    take_profit  = price + (self.config["take_profit_multiplier"] * (price - stop_loss))
                    qty          = self.alpaca.calculate_qty(symbol, portfolio_value, position_pct, price)

                    if qty > 0:
                        order = self.alpaca.place_limit_order(
                            symbol=symbol, side="buy", qty=qty,
                            limit_price=price * 1.002,
                            take_profit=take_profit, stop_loss=stop_loss,
                        )
                        if order:
                            if self.alpaca.is_crypto(symbol):
                                save_crypto_position(
                                    symbol=symbol, entry_price=price,
                                    stop_price=stop_loss, qty=qty,
                                    strategy="Aggressive",
                                )
                            alert_trade_executed(
                                strategy_name="Aggressive", action="BUY",
                                symbol=symbol, qty=qty, price=price,
                                stop_loss=stop_loss, take_profit=take_profit,
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
                    "macro_mode":    macro_mode,
                })

                logger.info(
                    f"[Aggressive] {symbol}: {action} | Mode: {macro_mode} | "
                    f"Regime: {regime['regime']} | "
                    f"Confidence: {decision.get('confidence', '')} | "
                    f"{decision.get('reason', '')}"
                )

            except Exception as e:
                logger.error(f"[Aggressive] Error {symbol}: {e}")
                continue

        return decisions
