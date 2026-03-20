"""
shared/state.py
===============
Persists Claude's daily adjustments between sessions.
Saves to state.json — survives bot restarts on Render.

Stores:
- Adjusted indicator thresholds per strategy
- Current strategy mode (TREND / RANGE / BOTH)
- Daily notes from Claude's review
- Adjustment history (last 14 days)

Default values are used on first run or if state is corrupted.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

STATE_FILE = Path("state.json")

# ============================================================
# DEFAULT STATE
# These are the baseline values before any self-tuning
# ============================================================

DEFAULT_STATE = {
    "conservative": {
        "rsi_buy_threshold":    30,    # RSI below this = oversold signal
        "rsi_sell_threshold":   70,    # RSI above this = overbought signal
        "volume_multiplier":    1.2,   # Volume must be Nx average
        "atr_stop_multiplier":  1.5,   # Stop = entry - (N × ATR)
        "strategy_mode":        "TREND",
        "score_threshold":      6,     # Minimum points to trade
        "notes":                "Default settings — no review yet",
        "last_updated":         None,
    },
    "aggressive": {
        "rsi_buy_threshold":    35,    # Slightly looser than conservative
        "rsi_sell_threshold":   65,
        "volume_multiplier":    1.1,
        "atr_stop_multiplier":  2.5,
        "strategy_mode":        "BOTH",
        "score_threshold":      4,
        "notes":                "Default settings — no review yet",
        "last_updated":         None,
    },
    "history": [],   # Last 14 days of adjustments
    "crypto_positions": {},
    "created_at": datetime.now(ET).isoformat(),
}

# Safe bounds — Claude cannot adjust beyond these limits
ADJUSTMENT_BOUNDS = {
    "rsi_buy_threshold":   (20, 40),
    "rsi_sell_threshold":  (60, 80),
    "volume_multiplier":   (1.0, 2.0),
    "atr_stop_multiplier": (1.0, 4.0),
    "score_threshold":     (3, 9),
}


# ============================================================
# LOAD STATE
# ============================================================

def load_state() -> dict:
    """
    Loads state from state.json.
    Returns default state if file doesn't exist or is corrupted.
    """
    if not STATE_FILE.exists():
        logger.info("📋 No state file found — using defaults")
        return DEFAULT_STATE.copy()

    try:
        with open(STATE_FILE) as f:
            state = json.load(f)

        # Merge with defaults to handle missing keys
        # (happens when new fields are added after deployment)
        for strategy in ("conservative", "aggressive"):
            for key, default_val in DEFAULT_STATE[strategy].items():
                if key not in state.get(strategy, {}):
                    state.setdefault(strategy, {})[key] = default_val

        logger.info("📋 State loaded successfully")
        return state

    except Exception as e:
        logger.error(f"❌ Failed to load state — using defaults: {e}")
        return DEFAULT_STATE.copy()


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state: dict) -> bool:
    """
    Saves state to state.json.
    Returns True on success, False on failure.
    """
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info("💾 State saved successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to save state: {e}")
        return False


# ============================================================
# APPLY ADJUSTMENTS
# ============================================================

def apply_adjustments(
    state:         dict,
    strategy_name: str,
    adjustments:   dict,
) -> dict:
    """
    Applies Claude's adjustments to state with safety bounds checking.
    Rejects any value outside defined bounds — Claude cannot go rogue.

    Args:
        state:         Current state dict
        strategy_name: "conservative" or "aggressive"
        adjustments:   Dict from Claude's daily review

    Returns:
        Updated state dict
    """
    key = strategy_name.lower()
    if key not in state:
        logger.error(f"❌ Unknown strategy: {strategy_name}")
        return state

    applied   = []
    rejected  = []
    today     = datetime.now(ET).isoformat()

    for field, new_value in adjustments.items():
        if field == "notes":
            state[key]["notes"] = str(new_value)[:200]  # Cap length
            applied.append(f"notes updated")
            continue

        if field == "strategy_mode":
            if new_value in ("TREND", "RANGE", "BOTH"):
                state[key]["strategy_mode"] = new_value
                applied.append(f"strategy_mode → {new_value}")
            else:
                rejected.append(f"strategy_mode invalid value: {new_value}")
            continue

        if field not in ADJUSTMENT_BOUNDS:
            rejected.append(f"{field} not adjustable")
            continue

        try:
            val = float(new_value)
            min_val, max_val = ADJUSTMENT_BOUNDS[field]

            if min_val <= val <= max_val:
                old_val = state[key].get(field)
                state[key][field] = val
                applied.append(f"{field}: {old_val} → {val}")
            else:
                rejected.append(
                    f"{field}={val} out of bounds [{min_val}, {max_val}]"
                )
        except (TypeError, ValueError):
            rejected.append(f"{field} invalid value: {new_value}")

    state[key]["last_updated"] = today

    # Add to history
    history_entry = {
        "date":     today[:10],
        "strategy": strategy_name,
        "applied":  applied,
        "rejected": rejected,
    }
    state.setdefault("history", []).append(history_entry)

    # Keep only last 14 days
    state["history"] = state["history"][-28:]  # 2 per day × 14 days

    if applied:
        logger.info(f"[{strategy_name}] ✅ Adjustments applied: {', '.join(applied)}")
    if rejected:
        logger.warning(f"[{strategy_name}] ⚠️  Adjustments rejected: {', '.join(rejected)}")

    return state


# ============================================================
# GET CURRENT SETTINGS
# ============================================================

def get_settings(strategy_name: str) -> dict:
    """
    Returns current settings for a strategy.
    Used at the start of each cycle to load adjusted thresholds.
    """
    state = load_state()
    return state.get(strategy_name.lower(), DEFAULT_STATE[strategy_name.lower()])


def save_crypto_position(symbol: str, entry_price: float, stop_price: float, qty: float, strategy: str):
    """Saves a crypto position entry for stop-loss tracking."""
    state = load_state()
    state.setdefault("crypto_positions", {})[symbol] = {
        "entry_price": entry_price,
        "stop_price":  stop_price,
        "qty":         qty,
        "strategy":    strategy,
        "opened_at":   datetime.now(ET).isoformat(),
    }
    save_state(state)
    logger.info(f"💾 Crypto position saved: {symbol} @ ${entry_price} stop @ ${stop_price}")


def remove_crypto_position(symbol: str):
    """Removes a crypto position after it's been closed."""
    state = load_state()
    state.setdefault("crypto_positions", {}).pop(symbol, None)
    save_state(state)
    logger.info(f"💾 Crypto position removed: {symbol}")


def get_crypto_positions() -> dict:
    """Returns all tracked crypto positions."""
    state = load_state()
    return state.get("crypto_positions", {})