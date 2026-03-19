"""
dashboard.py
============
Side-by-side performance dashboard for both strategies.
Built with Streamlit — runs in browser.

Usage:
    streamlit run dashboard.py

Shows:
- Live portfolio values for both strategies
- P&L over time (chart)
- Trade history with decisions and reasons
- Win/loss stats
- Kill switch status
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from shared.alpaca_client import AlpacaClient
from shared.config import CONSERVATIVE, AGGRESSIVE, validate_config, ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE, ALPACA_API_KEY_AGGRESSIVE, ALPACA_SECRET_KEY_AGGRESSIVE

ET = ZoneInfo("America/New_York")
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
st.caption(f"Paper Trading | Updated: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")

# ============================================================
# LOAD LOG FILES
# ============================================================

def load_log(log_file: str) -> pd.DataFrame:
    """Loads a JSON-lines log file into a DataFrame."""
    path = Path(log_file)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp")


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

# ============================================================
# LIVE PORTFOLIO VALUES
# ============================================================

st.subheader("💰 Live Portfolio")

col1, col2, col3 = st.columns(3)

if alpaca_con and alpaca_agg:
    try:
        con_value     = alpaca_con.get_portfolio_value()
        agg_value     = alpaca_agg.get_portfolio_value()
        con_cash      = alpaca_con.get_cash()
        agg_cash      = alpaca_agg.get_cash()
        con_positions = alpaca_con.get_positions()
        agg_positions = alpaca_agg.get_positions()
        con_start     = CONSERVATIVE["starting_capital"]
        agg_start     = AGGRESSIVE["starting_capital"]

        with col1:
            st.metric(
                label="🛡️ Conservative",
                value=f"${con_value:,.2f}",
                delta=f"${con_value - con_start:,.2f} vs start",
            )
        with col2:
            st.metric(
                label="⚡ Aggressive",
                value=f"${agg_value:,.2f}",
                delta=f"${agg_value - agg_start:,.2f} vs start",
            )
        with col3:
            st.metric(
                label="Combined Total",
                value=f"${con_value + agg_value:,.2f}",
                delta=f"${(con_value + agg_value) - (con_start + agg_start):,.2f} vs start",
            )

        # Open positions — side by side
        if con_positions or agg_positions:
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
                        "Qty":     p.qty,
                        "Entry":   f"${float(p.avg_entry_price):,.4f}",
                        "Current": f"${float(p.current_price):,.4f}",
                        "P&L":     f"${float(p.unrealized_pl):,.2f}",
                        "P&L %":   f"{float(p.unrealized_plpc)*100:.2f}%",
                    }]
                    st.dataframe(pd.DataFrame(pos_data), use_container_width=True, hide_index=True)

            render_positions(con_positions, "🛡️ Conservative", pcol1)
            render_positions(agg_positions, "⚡ Aggressive",   pcol2)

    except Exception as e:
        st.warning(f"Could not fetch live data: {e}")

# ============================================================
# STRATEGY COMPARISON
# ============================================================

st.divider()
st.subheader("📊 Strategy Performance")

con_log = load_log("logs/conservative.log")
agg_log = load_log("logs/aggressive.log")

col_con, col_agg = st.columns(2)

def render_strategy_stats(df: pd.DataFrame, name: str, config: dict, col):
    with col:
        st.markdown(f"### {'🛡️' if name == 'Conservative' else '⚡'} {name}")

        if df.empty:
            st.info("No trades logged yet.")
            return

        trades    = df[df["action"].isin(["BUY", "SELL"])]
        total     = len(trades)
        buys      = len(trades[trades["action"] == "BUY"])
        holds     = len(df[df["action"] == "HOLD"])
        stops     = len(df[df["action"].isin(["STOP_ALL", "STOP_TODAY"])])

        # Kill switch status
        is_killed  = not df[df["action"] == "STOP_ALL"].empty
        is_stopped = not df[df["action"] == "STOP_TODAY"].empty

        status = "🔴 KILLED" if is_killed else ("🟡 STOPPED TODAY" if is_stopped else "🟢 ACTIVE")
        st.markdown(f"**Status:** {status}")

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Trades", total)
        m2.metric("Buys",         buys)
        m3.metric("HOLDs",        holds)

        if stops:
            st.warning(f"⚠️ {stops} stop event(s) triggered")

        # Recent decisions
        st.markdown("**Recent Decisions:**")
        recent = df.tail(10)[["timestamp", "action", "symbol", "reason", "regime", "confidence"]].copy()
        recent["timestamp"] = recent["timestamp"].dt.strftime("%m/%d %H:%M")
        st.dataframe(recent, use_container_width=True, hide_index=True)

render_strategy_stats(con_log, "Conservative", CONSERVATIVE, col_con)
render_strategy_stats(agg_log, "Aggressive",   AGGRESSIVE,   col_agg)

# ============================================================
# TRADE HISTORY CHART
# ============================================================

st.divider()
st.subheader("📈 Decision Timeline")

def build_timeline(df: pd.DataFrame, name: str, color: str):
    if df.empty:
        return None

    trades = df[df["action"].isin(["BUY", "SELL"])].copy()
    if trades.empty:
        return None

    return go.Scatter(
        x=trades["timestamp"],
        y=[name] * len(trades),
        mode="markers+text",
        marker=dict(
            size=12,
            color=[
                "#22c55e" if a == "BUY" else "#ef4444"
                for a in trades["action"]
            ],
            symbol=[
                "triangle-up" if a == "BUY" else "triangle-down"
                for a in trades["action"]
            ],
        ),
        text=trades.get("symbol", ""),
        textposition="top center",
        name=name,
        hovertemplate=(
            "<b>%{text}</b><br>"
            "%{x}<br>"
            "<extra></extra>"
        ),
    )

fig = go.Figure()
con_trace = build_timeline(con_log, "Conservative", "#3b82f6")
agg_trace = build_timeline(agg_log, "Aggressive",   "#f59e0b")

if con_trace:
    fig.add_trace(con_trace)
if agg_trace:
    fig.add_trace(agg_trace)

if con_trace or agg_trace:
    fig.update_layout(
        height=250,
        showlegend=True,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(showgrid=False),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
        margin=dict(l=0, r=0, t=20, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trades to display yet. Chart will populate as the bot makes decisions.")

# ============================================================
# REGIME BREAKDOWN
# ============================================================

st.divider()
st.subheader("🌊 Market Regime Breakdown")

col_r1, col_r2 = st.columns(2)

def render_regime_breakdown(df: pd.DataFrame, name: str, col):
    with col:
        st.markdown(f"**{name}**")
        if df.empty or "regime" not in df.columns:
            st.info("No data yet.")
            return

        regime_counts = df["regime"].value_counts()
        fig = go.Figure(go.Pie(
            labels=regime_counts.index,
            values=regime_counts.values,
            hole=0.4,
            marker_colors=["#3b82f6", "#f59e0b", "#6b7280"],
        ))
        fig.update_layout(
            height=250,
            showlegend=True,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

render_regime_breakdown(con_log, "Conservative", col_r1)
render_regime_breakdown(agg_log, "Aggressive",   col_r2)

# ============================================================
# FULL LOG TABLE
# ============================================================

st.divider()
with st.expander("📄 Full Decision Log"):
    all_logs = []
    if not con_log.empty:
        all_logs.append(con_log)
    if not agg_log.empty:
        all_logs.append(agg_log)

    if all_logs:
        combined = pd.concat(all_logs).sort_values("timestamp", ascending=False)
        combined["timestamp"] = combined["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(combined, use_container_width=True, hide_index=True)
    else:
        st.info("No decisions logged yet.")

# ============================================================
# AUTO REFRESH
# ============================================================

st.divider()
st.caption("Dashboard auto-refreshes every 5 minutes.")

if st.button("🔄 Refresh Now"):
    st.rerun()

# Auto-refresh every 5 minutes
st.markdown(
    """
    <script>
    setTimeout(function() { window.location.reload(); }, 300000);
    </script>
    """,
    unsafe_allow_html=True,
)
