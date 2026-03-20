"""
shared/alpaca_client.py
=======================
Handles all communication with Alpaca:
- Fetching live + historical prices
- Placing / cancelling orders
- Checking account balance and positions
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List

import pandas as pd
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
    """
    Single client used by one strategy.
    Each strategy gets its own instance with its own API keys.
    """

    def __init__(self, api_key: str, secret_key: str):
        # Trading client — places orders, checks account
        self.trading = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,  # ALWAYS paper trading — never real money
        )

        # Data clients — fetches price history and live quotes
        self.stock_data = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        self.crypto_data = CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

        logger.info("✅ Alpaca client initialized (paper trading mode)")

    # ============================================================
    # ACCOUNT
    # ============================================================

    def get_account(self):
        """Returns full account object with balance, buying power etc."""
        return self.trading.get_account()

    def get_portfolio_value(self) -> float:
        """Returns current total portfolio value in dollars."""
        account = self.get_account()
        return float(account.portfolio_value)

    def get_cash(self) -> float:
        """Returns available cash in dollars."""
        account = self.get_account()
        return float(account.cash)

    def get_positions(self) -> list:
        """Returns list of all open positions."""
        return self.trading.get_all_positions()

    def get_position_symbols(self) -> List[str]:
        """Returns list of symbols currently held."""
        return [p.symbol for p in self.get_positions()]

    # ============================================================
    # MARKET DATA — HISTORICAL (for indicators)
    # ============================================================

    def get_stock_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: TimeFrame = TimeFrame.Hour,
    ) -> pd.DataFrame:
        """
        Fetches historical OHLCV bars for a stock.
        Returns a DataFrame with columns: open, high, low, close, volume
        """
        try:
            start = datetime.now(ET) - timedelta(days=lookback_days)
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
            )
            bars = self.stock_data.get_stock_bars(request)
            df = bars.df

            # Flatten multi-index if present
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")

            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            return df

        except Exception as e:
            logger.error(f"❌ Failed to fetch stock bars for {symbol}: {e}")
            return pd.DataFrame()

    def get_crypto_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: TimeFrame = TimeFrame.Hour,
    ) -> pd.DataFrame:
        """
        Fetches historical OHLCV bars for crypto.
        Symbol format: 'BTC/USD', 'ETH/USD'
        """
        try:
            start = datetime.now(ET) - timedelta(days=lookback_days)
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
            )
            bars = self.crypto_data.get_crypto_bars(request)
            df = bars.df

            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")

            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            return df

        except Exception as e:
            logger.error(f"❌ Failed to fetch crypto bars for {symbol}: {e}")
            return pd.DataFrame()

    # ============================================================
    # MARKET DATA — LIVE QUOTES
    # ============================================================

    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Returns the latest ask price for a stock."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.stock_data.get_stock_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            logger.error(f"❌ Failed to get stock price for {symbol}: {e}")
            return None

    def get_crypto_price(self, symbol: str) -> Optional[float]:
        """Returns the latest ask price for crypto."""
        try:
            request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.crypto_data.get_crypto_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            logger.error(f"❌ Failed to get crypto price for {symbol}: {e}")
            return None

    # ============================================================
    # ORDERS
    # ============================================================

    def place_limit_order(
    self,
    symbol: str,
    side: str,
    qty: float,
    limit_price: float,
    take_profit: float,
    stop_loss: float,
    ) -> Optional[dict]:
    try:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        # Crypto — simple market order (Alpaca doesn't support
        # bracket orders for crypto)
        if self.is_crypto(symbol):
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.GTC,
            )
            order = self.trading.submit_order(order_data)
            logger.info(
                f"✅ Crypto order placed: {side.upper()} {qty} {symbol} @ market"
            )
            return order

        # Stocks — whole shares only, bracket order with
        # stop-loss and take-profit
        whole_qty = int(qty)
        if whole_qty == 0:
            logger.warning(f"⚠️  {symbol} qty rounded to 0 — skipping order")
            return None

        order_data = LimitOrderRequest(
            symbol=symbol,
            qty=whole_qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
            order_class="bracket",
            take_profit={"limit_price": round(take_profit, 2)},
            stop_loss={"stop_price": round(stop_loss, 2)},
        )
        order = self.trading.submit_order(order_data)
        logger.info(
            f"✅ Stock order placed: {side.upper()} {whole_qty} {symbol} "
            f"@ ${limit_price:.2f} | TP: ${take_profit:.2f} | SL: ${stop_loss:.2f}"
        )
        return order

    except Exception as e:
        logger.error(f"❌ Failed to place order for {symbol}: {e}")
        return None
    
    def place_crypto_stop_sell(
    self,
    symbol: str,
    qty: float,
) -> Optional[dict]:
    """
    Places a market sell order for crypto.
    Used by manual stop-loss logic in strategy.
    """
    try:
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
        )
        order = self.trading.submit_order(order_data)
        logger.info(f"✅ Crypto stop-sell placed: {qty} {symbol}")
        return order
    except Exception as e:
        logger.error(f"❌ Failed to place crypto stop-sell for {symbol}: {e}")
        return None

    def cancel_all_orders(self):
        """Cancels all open orders. Used by kill switch."""
        try:
            self.trading.cancel_orders()
            logger.info("✅ All open orders cancelled.")
        except Exception as e:
            logger.error(f"❌ Failed to cancel orders: {e}")

    def close_all_positions(self):
        """
        Closes all open positions at market price.
        Only called by kill switch — emergency use only.
        """
        try:
            self.trading.close_all_positions(cancel_orders=True)
            logger.info("✅ All positions closed.")
        except Exception as e:
            logger.error(f"❌ Failed to close positions: {e}")

    def get_open_orders(self) -> list:
        """Returns all currently open orders."""
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            return self.trading.get_orders(request)
        except Exception as e:
            logger.error(f"❌ Failed to fetch open orders: {e}")
            return []

    # ============================================================
    # HELPERS
    # ============================================================

    def is_crypto(self, symbol: str) -> bool:
        """Detects if symbol is crypto based on format: BTC/USD"""
        return "/" in symbol

    def get_bars(self, symbol: str, lookback_days: int = 30) -> pd.DataFrame:
        """
        Unified bar fetcher — automatically routes to
        stock or crypto client based on symbol format.
        """
        if self.is_crypto(symbol):
            return self.get_crypto_bars(symbol, lookback_days)
        return self.get_stock_bars(symbol, lookback_days)

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Unified price fetcher — automatically routes to
        stock or crypto client based on symbol format.
        """
        if self.is_crypto(symbol):
            return self.get_crypto_price(symbol)
        return self.get_stock_price(symbol)

    def calculate_qty(
        self,
        symbol: str,
        portfolio_value: float,
        position_pct: float,
        price: float,
    ) -> float:
        """
        Calculates how many shares/coins to buy.

        Formula:
            dollar_amount = portfolio_value × position_pct
            qty = dollar_amount / current_price

        Rounds down to avoid exceeding budget.
        Crypto supports fractional, stocks rounded to 2 decimals.
        """
        dollar_amount = portfolio_value * position_pct
        qty = dollar_amount / price

        if self.is_crypto(symbol):
            return round(qty, 6)   # Crypto: up to 6 decimal places
        return round(qty, 2)       # Stocks: fractional shares
