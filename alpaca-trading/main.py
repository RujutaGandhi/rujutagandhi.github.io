"""
main.py
=======
Phase 7: Added combined portfolio kill switch before each cycle.
"""

import logging
import os
import threading
import time
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from shared.config import (
    validate_config, CONSERVATIVE, AGGRESSIVE,
    ALPACA_API_KEY_CONSERVATIVE, ALPACA_SECRET_KEY_CONSERVATIVE,
    ALPACA_API_KEY_AGGRESSIVE, ALPACA_SECRET_KEY_AGGRESSIVE,
    COMBINED_STARTING_CAPITAL,
)
from shared.alpaca_client import AlpacaClient
from shared.risk_guardian import run_risk_checks, check_combined_portfolio
from shared.alerts import alert_bot_started, alert_error
from shared.review import run_daily_review
from conservative.strategy import ConservativeStrategy
from aggressive.strategy import AggressiveStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log")],
)
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"✅ Health server started on port {port}")
    server.serve_forever()


def log_decisions(strategy_name: str, decisions: list):
    log_file = (
        "logs/conservative.log" if strategy_name == "Conservative"
        else "logs/aggressive.log"
    )
    timestamp = datetime.now(ET).isoformat()
    with open(log_file, "a") as f:
        for decision in decisions:
            entry = {"timestamp": timestamp, "strategy": strategy_name, **decision}
            f.write(json.dumps(entry) + "\n")


def run_strategy(strategy, strategy_name, alpaca, today_open_value):
    try:
        portfolio_value = alpaca.get_portfolio_value()
        config = CONSERVATIVE if strategy_name == "Conservative" else AGGRESSIVE
        risk   = run_risk_checks(
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
            logger.critical(f"[{strategy_name}] 🔴 Killed. {risk['reason']}")
            return

        if risk["daily_stop"]:
            strategy.stopped_today = True
            logger.warning(f"[{strategy_name}] 🟡 Stopped today. {risk['reason']}")
            return

        if not risk["can_trade"]:
            logger.info(f"[{strategy_name}] ⏸  Skipping. {risk['reason']}")
            return

        logger.info(f"[{strategy_name}] 🔄 Running cycle — Portfolio: ${portfolio_value:,.2f}")
        decisions = strategy.run_cycle()

        if decisions:
            log_decisions(strategy_name, decisions)
            for d in decisions:
                logger.info(
                    f"[{strategy_name}] Decision: {d.get('action')} "
                    f"{d.get('symbol', '')} — {d.get('reason', '')}"
                )
        else:
            log_decisions(strategy_name, [{
                "action": "HOLD", "symbol": None,
                "reason": "No eligible setups this cycle",
                "regime": "N/A", "confidence": "N/A",
            }])
            logger.info(f"[{strategy_name}] No trades this cycle.")

    except Exception as e:
        logger.error(f"[{strategy_name}] ❌ Cycle error: {e}", exc_info=True)
        alert_error(strategy_name, str(e))


def main():
    logger.info("🚀 Trading bot starting up...")
    validate_config()

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    alpaca_conservative = AlpacaClient(
        api_key=ALPACA_API_KEY_CONSERVATIVE,
        secret_key=ALPACA_SECRET_KEY_CONSERVATIVE,
    )
    alpaca_aggressive = AlpacaClient(
        api_key=ALPACA_API_KEY_AGGRESSIVE,
        secret_key=ALPACA_SECRET_KEY_AGGRESSIVE,
    )

    conservative = ConservativeStrategy(alpaca_conservative)
    aggressive   = AggressiveStrategy(alpaca_aggressive)

    con_value = alpaca_conservative.get_portfolio_value()
    agg_value = alpaca_aggressive.get_portfolio_value()

    today_open_values = {
        "conservative":       con_value,
        "aggressive":         agg_value,
        "combined":           con_value + agg_value,
    }
    last_reset_date = datetime.now(ET).date()

    # Track if combined kill switch has fired
    combined_halted       = False
    combined_stopped_today = False

    logger.info(f"💰 Conservative: ${con_value:,.2f} | Aggressive: ${agg_value:,.2f}")
    logger.info(f"💰 Combined: ${con_value + agg_value:,.2f} | Floor: $1,700.00")

    alert_bot_started("Conservative", con_value)
    alert_bot_started("Aggressive",   agg_value)

    while True:
        now = datetime.now(ET)

        # Reset daily values at midnight
        if now.date() != last_reset_date:
            con_val = alpaca_conservative.get_portfolio_value()
            agg_val = alpaca_aggressive.get_portfolio_value()
            today_open_values = {
                "conservative": con_val,
                "aggressive":   agg_val,
                "combined":     con_val + agg_val,
            }
            last_reset_date        = now.date()
            combined_stopped_today = False
            logger.info(
                f"📅 New day — Con: ${con_val:,.2f} | "
                f"Agg: ${agg_val:,.2f} | Combined: ${con_val + agg_val:,.2f}"
            )

        # Daily review at 4:05pm ET
        if now.hour == 16 and now.minute == 5 and now.second < 60:
            logger.info("📊 Triggering end-of-day review...")
            run_daily_review(alpaca_conservative, alpaca_aggressive)
            time.sleep(61)

        # Hourly trading cycle
        elif now.minute == 0 and now.second < 60:
            logger.info("=" * 60)
            logger.info(f"⏰ Hourly cycle — {now.strftime('%Y-%m-%d %H:%M ET')}")
            logger.info("=" * 60)

            # ── COMBINED PORTFOLIO CHECK (runs before either strategy) ──
            if not combined_halted and not combined_stopped_today:
                con_val = alpaca_conservative.get_portfolio_value()
                agg_val = alpaca_aggressive.get_portfolio_value()
                combined_check = check_combined_portfolio(
                    con_value=con_val,
                    agg_value=agg_val,
                    combined_today_open=today_open_values["combined"],
                )

                if combined_check["halt"]:
                    logger.critical(
                        f"🔴🔴 COMBINED HALT — {combined_check['reason']}"
                    )
                    # Determine if permanent or daily
                    if combined_check["combined_value"] <= 1700:
                        combined_halted = True
                        conservative.killed = True
                        aggressive.killed   = True
                        alpaca_conservative.cancel_all_orders()
                        alpaca_conservative.close_all_positions()
                        alpaca_aggressive.cancel_all_orders()
                        alpaca_aggressive.close_all_positions()
                    else:
                        combined_stopped_today = True

            # Skip cycle if combined halted
            if combined_halted:
                logger.critical("🔴🔴 Both strategies halted by combined kill switch.")
                break

            if not combined_stopped_today:
                con_thread = threading.Thread(
                    target=run_strategy,
                    args=(conservative, "Conservative",
                          alpaca_conservative, today_open_values["conservative"]),
                    daemon=True,
                )
                agg_thread = threading.Thread(
                    target=run_strategy,
                    args=(aggressive, "Aggressive",
                          alpaca_aggressive, today_open_values["aggressive"]),
                    daemon=True,
                )
                con_thread.start()
                agg_thread.start()
                con_thread.join(timeout=300)
                agg_thread.join(timeout=300)
                logger.info("✅ Hourly cycle complete.")
            else:
                logger.warning("🟡🟡 Combined daily stop active — skipping cycle.")

            if conservative.killed and aggressive.killed:
                logger.critical("🔴 Both strategies killed. Bot shutting down.")
                break

            time.sleep(61)

        else:
            time.sleep(30)


if __name__ == "__main__":
    main()
