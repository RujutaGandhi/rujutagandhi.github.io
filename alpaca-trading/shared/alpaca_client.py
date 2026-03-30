"""
shared/alpaca_client.py
=======================
Handles all communication with Alpaca.
Phase 7 additions: short selling methods (ETF/index only).
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List

import pandas as pd
import requests as req
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    CryptoBarsRequest,
    StockLatestQuoteRequest,
    CryptoLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame

from shared.config import ALPACA_BASE_URL

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class AlpacaClient:

    def __init__(self, api_key: str, secret_key: str):
        self._api_key    = api_key
        self._secret_key = secret_key
        self.trading = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
        )
        self.stock_data = StockHistoricalDataClient(
            api_key=api_key, secret_key=secret_key,
        )
        self.crypto_data = CryptoHistoricalDataClient(
            api_key=api_key, secret_key=secret_key,
        )
        logger.info("✅ Alpaca client initialized (paper trading mode)")

    # ============================================================
    # ACCOUNT
    # ============================================================

    def get_account(self):
        return self.trading.get_account()

    def get_portfolio_value(self) -> float:
        return float(self.trading.get_account().portfolio_value)

    def get_cash(self) -> float:
        return float(self.trading.get_account().cash)

    def get_positions(self) -> list:
        return self.trading.get_all_positions()

    def get_position_symbols(self) -> List[str]:
        return [p.symbol for p in self.get_positions()]

    def get_short_positions(self) -> list:
        """Returns only short positions (qty < 0)."""
        return [p for p in self.get_positions() if float(p.qty) < 0]

    # ============================================================
    # MARKET DATA
    # ============================================================

    def get_stock_bars(self, symbol: str, lookback_days: int = 30,
                       timeframe: TimeFrame = TimeFrame.Hour) -> pd.DataFrame:
        try:
            start   = datetime.now(ET) - timedelta(days=lookback_days)
            request = StockBarsRequest(
                symbol_or_symbols=symbol, timeframe=timeframe, start=start,
            )
            bars = self.stock_data.get_stock_bars(request)
            df   = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            logger.error(f"❌ Stock bars failed for {symbol}: {e}")
            return pd.DataFrame()

    def get_crypto_bars(self, symbol: str, lookback_days: int = 30,
                        timeframe: TimeFrame = TimeFrame.Hour) -> pd.DataFrame:
        try:
            start   = datetime.now(ET) - timedelta(days=lookback_days)
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol, timeframe=timeframe, start=start,
            )
            bars = self.crypto_data.get_crypto_bars(request)
            df   = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            logger.error(f"❌ Crypto bars failed for {symbol}: {e}")
            return pd.DataFrame()

    def get_stock_price(self, symbol: str) -> Optional[float]:
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote   = self.stock_data.get_stock_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            logger.error(f"❌ Stock price failed for {symbol}: {e}")
            return None

    def get_crypto_price(self, symbol: str) -> Optional[float]:
        try:
            request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote   = self.crypto_data.get_crypto_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            logger.error(f"❌ Crypto price failed for {symbol}: {e}")
            return None

    # ============================================================
    # LONG ORDERS (existing)
    # ============================================================

    def place_limit_order(self, symbol: str, side: str, qty: float,
                          limit_price: float, take_profit: float,
                          stop_loss: float) -> Optional[dict]:
        try:
            order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            order_data = LimitOrderRequest(
                symbol=symbol, qty=qty, side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=round(limit_price, 2),
                order_class="bracket",
                take_profit={"limit_price": round(take_profit, 2)},
                stop_loss={"stop_price": round(stop_loss, 2)},
            )
            order = self.trading.submit_order(order_data)
            logger.info(
                f"✅ Order: {side.upper()} {qty} {symbol} "
                f"@ ${limit_price:.2f} | TP: ${take_profit:.2f} | SL: ${stop_loss:.2f}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Order failed for {symbol}: {e}")
            return None

    def place_crypto_stop_sell(self, symbol: str, qty: float) -> Optional[dict]:
        try:
            order_data = MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
            )
            order = self.trading.submit_order(order_data)
            logger.info(f"✅ Crypto stop sell: {qty} {symbol}")
            return order
        except Exception as e:
            logger.error(f"❌ Crypto stop sell failed for {symbol}: {e}")
            return None

    def cancel_all_orders(self):
        try:
            self.trading.cancel_orders()
            logger.info("✅ All orders cancelled.")
        except Exception as e:
            logger.error(f"❌ Cancel orders failed: {e}")

    def close_all_positions(self):
        try:
            self.trading.close_all_positions(cancel_orders=True)
            logger.info("✅ All positions closed.")
        except Exception as e:
            logger.error(f"❌ Close positions failed: {e}")

    def get_open_orders(self) -> list:
        try:
            return self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        except Exception as e:
            logger.error(f"❌ Get open orders failed: {e}")
            return []

    # ============================================================
    # SHORT SELLING (Phase 7 — ETF/index only)
    # ============================================================

    def check_etb(self, symbol: str) -> bool:
        """
        Checks if a symbol is Easy-To-Borrow (ETB) — required for shorting.
        SPY and QQQ are almost always ETB, but we verify before every short.
        """
        try:
            asset = self.trading.get_asset(symbol)
            etb   = getattr(asset, "easy_to_borrow", True)
            if not etb:
                logger.warning(f"⚠️  {symbol} is NOT easy-to-borrow — cannot short")
            return bool(etb)
        except Exception as e:
            logger.error(f"❌ ETB check failed for {symbol}: {e}")
            return False  # Fail safe — don't short if we can't verify

    def place_short_order(self, symbol: str, qty: float) -> Optional[dict]:
        """
        Opens a short position by selling shares we don't own.
        ETF/index only (SPY, QQQ). Simple market order — no bracket
        (we manage stops manually via _check_short_stops in strategy).

        Args:
            symbol: ETF to short (SPY or QQQ only)
            qty:    Number of shares to short
        """
        try:
            # Verify ETB before placing
            if not self.check_etb(symbol):
                return None

            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(order_data)
            logger.info(f"✅ Short opened: SELL {qty} {symbol} (short)")
            return order
        except Exception as e:
            logger.error(f"❌ Short order failed for {symbol}: {e}")
            return None

    def cover_short(self, symbol: str, qty: float) -> Optional[dict]:
        """
        Closes a short position by buying back the shares.

        Args:
            symbol: ETF to cover (SPY or QQQ)
            qty:    Number of shares to buy back (use abs value)
        """
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=abs(qty),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(order_data)
            logger.info(f"✅ Short covered: BUY {qty} {symbol} (cover)")
            return order
        except Exception as e:
            logger.error(f"❌ Cover short failed for {symbol}: {e}")
            return None

    def get_total_short_exposure(self) -> float:
        """
        Returns total dollar value of all short positions.
        Used to enforce max_short_exposure_pct limit.
        """
        try:
            shorts = self.get_short_positions()
            return sum(abs(float(p.market_value)) for p in shorts)
        except Exception as e:
            logger.error(f"❌ Short exposure check failed: {e}")
            return 0.0

    # ============================================================
    # DASHBOARD METHODS
    # ============================================================

    def get_closed_orders(self, days_back: int = 30) -> list:
        try:
            after   = datetime.now(ET) - timedelta(days=days_back)
            request = GetOrdersRequest(
                status=QueryOrderStatus.CLOSED, after=after, limit=100,
            )
            orders = self.trading.get_orders(request)
            return [o for o in orders if str(o.status) in ("filled", "OrderStatus.FILLED")]
        except Exception as e:
            logger.error(f"❌ Closed orders failed: {e}")
            return []

    def get_portfolio_history(self, days_back: int = 30) -> pd.DataFrame:
        try:
            headers = {
                "APCA-API-KEY-ID":     self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
            }
            url      = f"{ALPACA_BASE_URL}/v2/account/portfolio/history"
            params   = {"period": f"{days_back}D", "timeframe": "1D",
                        "intraday_reporting": "market_hours"}
            response = req.get(url, headers=headers, params=params, timeout=10)
            if response.status_code != 200:
                return pd.DataFrame()
            data       = response.json()
            timestamps = data.get("timestamp", [])
            equity     = data.get("equity", [])
            if not timestamps or not equity:
                return pd.DataFrame()
            df = pd.DataFrame({
                "date":  pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(ET),
                "value": equity,
            })
            return df.dropna()
        except Exception as e:
            logger.error(f"❌ Portfolio history failed: {e}")
            return pd.DataFrame()

    # ============================================================
    # HELPERS
    # ============================================================

    def is_crypto(self, symbol: str) -> bool:
        return "/" in symbol

    def get_bars(self, symbol: str, lookback_days: int = 30) -> pd.DataFrame:
        if self.is_crypto(symbol):
            return self.get_crypto_bars(symbol, lookback_days)
        return self.get_stock_bars(symbol, lookback_days)

    def get_price(self, symbol: str) -> Optional[float]:
        if self.is_crypto(symbol):
            return self.get_crypto_price(symbol)
        return self.get_stock_price(symbol)

    def calculate_qty(self, symbol: str, portfolio_value: float,
                      position_pct: float, price: float) -> float:
        dollar_amount = portfolio_value * position_pct
        qty = dollar_amount / price
        if self.is_crypto(symbol):
            return round(qty, 6)
        return round(qty, 2)
