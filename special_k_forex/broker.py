from __future__ import annotations

import logging
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce, QueryOrderStatus
from alpaca.trading.requests import (
    GetOrdersRequest,
    GetPortfolioHistoryRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from .config import settings

logger = logging.getLogger(__name__)


class Broker:
    def __init__(self) -> None:
        self.client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )

    def get_account(self):
        return self.client.get_account()

    def get_buying_power(self) -> float:
        account = self.get_account()
        return float(account.buying_power)

    def get_positions(self):
        return self.client.get_all_positions()

    def get_position(self, symbol: str):
        for position in self.get_positions():
            if position.symbol == symbol:
                return position
        return None

    def get_open_orders(self):
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100)
        return self.client.get_orders(filter=request)

    def cancel_orders_for_symbol(self, symbol: str) -> None:
        for order in self.get_open_orders():
            if getattr(order, "symbol", "") == symbol:
                try:
                    self.client.cancel_order_by_id(order.id)
                except Exception as exc:
                    logger.warning("Could not cancel order for %s: %s", symbol, exc)

    def close_position(self, symbol: str):
        self.cancel_orders_for_symbol(symbol)
        return self.client.close_position(symbol)

    def get_portfolio_history(self, period: str = "1A", timeframe: str = "1D"):
        """Return daily equity history for the past `period` (e.g. '1A', '6M', '3M')."""
        req = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
        return self.client.get_portfolio_history(req)

    def get_closed_orders(self, limit: int = 500):
        """Return all filled/closed orders, newest first."""
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=limit)
        return self.client.get_orders(filter=req)

    def place_bracket_buy(
        self,
        symbol: str,
        qty: float,
        quote_ask: float,
        stop_loss: float,
        take_profit: float,
    ):
        if qty < 0.001:
            raise ValueError("Quantity must be at least 0.001.")
        limit_price = round(max(quote_ask, 0.01) * 1.0005, 4)

        # Alpaca does not allow bracket orders for fractional shares — use simple limit
        is_fractional = (qty % 1) != 0
        if is_fractional:
            logger.info(f"Fractional qty {qty} for {symbol} — using simple limit order (no bracket)")
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY,
            )
        else:
            safe_stop = round(min(stop_loss, limit_price - 0.0001), 4)
            safe_target = round(max(take_profit, limit_price + 0.0001), 4)
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=safe_target),
                stop_loss=StopLossRequest(stop_price=safe_stop),
            )
        return self.client.submit_order(request)

    def place_bracket_short(
        self,
        symbol: str,
        qty: float,
        quote_bid: float,
        stop_loss: float,   # ABOVE entry for shorts
        take_profit: float, # BELOW entry for shorts
    ):
        """Short sell with bracket orders. Stop is above entry, target is below."""
        if qty < 0.001:
            raise ValueError("Quantity must be at least 0.001.")
        limit_price = round(max(quote_bid, 0.01) * 0.9995, 4)  # slightly below bid

        # Alpaca does not allow bracket orders for fractional shares — use simple limit
        is_fractional = (qty % 1) != 0
        if is_fractional:
            logger.info(f"Fractional qty {qty} for {symbol} — using simple limit order (no bracket)")
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY,
            )
        else:
            safe_stop   = round(max(stop_loss,   limit_price + 0.0001), 4)
            safe_target = round(min(take_profit, limit_price - 0.0001), 4)
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=safe_target),
                stop_loss=StopLossRequest(stop_price=safe_stop),
            )
        logger.info(
            f"SHORT {symbol}: qty={qty} limit={limit_price} fractional={is_fractional}"
        )
        return self.client.submit_order(request)
