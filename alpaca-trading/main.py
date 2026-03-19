"""
main.py
=======
Runs both strategies every hour in parallel.
This is the entry point — run this file to start the bot.

Usage:
    python main.py

Deployment:
    On Render, set the start command to: python main.py
"""

import logging
import threading
import time
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.config import validate_config, CONSERVATIVE, AGGRESSIVE, ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE, ALPACA_API_KEY_AGGRESSIVE, ALPACA_SECRET_KEY_AGGRESSIVE
from shared.alpaca_client import AlpacaClient
from shared.risk_guardian import run_risk_checks
from shared.alerts import alert_bot_started, alert_error
from conservative.strategy import ConservativeStrategy
from aggressive.strategy import AggressiveStrategy

from shared.review import run_daily_review
from shared.state import get_settings

# ============================================================
# LOGGING SETUP
# Logs to both console and individual strategy log files
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),                         # Console (visible on Render)
        logging.FileHandler("logs/bot.log"),             # Master log
    ]
)
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ============================================================
# STRATEGY LOG FILES
# Each strategy writes its own decision log as JSON lines
# Easy to parse for the dashboard
# ============================================================

def log_decisions(strategy_name: str, decisions: list[dict]):
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
# SINGLE STRATEGY RUNNER
# Runs in its own thread so both strategies run in parallel
# ============================================================

def run_strategy(
    strategy,
    strategy_name: str,
    alpaca: AlpacaClient,
    today_open_value: float,
):
    """
    Executes one cycle of a strategy with full risk checks.
    Designed to run in a thread.
    """
    try:
        portfolio_value = alpaca.get_portfolio_value()

        # Run risk checks before anything else
        config = CONSERVATIVE if strategy_name == "Conservative" else AGGRESSIVE
        risk = run_risk_checks(
            strategy_name=strategy_name,
            portfolio_value=portfolio_value,
            today_open_value=today_open_value,
            config=config,
            is_killed=strategy.killed,
            is_stopped_today=strategy.stopped_today,
        )

        # Update strategy flags from risk check results
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

        # Run strategy cycle
        logger.info(f"[{strategy_name}] 🔄 Running cycle — Portfolio: ${portfolio_value:,.2f}")
        decisions = strategy.run_cycle()

        # Log decisions
        if decisions:
            log_decisions(strategy_name, decisions)
            for d in decisions:
                logger.info(
                    f"[{strategy_name}] Decision: {d.get('action')} {d.get('symbol', '')} "
                    f"— {d.get('reason', '')}"
                )
        else:
            logger.info(f"[{strategy_name}] No trades this cycle.")

    except Exception as e:
        logger.error(f"[{strategy_name}] ❌ Cycle error: {e}", exc_info=True)
        alert_error(strategy_name, str(e))


# ============================================================
# HOURLY SCHEDULER
# Runs both strategies at the top of every hour
# ============================================================

def run_hourly_cycle(
    conservative: ConservativeStrategy,
    aggressive: AggressiveStrategy,
    alpaca: AlpacaClient,
    today_open_values: dict,
):
    """Runs both strategies in parallel threads."""
    logger.info("=" * 60)
    logger.info(f"⏰  Hourly cycle starting — {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    logger.info("=" * 60)

    # Run both strategies simultaneously in separate threads
    con_thread = threading.Thread(
        target=run_strategy,
        args=(conservative, "Conservative", alpaca, today_open_values["conservative"]),
        daemon=True,
    )
    agg_thread = threading.Thread(
        target=run_strategy,
        args=(aggressive, "Aggressive", alpaca, today_open_values["aggressive"]),
        daemon=True,
    )

    con_thread.start()
    agg_thread.start()

    # Wait for both to finish before next cycle
    con_thread.join(timeout=300)  # 5 min timeout per cycle
    agg_thread.join(timeout=300)

    logger.info("✅ Hourly cycle complete.")


# ============================================================
# DAILY OPEN VALUE TRACKER
# Resets at midnight ET each day
# ============================================================

def get_today_open_values(alpaca: AlpacaClient) -> dict:
    """Fetches current portfolio value to use as today's open."""
    value = alpaca.get_portfolio_value()
    return {
        "conservative": value,
        "aggressive":   value,
    }


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    logger.info("🚀 Trading bot starting up...")

    # Validate all API keys are present
    validate_config()

    # Initialize separate Alpaca clients — one per strategy, one per account
    alpaca_conservative = AlpacaClient(
        api_key=ALPACA_API_KEY_CONSERVATIVE,
        secret_key=ALPACA_SECRET_KEY_CONSERVATIVE,
    )
    alpaca_aggressive = AlpacaClient(
        api_key=ALPACA_API_KEY_AGGRESSIVE,
        secret_key=ALPACA_SECRET_KEY_AGGRESSIVE,
    )

    # Initialize both strategies with their own Alpaca client
    conservative = ConservativeStrategy(alpaca_conservative)
    aggressive   = AggressiveStrategy(alpaca_aggressive)

    # Get starting portfolio values per account
    con_value           = alpaca_conservative.get_portfolio_value()
    agg_value           = alpaca_aggressive.get_portfolio_value()
    today_open_values   = {
        "conservative": con_value,
        "aggressive":   agg_value,
    }
    last_reset_date = datetime.now(ET).date()

    logger.info(f"💰 Conservative starting value: ${con_value:,.2f}")
    logger.info(f"💰 Aggressive starting value:   ${agg_value:,.2f}")
    logger.info(f"📊 Conservative kill switch:    ${CONSERVATIVE['portfolio_floor']:,.2f}")
    logger.info(f"📊 Aggressive kill switch:      ${AGGRESSIVE['portfolio_floor']:,.2f}")

    # Send startup confirmation emails
    alert_bot_started("Conservative", con_value)
    alert_bot_started("Aggressive",   agg_value)

    # ============================================================
    # MAIN LOOP — runs forever until killed
    # ============================================================
    while True:
        now = datetime.now(ET)

        # Reset daily open values at midnight
        if now.date() != last_reset_date:
            today_open_values = {
                "conservative": alpaca_conservative.get_portfolio_value(),
                "aggressive":   alpaca_aggressive.get_portfolio_value(),
            }
            last_reset_date = now.date()
            logger.info(
                f"📅 New day — Conservative: ${today_open_values['conservative']:,.2f} | "
                f"Aggressive: ${today_open_values['aggressive']:,.2f}"
            )

        # Run daily review at 4:05pm ET (after market close)
        if now.hour == 16 and now.minute == 5 and now.second < 60:
            logger.info("📊 Triggering end-of-day review...")
            run_daily_review(alpaca_conservative, alpaca_aggressive)
            time.sleep(61)  # Prevent double-firing
        
        # Run hourly cycle at the top of each hour (:00)
        # Check every 60 seconds to avoid drift
        if now.minute == 0 and now.second < 60:
            # Run both strategies with their own Alpaca clients
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

            # Stop if both strategies are killed
            if conservative.killed and aggressive.killed:
                logger.critical("🔴 Both strategies killed. Bot shutting down.")
                break

            # Wait 61 seconds to avoid double-firing at :00
            time.sleep(61)
        else:
            # Sleep 30 seconds between checks
            time.sleep(30)


if __name__ == "__main__":
    main()
