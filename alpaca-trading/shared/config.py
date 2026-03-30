"""
shared/config.py
================
Central configuration for both strategies.
All settings in one place — easy to tune without hunting through files.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API CREDENTIALS
# ============================================================
ALPACA_API_KEY_CONSERVATIVE    = os.getenv("ALPACA_API_KEY_CONSERVATIVE")
ALPACA_SECRET_KEY_CONSERVATIVE = os.getenv("ALPACA_SECRET_KEY_CONSERVATIVE")
ALPACA_API_KEY_AGGRESSIVE      = os.getenv("ALPACA_API_KEY_AGGRESSIVE")
ALPACA_SECRET_KEY_AGGRESSIVE   = os.getenv("ALPACA_SECRET_KEY_AGGRESSIVE")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Email alerts
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")
ALERT_EMAIL_TO   = os.getenv("ALERT_EMAIL_TO")

# ============================================================
# TRADING UNIVERSE
# ============================================================

EXCLUDED_SYMBOLS = [
    "AMZN",   # Trading restrictions
]

PERMANENT_SYMBOLS = [
    "UBER",   # Always monitored
]

CONSERVATIVE_CRYPTO = ["BTC/USD", "ETH/USD"]

AGGRESSIVE_CRYPTO = [
    "BTC/USD", "ETH/USD",
    "SOL/USD", "DOGE/USD", "AVAX/USD"
]

CONSERVATIVE_STOCKS_FALLBACK = [
    "AAPL", "MSFT", "GOOGL", "NVDA",
    "META", "TSLA", "JPM", "V", "UBER"
]

AGGRESSIVE_STOCKS_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META",
    "PLTR", "RKLB", "IONQ", "SMCI", "MSTR",
    "HOOD", "COIN", "SOFI", "UBER", "ACHR"
]

# ============================================================
# COMBINED PORTFOLIO RISK
# Both strategies together — monitored in main.py
# ============================================================
COMBINED_STARTING_CAPITAL = 2000.0          # $1,000 conservative + $1,000 aggressive
COMBINED_PORTFOLIO_FLOOR  = 1700.0          # -15% combined → halt both strategies
COMBINED_DAILY_STOP_PCT   = 0.08            # -8% combined in one day → halt both

# ============================================================
# MACRO REGIME THRESHOLDS
# ============================================================
VIX_LOW      = 20    # Below this = calm market = MOMENTUM mode
VIX_ELEVATED = 25    # 20-25 = caution = cautious MOMENTUM or MEAN_REVERSION
VIX_HIGH     = 30    # 25-30 = HIGH = DEFENSIVE
                     # Above 30 = EXTREME = MACRO_EVENT

# ============================================================
# SECTOR CAPS
# ============================================================
SECTOR_CAP_PCT = 0.30    # Max 30% of portfolio in any single sector

# Sector membership — used for exposure checks
SECTOR_MAP = {
    "tech":     ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "SMCI"],
    "finance":  ["JPM", "V", "HOOD", "SOFI", "COIN"],
    "ev":       ["TSLA", "RIVN", "LCID"],
    "ai":       ["PLTR", "IONQ", "MSTR", "RKLB"],
    "energy":   ["XLE", "XOP", "USO", "RTX", "LMT", "NOC"],
    "crypto":   ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"],
    "defensive":["GLD", "SLV", "XLU", "VNQ"],
}

# ============================================================
# CONSERVATIVE STRATEGY SETTINGS
# ============================================================
CONSERVATIVE = {
    "name":                 "Conservative",
    "starting_capital":     float(os.getenv("CONSERVATIVE_STARTING_CAPITAL", 1000)),
    "frequency_minutes":    int(os.getenv("TRADING_FREQUENCY_MINUTES", 60)),
    "max_position_pct":     0.05,
    "crypto_cap_pct":       0.02,
    "atr_stop_multiplier":  1.5,
    "take_profit_multiplier": 3.0,
    "max_open_positions":   3,
    "signals_required":     3,
    "daily_stop_pct":       0.15,
    "portfolio_floor":      700,
    "allow_short":          False,      # Conservative NEVER shorts
    "stocks":               CONSERVATIVE_STOCKS_FALLBACK,
    "crypto":               CONSERVATIVE_CRYPTO,
    "log_file":             "logs/conservative.log",
    # Regime-specific position size multipliers
    "regime_size_multiplier": {
        "MOMENTUM":       1.0,    # Full size
        "MEAN_REVERSION": 0.6,    # 60% — less conviction
        "DEFENSIVE":      0.0,    # No new longs
        "MACRO_EVENT":    0.0,    # No new longs
    },
}

# ============================================================
# AGGRESSIVE STRATEGY SETTINGS
# ============================================================
AGGRESSIVE = {
    "name":                 "Aggressive",
    "starting_capital":     float(os.getenv("AGGRESSIVE_STARTING_CAPITAL", 1000)),
    "frequency_minutes":    int(os.getenv("TRADING_FREQUENCY_MINUTES", 60)),
    "max_position_pct":     0.15,
    "crypto_cap_pct":       0.20,
    "atr_stop_multiplier":  2.5,
    "take_profit_multiplier": 5.0,
    "max_open_positions":   5,
    "signals_required":     2,
    "daily_stop_pct":       0.20,
    "portfolio_floor":      600,
    "allow_short":          True,
    # Short selling — ETF/index only, no single stocks
    "short_symbols":        ["SPY", "QQQ"],
    "short_score_threshold": -4,        # Score ≤ -4 to consider shorting
    "max_short_exposure_pct": 0.30,     # Max 30% of portfolio in shorts
    "short_stop_pct":        0.08,      # Hard stop if short up 8% against us
    "short_squeeze_pct":     0.05,      # Force close if ETF rises 5% intraday
    "stocks":               AGGRESSIVE_STOCKS_FALLBACK,
    "crypto":               AGGRESSIVE_CRYPTO,
    "log_file":             "logs/aggressive.log",
    # Regime-specific position size multipliers
    "regime_size_multiplier": {
        "MOMENTUM":       1.0,    # Full size
        "MEAN_REVERSION": 0.7,    # 70% — smaller positions for reversion plays
        "DEFENSIVE":      0.5,    # 50% — minimal longs, mostly shorts
        "MACRO_EVENT":    0.5,    # 50% — reduced exposure
    },
    # Regime-specific long/short permission
    "regime_allow_long": {
        "MOMENTUM":       True,
        "MEAN_REVERSION": True,
        "DEFENSIVE":      False,  # No new longs in bear market
        "MACRO_EVENT":    True,   # Allow selective longs (defensive ETFs)
    },
    "regime_allow_short": {
        "MOMENTUM":       False,  # Don't short in bull market
        "MEAN_REVERSION": False,  # Don't short in chop
        "DEFENSIVE":      True,   # Short SPY/QQQ in bear market
        "MACRO_EVENT":    False,  # Too unpredictable to short
    },
}

# ============================================================
# SHARED INDICATOR SETTINGS
# ============================================================
INDICATORS = {
    "rsi_period":            14,
    "rsi_oversold":          30,
    "rsi_overbought":        70,
    "ema_fast":              9,
    "ema_slow":              21,
    "macd_fast":             12,
    "macd_slow":             26,
    "macd_signal":           9,
    "atr_period":            14,
    "volume_avg_period":     20,
    "volume_surge_threshold": 1.2,
}

# ============================================================
# MARKET HOURS (Eastern Time)
# ============================================================
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN  = 0
NO_NEW_TRADES_MINS_BEFORE_CLOSE = 30

# ============================================================
# CLAUDE MODEL
# ============================================================
CLAUDE_MODEL      = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 500

# ============================================================
# VALIDATION
# ============================================================
def validate_config():
    required = {
        "ALPACA_API_KEY_CONSERVATIVE":    ALPACA_API_KEY_CONSERVATIVE,
        "ALPACA_SECRET_KEY_CONSERVATIVE": ALPACA_SECRET_KEY_CONSERVATIVE,
        "ALPACA_API_KEY_AGGRESSIVE":      ALPACA_API_KEY_AGGRESSIVE,
        "ALPACA_SECRET_KEY_AGGRESSIVE":   ALPACA_SECRET_KEY_AGGRESSIVE,
        "ANTHROPIC_API_KEY":              ANTHROPIC_API_KEY,
        "ALERT_EMAIL_FROM":               ALERT_EMAIL_FROM,
        "ALERT_EMAIL_TO":                 ALERT_EMAIL_TO,
    }
    missing = [k for k, v in required.items() if not v or "your_" in str(v)]
    if missing:
        raise ValueError(
            f"\n❌ Missing required environment variables: {missing}\n"
            f"   → Copy .env.template to .env and fill in your values.\n"
        )
    print("✅ Config validated — all API keys present.")

if __name__ == "__main__":
    validate_config()
