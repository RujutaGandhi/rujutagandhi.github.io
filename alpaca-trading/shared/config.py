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
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
ALERT_EMAIL_TO       = os.getenv("ALERT_EMAIL_TO")

# ============================================================
# TRADING UNIVERSE
# ============================================================
CONSERVATIVE_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "JPM", "V", "UNH"
]

CONSERVATIVE_CRYPTO = [
    "BTC/USD", "ETH/USD"
]

AGGRESSIVE_STOCKS = [
    # Large cap
    "AAPL", "MSFT", "NVDA", "TSLA", "META",
    # Small cap / momentum
    "PLTR", "RKLB", "IONQ", "SMCI", "MSTR",
    "HOOD", "COIN", "SOFI", "OPEN", "ACHR"
]

AGGRESSIVE_CRYPTO = [
    "BTC/USD", "ETH/USD",
    "SOL/USD", "DOGE/USD", "AVAX/USD"
]

# ============================================================
# CONSERVATIVE STRATEGY SETTINGS
# ============================================================
CONSERVATIVE = {
    "name": "Conservative",
    "starting_capital": float(os.getenv("CONSERVATIVE_STARTING_CAPITAL", 1000)),
    "frequency_minutes": int(os.getenv("TRADING_FREQUENCY_MINUTES", 60)),
    "max_position_pct": 0.05,        # 5% max per trade
    "crypto_cap_pct": 0.02,          # 2% max in any crypto position
    "atr_stop_multiplier": 1.5,      # Stop loss = 1.5x ATR
    "take_profit_multiplier": 3.0,   # Take profit = 3x risk
    "max_open_positions": 3,
    "signals_required": 3,           # 3 of 5 indicators must agree
    "daily_stop_pct": 0.15,          # Stop trading if down 15% today
    "portfolio_floor": 700,          # Kill switch: halt permanently if below $700
    "stocks": CONSERVATIVE_STOCKS,
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
    "max_position_pct": 0.15,        # 15% max per trade
    "crypto_cap_pct": 0.20,          # 20% max in any crypto position
    "atr_stop_multiplier": 2.5,      # Wider stops for volatile assets
    "take_profit_multiplier": 5.0,   # Bigger targets
    "max_open_positions": 5,
    "signals_required": 2,           # Only 2 of 5 indicators need to agree
    "daily_stop_pct": 0.20,          # Stop trading if down 20% today
    "portfolio_floor": 600,          # Kill switch: halt permanently if below $600
    "stocks": AGGRESSIVE_STOCKS,
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
        "ALERT_EMAIL_PASSWORD": ALERT_EMAIL_PASSWORD,
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
