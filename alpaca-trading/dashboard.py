"""
dashboard.py
============
Live performance dashboard for both trading strategies.
Built with Streamlit — runs in browser.

Data sources:
- Live portfolio values:   Alpaca account API
- Trade history:           Alpaca closed orders API
- Equity curve:            Alpaca portfolio history API
- S&P500 comparison:       Alpaca stock bars (SPY)
- Market regime:           Computed live from price data
- Sharpe ratio:            Computed from daily portfolio history

No log files required — all data comes from Alpaca directly,
so this works even on a separate Render service from the bot.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from shared.alpaca_client import AlpacaClient
from shared.config import (
    CONSERVATIVE, AGGRESSIVE,
    ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE,
    ALPACA_API_KEY_AGGRESSIVE,   ALPACA_SECRET_KEY_AGGRESSIVE,
    PERMANENT_SYMBOLS, EXCLUDED_SYMBOLS,
    validate_config,
)
from shared.indicators import compute_all, get_latest_signals
from shared.regime_filter import regime_summary

ET     = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("🤖 AI Trading Bot — Live Dashboard")
st.caption(f"Paper Trading · Updated: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")

# ============================================================
# CONNECT TO ALPACA
# ============================================================

@st.cache_resource
def get_alpaca_clients():
    try:
        validate_config()
        con = AlpacaClient(ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE)
        agg = AlpacaClient(ALPACA_API_KEY_AGGRESSIVE,   ALPACA_SECRET_KEY_AGGRESSIVE)
        return con, agg
    except Exception as e:
        st.error(f"❌ Alpaca connection failed: {e}")
        return None, None

alpaca_con, alpaca_agg = get_alpaca_clients()

if not alpaca_con or not alpaca_agg:
    st.stop()

# ============================================================
# FETCH ALL DATA
# ============================================================

@st.cache_data(ttl=300)
def fetch_dashboard_data():
    data = {}
    data["con_value"]     = alpaca_con.get_portfolio_value()
    data["agg_value"]     = alpaca_agg.get_portfolio_value()
    data["con_cash"]      = alpaca_con.get_cash()
    data["agg_cash"]      = alpaca_agg.get_cash()
    data["con_positions"] = alpaca_con.get_positions()
    data["agg_positions"] = alpaca_agg.get_positions()
    data["con_orders"]    = alpaca_con.get_closed_orders(days_back=30)
    data["agg_orders"]    = alpaca_agg.get_closed_orders(days_back=30)
    data["con_history"]   = alpaca_con.get_portfolio_history(days_back=30)
    data["agg_history"]   = alpaca_agg.get_portfolio_history(days_back=30)
    return data

try:
    d = fetch_dashboard_data()
except Exception as e:
    st.error(f"❌ Failed to fetch data: {e}")
    st.stop()

con_start = CONSERVATIVE["starting_capital"]
agg_start = AGGRESSIVE["starting_capital"]

# ============================================================
# HELPERS
# ============================================================

def delta_metric(label, value, delta, prefix="$"):
    """
    Renders st.metric with correct arrow and color.
    Positive → green up arrow
    Negative → red down arrow
    Zero     → no arrow, grey text
    """
    if abs(delta) < 0.01:
        st.metric(label=label, value=f"{prefix}{value:,.2f}")
    else:
        st.metric(
            label=label,
            value=f"{prefix}{value:,.2f}",
            delta=f"{prefix}{delta:+,.2f} vs start",
            delta_color="normal",
        )


def compute_sharpe(history_df, starting_capital):
    if history_df.empty or len(history_df) < 5:
        return "N/A"
    try:
        values  = history_df["value"].values
        returns = pd.Series(values).pct_change().dropna()
        if returns.std() == 0:
            return "N/A"
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        return f"{sharpe:.2f}"
    except Exception:
        return "N/A"


def orders_to_df(orders):
    if not orders:
        return pd.DataFrame()
    rows = []
    for o in orders:
        try:
            rows.append({
                "Time":   pd.to_datetime(str(o.filled_at)).tz_convert(ET).strftime("%m/%d %H:%M"),
                "Symbol": str(o.symbol),
                "Side":   str(o.side).replace("OrderSide.", "").upper(),
                "Qty":    float(o.filled_qty or 0),
                "Price":  f"${float(o.filled_avg_price or 0):,.4f}",
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


# ============================================================
# SECTION 1 — LIVE PORTFOLIO
# ============================================================

st.subheader("💰 Live Portfolio")

col1, col2, col3 = st.columns(3)

con_delta      = d["con_value"] - con_start
agg_delta      = d["agg_value"] - agg_start
combined_delta = (d["con_value"] + d["agg_value"]) - (con_start + agg_start)

with col1:
    delta_metric("🛡️ Conservative", d["con_value"], con_delta)
with col2:
    delta_metric("⚡ Aggressive",   d["agg_value"], agg_delta)
with col3:
    delta_metric("Combined Total", d["con_value"] + d["agg_value"], combined_delta)

if d["con_positions"] or d["agg_positions"]:
    st.subheader("📋 Open Positions")
    pcol1, pcol2 = st.columns(2)

    def render_positions(positions, label, col):
        with col:
            st.markdown(f"**{label}**")
            if not positions:
                st.info("No open positions.")
                return
            pos_data = [{
                "Symbol":  p.symbol,
                "Qty":     float(p.qty),
                "Entry":   f"${float(p.avg_entry_price):,.4f}",
                "Current": f"${float(p.current_price):,.4f}",
                "P&L":     f"${float(p.unrealized_pl):,.2f}",
                "P&L %":   f"{float(p.unrealized_plpc)*100:.2f}%",
            } for p in positions]
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True, hide_index=True)

    render_positions(d["con_positions"], "🛡️ Conservative", pcol1)
    render_positions(d["agg_positions"], "⚡ Aggressive",   pcol2)
else:
    st.info("No open positions in either strategy.")

# ============================================================
# SECTION 2 — EQUITY CURVE vs S&P500
# ============================================================

st.divider()
st.subheader("📈 Portfolio Performance vs S&P 500")
st.caption(
    "Daily portfolio value for each strategy vs SPY (S&P 500 ETF). "
    "SPY is normalised to the same starting capital for a fair comparison. "
    "A strategy line above SPY is outperforming the broader market."
)

@st.cache_data(ttl=3600)
def fetch_spy():
    try:
        df = alpaca_con.get_stock_bars("SPY", lookback_days=30)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        date_col = "timestamp" if "timestamp" in df.columns else df.index.name or "index"
        df["date"] = pd.to_datetime(df[date_col] if date_col in df.columns else df.index)
        return df[["date", "close"]].rename(columns={"close": "spy_close"})
    except Exception:
        return pd.DataFrame()

spy_df = fetch_spy()

fig = go.Figure()

if not d["con_history"].empty:
    fig.add_trace(go.Scatter(
        x=d["con_history"]["date"], y=d["con_history"]["value"],
        name="🛡️ Conservative", line=dict(color="#3b82f6", width=2),
        hovertemplate="Conservative: $%{y:,.2f}<br>%{x}<extra></extra>",
    ))

if not d["agg_history"].empty:
    fig.add_trace(go.Scatter(
        x=d["agg_history"]["date"], y=d["agg_history"]["value"],
        name="⚡ Aggressive", line=dict(color="#f59e0b", width=2),
        hovertemplate="Aggressive: $%{y:,.2f}<br>%{x}<extra></extra>",
    ))

if not spy_df.empty:
    spy_start      = spy_df["spy_close"].iloc[0]
    avg_start      = (con_start + agg_start) / 2
    spy_normalised = (spy_df["spy_close"] / spy_start) * avg_start
    fig.add_trace(go.Scatter(
        x=spy_df["date"], y=spy_normalised,
        name="📊 S&P 500 (SPY)", line=dict(color="#6b7280", width=1.5, dash="dot"),
        hovertemplate="SPY (normalised): $%{y:,.2f}<br>%{x}<extra></extra>",
    ))

fig.update_layout(
    height=350, showlegend=True,
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    yaxis=dict(title="Portfolio Value ($)", gridcolor="#e5e7eb", tickprefix="$"),
    xaxis=dict(gridcolor="#e5e7eb"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=0, r=0, t=40, b=0),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

# ============================================================
# SECTION 3 — STRATEGY PERFORMANCE + SHARPE
# ============================================================

st.divider()
st.subheader("📊 Strategy Performance")

col_con, col_agg = st.columns(2)

def render_strategy_stats(orders, history, name, start, col):
    with col:
        icon = "🛡️" if name == "Conservative" else "⚡"
        st.markdown(f"### {icon} {name}")

        sharpe           = compute_sharpe(history, start)
        total_return_pct = ((history["value"].iloc[-1] / start) - 1) * 100 \
                           if not history.empty and len(history) > 1 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Sharpe Ratio",  sharpe,
                  help="Risk-adjusted return. Above 1.0 is good. Above 2.0 is very strong.")
        m2.metric("Total Return",  f"{total_return_pct:+.2f}%")
        m3.metric("Trades",        len(orders))

        st.caption(
            "**Sharpe Ratio** = return ÷ risk (volatility). "
            "Above 1.0: returns justify the risk. "
            "Above 2.0: very strong risk-adjusted performance. "
            "Below 0: strategy is losing money."
        )

        buys  = [o for o in orders if "buy"  in str(o.side).lower()]
        sells = [o for o in orders if "sell" in str(o.side).lower()]
        b1, b2 = st.columns(2)
        b1.metric("Buys",  len(buys))
        b2.metric("Sells", len(sells))

        orders_df = orders_to_df(orders)
        if not orders_df.empty:
            st.markdown("**Recent Trades:**")
            st.dataframe(orders_df.head(10), use_container_width=True, hide_index=True)
        else:
            st.info("No completed trades yet.")

render_strategy_stats(d["con_orders"], d["con_history"], "Conservative", con_start, col_con)
render_strategy_stats(d["agg_orders"], d["agg_history"], "Aggressive",   agg_start, col_agg)

# ============================================================
# SECTION 4 — LIVE MARKET REGIME
# ============================================================

st.divider()
st.subheader("🌊 Live Market Regime")

st.markdown("""
**What is Market Regime?**

Market regime describes the current character of price movement for each asset, measured using ADX (Average Directional Index):

- 🟢 **TREND** (ADX > 25) — Price moving strongly in one direction. Momentum strategies work best here. Both Conservative and Aggressive strategies trade in TREND regime.
- 🟡 **RANGE** (ADX < 20) — Price moving sideways. Mean reversion works better. Only the Aggressive strategy trades in RANGE regime.
- ⚪ **UNCLEAR** (ADX 20–25) — Mixed signals. Both strategies skip these assets entirely.

Higher ADX = stronger trend. The table below shows the current regime for each asset in the bot's universe.
""")

@st.cache_data(ttl=1800)
def compute_live_regimes():
    symbols = list(PERMANENT_SYMBOLS) + [
        "AAPL", "MSFT", "NVDA", "TSLA", "META",
        "PLTR", "COIN", "MSTR",
        "BTC/USD", "ETH/USD", "SOL/USD",
    ]
    excluded = {s.upper() for s in EXCLUDED_SYMBOLS}
    symbols  = [s for s in dict.fromkeys(symbols) if s.upper() not in excluded]

    rows = []
    for symbol in symbols:
        try:
            df = alpaca_con.get_bars(symbol, lookback_days=30)
            if df.empty:
                continue
            df     = compute_all(df)
            regime = regime_summary(df)
            rows.append({
                "Symbol":      symbol,
                "Regime":      regime.get("regime", "UNCLEAR"),
                "ADX":         round(float(regime.get("adx", 0)), 1),
                "Description": regime.get("description", ""),
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Regime", "ADX"], ascending=[True, False])

regime_df = compute_live_regimes()

if not regime_df.empty:
    def style_regime(val):
        if val == "TREND":   return "background-color: #dcfce7; color: #166534; font-weight: bold"
        if val == "RANGE":   return "background-color: #fef9c3; color: #854d0e; font-weight: bold"
        if val == "UNCLEAR": return "background-color: #f3f4f6; color: #6b7280"
        return ""

    st.dataframe(
        regime_df.style.applymap(style_regime, subset=["Regime"]),
        use_container_width=True,
        hide_index=True,
    )

    r1, r2, r3 = st.columns(3)
    r1.metric("🟢 TREND",   len(regime_df[regime_df["Regime"] == "TREND"]),
              help="Conservative + Aggressive can trade")
    r2.metric("🟡 RANGE",   len(regime_df[regime_df["Regime"] == "RANGE"]),
              help="Aggressive only can trade")
    r3.metric("⚪ UNCLEAR", len(regime_df[regime_df["Regime"] == "UNCLEAR"]),
              help="Both strategies skip")
else:
    st.info("Loading regime data...")

# ============================================================
# SECTION 5 — FULL ORDER HISTORY
# ============================================================

st.divider()
with st.expander("📄 Full Order History (last 30 days)"):
    rows = []
    for o in d["con_orders"]:
        try:
            rows.append({
                "Strategy": "Conservative",
                "Time":     pd.to_datetime(str(o.filled_at)).tz_convert(ET).strftime("%Y-%m-%d %H:%M"),
                "Symbol":   str(o.symbol),
                "Side":     str(o.side).replace("OrderSide.", "").upper(),
                "Qty":      float(o.filled_qty or 0),
                "Price":    f"${float(o.filled_avg_price or 0):,.4f}",
            })
        except Exception:
            continue
    for o in d["agg_orders"]:
        try:
            rows.append({
                "Strategy": "Aggressive",
                "Time":     pd.to_datetime(str(o.filled_at)).tz_convert(ET).strftime("%Y-%m-%d %H:%M"),
                "Symbol":   str(o.symbol),
                "Side":     str(o.side).replace("OrderSide.", "").upper(),
                "Qty":      float(o.filled_qty or 0),
                "Price":    f"${float(o.filled_avg_price or 0):,.4f}",
            })
        except Exception:
            continue

    if rows:
        all_df = pd.DataFrame(rows).sort_values("Time", ascending=False)
        st.dataframe(all_df, use_container_width=True, hide_index=True)
    else:
        st.info("No completed orders in the last 30 days.")

# ============================================================
# REFRESH
# ============================================================

st.divider()
st.caption("Portfolio + trades refresh every 5 min · Regime refreshes every 30 min")

if st.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()

st.markdown(
    """<script>setTimeout(function(){window.location.reload();},300000);</script>""",
    unsafe_allow_html=True,
)
