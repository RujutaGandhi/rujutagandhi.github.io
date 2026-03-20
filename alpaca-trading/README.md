# 📈 AI Paper Trading Bot

A dual-strategy autonomous paper trading bot powered by Claude AI and Alpaca Markets. Built as an AI PM portfolio project demonstrating agentic system design, prompt engineering, risk management architecture, and production deployment.

**Live dashboard:** https://alpaca-trading-dashboard-aanl.onrender.com

---

## What It Does

Two parallel trading strategies run 24/7 on Render, scanning US stocks and crypto every hour. Claude makes every buy/sell/hold decision using a weighted 8-signal scoring engine. A self-tuning end-of-day review fires at 4:05pm ET — Claude analyzes the day's trades and adjusts parameters for the next session.

| | Conservative | Aggressive |
|---|---|---|
| Persona | Former Bridgewater portfolio manager | Former Citadel prop trader |
| Capital | $1,000 paper | $1,000 paper |
| Universe | Large cap stocks + BTC/ETH | Large cap + small cap + BTC/ETH + altcoins |
| Signal threshold | 6+ points | 4+ points |
| Max position | 5% stocks / 2% crypto | 15% stocks / 20% crypto |
| Daily stop | 15% loss | 20% loss |
| Kill switch | Portfolio < $700 | Portfolio < $600 |

---

## Signal Architecture

| Signal | Points | Source |
|---|---|---|
| News sentiment (Claude) | +3 / -3 | Alpaca News API → Claude |
| Social sentiment (Reddit/StockTwits) | +2 / -2 | Reddit API + StockTwits API → Claude |
| Congressional trades | +2 / -1 | Capitol Trades API |
| Market regime (ADX) | +2 / 0 | Computed from price data |
| Fear & Greed Index | +2 to -1 | CNN Fear & Greed |
| RSI | +1 / -1 | Computed from price data |
| MACD | +1 / -1 | Computed from price data |
| EMA crossover | +1 / -1 | Computed from price data |
| Volume ratio | +1 / 0 | Computed from price data |
| **Earnings veto** | **Hard block** | **Alpaca calendar API** |

Conservative requires 6+ points. Aggressive requires 4+. Earnings veto overrides all signals.

---

## Architecture

```
Layer 1 — Python (deterministic)
  Fetch price data → Compute indicators → Regime filter
  → Check earnings veto → Score all signals
  → Pre-filter: only pass eligible setups to Claude

Layer 2 — Claude API (reasoning)
  Receives pre-validated setups + full scorecard
  → Final judgment with persona-driven reasoning
  → Returns structured JSON decision

Layer 3 — Execution
  Parse JSON → Validate position size
  → Stocks: limit bracket order (stop-loss + take-profit)
  → Crypto: market order + manual stop-loss tracking

Layer 4 — Risk Guardian (every cycle)
  Kill switch check → Daily stop check
  → Market hours check → Correlation check
  → Email alert if triggered

Layer 5 — Self-Tuning Review (4:05pm ET daily)
  Read today's trade log → Send to Claude
  → Claude outputs JSON parameter adjustments
  → Apply with safety bounds → Save to state.json
  → Next morning both strategies load updated parameters
```

---

## File Structure

```
alpaca-trading/
├── conservative/
│   └── strategy.py          # Conservative Claude prompts + decision logic
├── aggressive/
│   └── strategy.py          # Aggressive Claude prompts + decision logic
├── shared/
│   ├── config.py            # All settings, API keys, strategy parameters
│   ├── alpaca_client.py     # Alpaca API connection, prices, orders
│   ├── indicators.py        # RSI, MACD, EMA, ATR, Volume computation
│   ├── regime_filter.py     # Trend vs range detection (ADX)
│   ├── risk_guardian.py     # Kill switches, daily stops, correlation check
│   ├── alerts.py            # SendGrid email alerts
│   ├── news.py              # Alpaca News API → Claude sentiment scoring
│   ├── earnings.py          # Earnings calendar veto
│   ├── fear_greed.py        # CNN Fear & Greed Index
│   ├── congressional.py     # Capitol Trades API
│   ├── scoring.py           # Weighted point system (all 8 signals)
│   ├── review.py            # End-of-day Claude review + parameter tuning
│   └── state.py             # Persists adjustments to state.json
│   ├── social_sentiment.py  # Reddit + StockTwits → Claude sentiment scoring
│   ├── screener.py          # Dynamic symbol screener via Alpaca API
├── tests/
│   ├── test_config.py       # Level 1: API key validation
│   ├── test_connection.py   # Level 2: Alpaca connection + data pipeline
│   ├── test_dry_run.py      # Level 3: Full cycle without placing orders
│   ├── test_signals.py      # Phase 1-4 signal module tests
│   └── test_phase5.py       # Phase 5 state + review loop tests
│   └── test_phase6.py       # Phase 6: screener, social sentiment, exclusions
├── main.py                  # Entry point — runs both strategies + health server
├── dashboard.py             # Streamlit performance dashboard
├── requirements.txt
├── runtime.txt              # python-3.11.0
└── .env.template            # Environment variable template
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/RujutaGandhi/rujutagandhi.github.io
cd rujutagandhi.github.io/alpaca-trading
pip3 install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.template .env
# Fill in your API keys
```

Required keys:
- `ALPACA_API_KEY_CONSERVATIVE` + `ALPACA_SECRET_KEY_CONSERVATIVE`
- `ALPACA_API_KEY_AGGRESSIVE` + `ALPACA_SECRET_KEY_AGGRESSIVE`
- `ALPACA_BASE_URL` — `https://paper-api.alpaca.markets`
- `ANTHROPIC_API_KEY`
- `SENDGRID_API_KEY` — Mail Send only, restricted key
- `ALERT_EMAIL_FROM` + `ALERT_EMAIL_TO`

### 3. Run tests

```bash
python3 tests/test_config.py
python3 tests/test_connection.py
python3 tests/test_dry_run.py
python3 tests/test_signals.py
python3 tests/test_phase5.py
python3 tests/test_phase6.py

```

### 4. Run locally

```bash
python3 main.py
streamlit run dashboard.py   # separate terminal
```

---

## Key Design Decisions

**Claude over Finnhub for sentiment** — Pre-computed scores can't distinguish nuance. Claude reads actual headlines and explains reasoning, making decisions auditable.

**Weighted scoring over vote counting** — RSI and MACD correlate. Point weights reflect signal independence: news (+3) outweighs lagging technicals (+1 each).

**Two separate Alpaca accounts** — Shared account means kill switches fire on combined portfolio value. Separate accounts give true capital isolation and accurate floor monitoring.

**Manual crypto stop-loss** — Alpaca doesn't support bracket orders for crypto. State-persisted stop-loss checker runs every cycle and places a market sell if price breaches ATR-based stop.

**Self-tuning daily review** — Claude reads its own trade log at 4:05pm ET, identifies patterns, and outputs JSON parameter adjustments within safety bounds.

**Dynamic screener over fixed stock list** — Instead of always scanning the same 10 stocks, the screener fetches the most active and highest momentum US stocks from Alpaca each cycle. UBER is always included. AMZN is permanently excluded due to trading restrictions.

**Reddit + StockTwits sentiment** — Retail momentum often shows up on social media before it shows up in price. Both APIs are free with no auth required. Claude scores the combined signal, adding up to +2/-2 to the weighted scoring engine.
---

## Tech Stack

Claude Sonnet · Alpaca Markets API · Python 3.11 · Streamlit · Render.com · SendGrid · Alpaca News API · CNN Fear & Greed · Capitol Trades API · pandas · cron-job.org

---

*Paper trading only — no real money. Not financial advice.*
