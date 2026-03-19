"""
shared/alerts.py
================
Sends email alerts when kill switches trigger.

Triggers:
- Portfolio value drops below floor ($700 conservative / $600 aggressive)
- Daily loss exceeds threshold (15% conservative / 20% aggressive)
- Bot starts up (confirmation it's running)
- Bot shuts down (confirmation it stopped)

Uses Gmail SMTP with App Password from .env
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.config import (
    ALERT_EMAIL_FROM,
    ALERT_EMAIL_PASSWORD,
    ALERT_EMAIL_TO,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ============================================================
# CORE EMAIL SENDER
# ============================================================

def send_email(subject: str, body: str) -> bool:
    """
    Sends a plain-text email via Gmail SMTP.

    Returns True if sent successfully, False if failed.
    Failure is logged but never crashes the bot —
    a failed alert should not stop trading.
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = ALERT_EMAIL_FROM
        msg["To"]      = ALERT_EMAIL_TO

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASSWORD)
            server.sendmail(ALERT_EMAIL_FROM, ALERT_EMAIL_TO, msg.as_string())

        logger.info(f"✅ Alert sent: {subject}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send alert: {e}")
        return False


# ============================================================
# SPECIFIC ALERT TYPES
# ============================================================

def alert_bot_started(strategy_name: str, starting_value: float):
    """Sent when bot starts — confirms it's live and running."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"🟢 [{strategy_name}] Trading Bot Started"
    body = f"""
Your {strategy_name} trading bot has started successfully.

Started at:      {now}
Starting value:  ${starting_value:,.2f}
Mode:            Paper Trading (no real money)

You will receive alerts if:
  - Portfolio drops below the kill switch floor
  - Daily losses exceed the stop threshold

To stop the bot, shut down your Render service.
    """.strip()
    send_email(subject, body)


def alert_daily_stop(
    strategy_name: str,
    portfolio_value: float,
    daily_loss_pct: float,
    threshold_pct: float,
):
    """Sent when daily loss limit is hit — bot stops for the day."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"🟡 [{strategy_name}] Daily Stop Triggered"
    body = f"""
DAILY STOP TRIGGERED — No more trades today.

Strategy:        {strategy_name}
Time:            {now}
Portfolio value: ${portfolio_value:,.2f}
Daily loss:      {daily_loss_pct:.1f}%
Threshold:       {threshold_pct:.0f}%

The bot will resume trading tomorrow at market open.
No positions have been closed — existing stop-losses remain active.
    """.strip()
    send_email(subject, body)


def alert_kill_switch(
    strategy_name: str,
    portfolio_value: float,
    floor_value: float,
):
    """
    Sent when portfolio drops below the floor.
    This is permanent — bot will NOT restart.
    """
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"🔴 [{strategy_name}] KILL SWITCH — Trading Halted Permanently"
    body = f"""
⚠️  KILL SWITCH TRIGGERED — ALL TRADING HALTED PERMANENTLY

Strategy:        {strategy_name}
Time:            {now}
Portfolio value: ${portfolio_value:,.2f}
Floor threshold: ${floor_value:,.2f}

The bot has:
  ✓ Cancelled all open orders
  ✓ Closed all open positions
  ✓ Stopped permanently (will not restart)

To restart, you must manually redeploy on Render
and reset the paper trading account on Alpaca.

Review logs to understand what happened before restarting.
    """.strip()
    send_email(subject, body)


def alert_trade_executed(
    strategy_name: str,
    action: str,
    symbol: str,
    qty: float,
    price: float,
    stop_loss: float,
    take_profit: float,
    reason: str,
):
    """Optional — sent when a trade is placed. Useful for monitoring."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"📊 [{strategy_name}] Trade: {action} {symbol}"
    body = f"""
Trade executed on {strategy_name} strategy.

Action:      {action}
Symbol:      {symbol}
Quantity:    {qty}
Price:       ${price:,.4f}
Stop loss:   ${stop_loss:,.4f}
Take profit: ${take_profit:,.4f}
Time:        {now}

Reason: {reason}
    """.strip()
    send_email(subject, body)


def alert_error(strategy_name: str, error_msg: str):
    """Sent when an unexpected error occurs that needs attention."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"⚠️  [{strategy_name}] Bot Error"
    body = f"""
An error occurred in the {strategy_name} trading bot.

Time:  {now}
Error: {error_msg}

The bot will attempt to continue on the next cycle.
Check Render logs for full stack trace.
    """.strip()
    send_email(subject, body)
