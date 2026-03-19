# 🤖 AI Trading Bot — Rujuta Gandhi

A dual-strategy paper trading bot powered by Claude AI + Alpaca Markets.
Built as an AI PM portfolio project demonstrating agentic system design,
prompt engineering, and risk management architecture.

---

## Strategies

| | Conservative | Aggressive |
|---|---|---|
| Capital | $1,000 | $1,000 |
| Universe | Large cap + BTC/ETH | Large cap + small cap + BTC/ETH + altcoins |
| Max position | 5% | 15% |
| Signals required | 3 of 5 | 2 of 5 |
| Kill switch | $700 | $600 |

---

## Setup

### 1. Clone and install
```bash
git clone <your-repo>
cd trading-bot
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.template .env
# Edit .env with your API keys
```

### 3. Validate config
```bash
python shared/config.py
```

### 4. Run the bot
```bash
python main.py
```

### 5. View dashboard
```bash
streamlit run dashboard.py
```

---

## Architecture

```
Layer 1 — Python (deterministic)
  Fetch data → Compute indicators → Regime filter → Pre-filter setups

Layer 2 — Claude API (reasoning)
  Receives only pre-validated setups → Final judgment → JSON decision

Layer 3 — Execution
  Parse JSON → Size position → Place limit order → Set stop/take-profit

Layer 4 — Risk Guardian
  Monitors kill switches → Sends email alerts → Halts if triggered
```

---

## API Keys Required

- **Alpaca** (paper trading): alpaca.markets
- **Anthropic**: console.anthropic.com
- **Gmail App Password**: Google Account → Security → App Passwords

---

## Deployment (Render.com)

1. Push to GitHub
2. Create new Web Service on Render
3. Set environment variables in Render dashboard
4. Deploy — runs 24/7 without your laptop

---

*This is a paper trading experiment. Not financial advice.*
