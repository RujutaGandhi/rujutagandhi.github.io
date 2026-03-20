"""
main.py
=======
Runs both strategies every hour in parallel.
Includes a health check endpoint so Render Web Service
doesn't spin down — same pattern as USPS chatbot.

Usage:
    python3 main.py

Deployment:
    Render Web Service — start command: python3 main.py
    Keep alive: cron-job.org pinging /health every 10 minutes
"""

import logging
import os
import threading
import time
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from shared.config import validate_config, CONSERVATIVE, AGGRESSIVE, ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE, ALPACA_API_KEY_AGGRESSIVE, ALPACA_SECRET_KEY_AGGRESSIVE
from shared.alpaca_client import AlpacaClient
from shared.risk_guardian import run_risk_checks
from shared.alerts import alert_bot_started, alert_error
from shared.review import run_daily_review
from conservative.strategy import ConservativeStrategy
from aggressive.strategy import AggressiveStrategy

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ]
)
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ============================================================
# HEALTH CHECK SERVER
# Keeps Render Web Service alive — responds to pings on /health
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logs — keep bot logs clean


def run_health_server():
    """Runs a tiny HTTP server in a background thread."""
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"✅ Health server started on port {port}")
    server.serve_forever()


# ============================================================
# DECISION LOGGER
# ============================================================

def log_decisions(strategy_name: str, decisions: list):
    """Appends decisions to the strategy's JSON log file."""
    log_file = (
        "logs/conservative.log" if strategy_name == "Conservative"
        else "logs/aggressive.log"
    )
    timestamp = datetime.now(ET).isoformat()
    with open(log_file, "a") as f:
        for decision in decisions:
            entry = {
                "timestamp": timestamp,
                "strategy":  strategy_name,
                **decision,
            }
            f.write(json.dumps(entry) + "\n")


# ============================================================
# STRATEGY RUNNER
# ============================================================

def run_strategy(strategy, strategy_name, alpaca, today_open_value):
    """Executes one cycle of a strategy with full risk checks."""
    try:
        portfolio_value = alpaca.get_portfolio_value()

        config = CONSERVATIVE if strategy_name == "Conservative" else AGGRESSIVE
        risk = run_risk_checks(
            strategy_name=strategy_name,
            portfolio_value=portfolio_value,
            today_open_value=today_open_value,
            config=config,
            is_killed=strategy.killed,
            is_stopped_today=strategy.stopped_today,
        )

        if risk["kill_switch"]:
            strategy.killed = True
            alpaca.cancel_all_orders()
            alpaca.close_all_positions()
            logger.critical(f"[{strategy_name}] 🔴 Killed. Reason: {risk['reason']}")
            return

        if risk["daily_stop"]:
            strategy.stopped_today = True
            logger.warning(f"[{strategy_name}] 🟡 Stopped today. Reason: {risk['reason']}")
            return

        if not risk["can_trade"]:
            logger.info(f"[{strategy_name}] ⏸  Skipping cycle. Reason: {risk['reason']}")
            return

        logger.info(f"[{strategy_name}] 🔄 Running cycle — Portfolio: ${portfolio_value:,.2f}")
        decisions = strategy.run_cycle()

        if decisions:
            log_decisions(strategy_name, decisions)
            for d in decisions:
                logger.info(
                    f"[{strategy_name}] Decision: {d.get('action')} {d.get('symbol', '')} "
                    f"— {d.get('reason', '')}"
                )
        else:
            # Log a cycle heartbeat so the dashboard has data to show
            log_decisions(strategy_name, [{
                "action":     "HOLD",
                "symbol":     None,
                "reason":     "No eligible setups this cycle",
                "regime":     "N/A",
                "confidence": "N/A",
            }])
            logger.info(f"[{strategy_name}] No trades this cycle.")

    except Exception as e:
        logger.error(f"[{strategy_name}] ❌ Cycle error: {e}", exc_info=True)
        alert_error(strategy_name, str(e))


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    logger.info("🚀 Trading bot starting up...")

    # Validate all API keys
    validate_config()

    # Start health server in background thread (keeps Render alive)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Initialize Alpaca clients — one per strategy
    alpaca_conservative = AlpacaClient(
        api_key=ALPACA_API_KEY_CONSERVATIVE,
        secret_key=ALPACA_SECRET_KEY_CONSERVATIVE,
    )
    alpaca_aggressive = AlpacaClient(
        api_key=ALPACA_API_KEY_AGGRESSIVE,
        secret_key=ALPACA_SECRET_KEY_AGGRESSIVE,
    )

    # Initialize strategies
    conservative = ConservativeStrategy(alpaca_conservative)
    aggressive   = AggressiveStrategy(alpaca_aggressive)

    # Get starting values
    con_value = alpaca_conservative.get_portfolio_value()
    agg_value = alpaca_aggressive.get_portfolio_value()
    today_open_values = {
        "conservative": con_value,
        "aggressive":   agg_value,
    }
    last_reset_date = datetime.now(ET).date()

    logger.info(f"💰 Conservative starting value: ${con_value:,.2f}")
    logger.info(f"💰 Aggressive starting value:   ${agg_value:,.2f}")
    logger.info(f"📊 Conservative kill switch:    ${CONSERVATIVE['portfolio_floor']:,.2f}")
    logger.info(f"📊 Aggressive kill switch:      ${AGGRESSIVE['portfolio_floor']:,.2f}")

    # Startup email confirmations
    alert_bot_started("Conservative", con_value)
    alert_bot_started("Aggressive",   agg_value)

    # ============================================================
    # MAIN LOOP
    # ============================================================
    while True:
        now = datetime.now(ET)

        # Reset daily values at midnight
        if now.date() != last_reset_date:
            today_open_values = {
                "conservative": alpaca_conservative.get_portfolio_value(),
                "aggressive":   alpaca_aggressive.get_portfolio_value(),
            }
            last_reset_date = now.date()
            logger.info(
                f"📅 New day — "
                f"Conservative: ${today_open_values['conservative']:,.2f} | "
                f"Aggressive: ${today_open_values['aggressive']:,.2f}"
            )

        # Daily review at 4:05pm ET (after market close)
        if now.hour == 16 and now.minute == 5 and now.second < 60:
            logger.info("📊 Triggering end-of-day review...")
            run_daily_review(alpaca_conservative, alpaca_aggressive)
            # Sleep 61 seconds so this only fires once
            time.sleep(61)

        # Hourly trading cycle at :00
        elif now.minute == 0 and now.second < 60:
            logger.info("=" * 60)
            logger.info(f"⏰ Hourly cycle — {now.strftime('%Y-%m-%d %H:%M ET')}")
            logger.info("=" * 60)

            con_thread = threading.Thread(
                target=run_strategy,
                args=(conservative, "Conservative", alpaca_conservative, today_open_values["conservative"]),
                daemon=True,
            )
            agg_thread = threading.Thread(
                target=run_strategy,
                args=(aggressive, "Aggressive", alpaca_aggressive, today_open_values["aggressive"]),
                daemon=True,
            )
            con_thread.start()
            agg_thread.start()
            con_thread.join(timeout=300)
            agg_thread.join(timeout=300)
            logger.info("✅ Hourly cycle complete.")

            if conservative.killed and aggressive.killed:
                logger.critical("🔴 Both strategies killed. Bot shutting down.")
                break

            # Sleep 61 seconds to avoid double-firing
            time.sleep(61)

        else:
            # Check every 30 seconds
            time.sleep(30)


if __name__ == "__main__":
    main()
