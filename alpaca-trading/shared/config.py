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
ALERT_EMAIL_FROM     = os.getenv("ALERT_EMAIL_FROM")
ALERT_EMAIL_TO       = os.getenv("ALERT_EMAIL_TO")

# ============================================================
# TRADING UNIVERSE
# ============================================================

# Symbols NEVER traded — trading restrictions or other reasons
# Add any symbols here you cannot or should not trade
EXCLUDED_SYMBOLS = [
    "AMZN",   # Trading restrictions
]

# Symbols ALWAYS included in every scan regardless of screener
PERMANENT_SYMBOLS = [
    "UBER",   # Always monitored
]

# Crypto universes — fixed (screener not applicable for crypto)
CONSERVATIVE_CRYPTO = [
    "BTC/USD", "ETH/USD"
]

AGGRESSIVE_CRYPTO = [
    "BTC/USD", "ETH/USD",
    "SOL/USD", "DOGE/USD", "AVAX/USD"
]

# Legacy fallback stock lists — used if screener fails
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
# CONSERVATIVE STRATEGY SETTINGS
# ============================================================
CONSERVATIVE = {
    "name": "Conservative",
    "starting_capital": float(os.getenv("CONSERVATIVE_STARTING_CAPITAL", 1000)),
    "frequency_minutes": int(os.getenv("TRADING_FREQUENCY_MINUTES", 60)),
    "max_position_pct": 0.05,
    "crypto_cap_pct": 0.02,
    "atr_stop_multiplier": 1.5,
    "take_profit_multiplier": 3.0,
    "max_open_positions": 3,
    "signals_required": 3,
    "daily_stop_pct": 0.15,
    "portfolio_floor": 700,
    "stocks": CONSERVATIVE_STOCKS_FALLBACK,   # Fallback only — screener used at runtime
    "crypto": CONSERVATIVE_CRYPTO,
    "log_file": "logs/conservative.log",
}

# ============================================================
# AGGRESSIVE STRATEGY SETTINGS
# ============================================================
AGGRESSIVE = {
    "name": "Aggressive",
    "starting_capital": float(os.getenv("AGGRESSIVE_STARTING_CAPITAL", 1000)),
    "frequency_minutes": int(os.getenv("TRADING_FREQUENCY_MINUTES", 60)),
    "max_position_pct": 0.15,
    "crypto_cap_pct": 0.20,
    "atr_stop_multiplier": 2.5,
    "take_profit_multiplier": 5.0,
    "max_open_positions": 5,
    "signals_required": 2,
    "daily_stop_pct": 0.20,
    "portfolio_floor": 600,
    "stocks": AGGRESSIVE_STOCKS_FALLBACK,   # Fallback only — screener used at runtime
    "crypto": AGGRESSIVE_CRYPTO,
    "log_file": "logs/aggressive.log",
}

# ============================================================
# SHARED INDICATOR SETTINGS
# ============================================================
INDICATORS = {
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "ema_fast": 9,
    "ema_slow": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "volume_avg_period": 20,
    "volume_surge_threshold": 1.2,   # Volume must be 1.2x 20-day average
}

# ============================================================
# MARKET HOURS (Eastern Time)
# ============================================================
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN  = 0
NO_NEW_TRADES_MINS_BEFORE_CLOSE = 30  # No new trades in last 30 mins

# ============================================================
# CLAUDE MODEL
# ============================================================
CLAUDE_MODEL      = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 500   # Decisions are short — keep costs low

# ============================================================
# VALIDATION — fail loudly if keys are missing
# ============================================================
def validate_config():
    required = {
        "ALPACA_API_KEY_CONSERVATIVE": ALPACA_API_KEY_CONSERVATIVE,
        "ALPACA_SECRET_KEY_CONSERVATIVE": ALPACA_SECRET_KEY_CONSERVATIVE,
        "ALPACA_API_KEY_AGGRESSIVE": ALPACA_API_KEY_AGGRESSIVE,
        "ALPACA_SECRET_KEY_AGGRESSIVE": ALPACA_SECRET_KEY_AGGRESSIVE,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "ALERT_EMAIL_FROM": ALERT_EMAIL_FROM,
        "ALERT_EMAIL_TO": ALERT_EMAIL_TO,
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
