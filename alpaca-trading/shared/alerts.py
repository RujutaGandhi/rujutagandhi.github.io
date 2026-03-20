"""
shared/alerts.py
================
Sends email alerts when kill switches trigger.

Uses SendGrid API (HTTP) — works on Render free tier.
SendGrid key restricted to Mail Send only for security.
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from shared.config import ALERT_EMAIL_FROM, ALERT_EMAIL_TO

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_email(subject: str, body: str) -> bool:
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.error("❌ SENDGRID_API_KEY not set — cannot send email")
        return False
    try:
        payload = {
            "personalizations": [{"to": [{"email": ALERT_EMAIL_TO}]}],
            "from":    {"email": ALERT_EMAIL_FROM},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        response = requests.post(
            SENDGRID_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=10,
        )
        if response.status_code in (200, 202):
            logger.info(f"✅ Alert sent: {subject}")
            return True
        else:
            logger.error(f"❌ SendGrid error {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Failed to send alert: {e}")
        return False


def alert_bot_started(strategy_name: str, starting_value: float):
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
  - Daily review completes with adjustments

To stop the bot, suspend the service on Render.
    """.strip()
    send_email(subject, body)


def alert_daily_stop(strategy_name, portfolio_value, daily_loss_pct, threshold_pct):
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
    """.strip()
    send_email(subject, body)


def alert_kill_switch(strategy_name, portfolio_value, floor_value):
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    subject = f"🔴 [{strategy_name}] KILL SWITCH — Trading Halted Permanently"
    body = f"""
⚠️  KILL SWITCH TRIGGERED — ALL TRADING HALTED PERMANENTLY

Strategy:        {strategy_name}
Time:            {now}
Portfolio value: ${portfolio_value:,.2f}
Floor threshold: ${floor_value:,.2f}

The bot has cancelled all orders and closed all positions.
To restart, redeploy on Render and reset your Alpaca paper account.
    """.strip()
    send_email(subject, body)


def alert_trade_executed(strategy_name, action, symbol, qty, price, stop_loss, take_profit, reason):
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


def alert_error(strategy_name, error_msg):
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
