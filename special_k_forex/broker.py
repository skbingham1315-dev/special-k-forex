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
from .data import is_crypto, normalise_crypto

logger = logging.getLogger(__name__)


class Broker:
    def __init__(self) -> None:
        self.client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )
        # Detect whether the account supports shorting (paper accounts often don't)
        try:
            acct = self.client.get_account()
            self.shorting_enabled: bool = getattr(acct, "shorting_enabled", True)
        except Exception:
            self.shorting_enabled = False
        if not self.shorting_enabled:
            logger.info("Broker: shorting_enabled=False — short/sell signals will be skipped.")

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
        # Crypto positions show as "SOLUSD" but orders use "SOL/USD" — match both
        alt = normalise_crypto(symbol) if is_crypto(symbol) else symbol
        for order in self.get_open_orders():
            order_sym = getattr(order, "symbol", "")
            if order_sym == symbol or order_sym == alt:
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

    def get_pdt_info(self) -> dict:
        """
        Return PDT status for the account.
        daytrade_count: how many day trades used in the rolling 5-day window
        pdt_flagged: True if the account is officially flagged as a PDT account
        near_limit: True if count >= 3 and not flagged (next close of same-day open = PDT violation)
        """
        try:
            acct = self.client.get_account()
            count = int(getattr(acct, "daytrade_count", 0) or 0)
            flagged = bool(getattr(acct, "pattern_day_trader", False))
            return {"daytrade_count": count, "pdt_flagged": flagged, "near_limit": count >= 3 and not flagged}
        except Exception:
            return {"daytrade_count": 0, "pdt_flagged": False, "near_limit": False}

    def get_todays_opened_symbols(self) -> set:
        """
        Return set of symbols that had a filled BUY order placed today (local date).
        Used to identify same-day positions that would trigger PDT if closed today.
        """
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=today_utc, limit=200)
            orders = self.client.get_orders(filter=req)
            return {
                o.symbol for o in orders
                if str(getattr(o.side, "value", o.side)).lower() == "buy"
                and getattr(o, "filled_at", None) is not None
            }
        except Exception as e:
            logger.debug(f"get_todays_opened_symbols failed: {e}")
            return set()

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

        # Crypto: use GTC limit order (no bracket, no DAY TIF, fractional fine)
        if is_crypto(symbol):
            sym = normalise_crypto(symbol)
            limit_price = round(max(quote_ask, 0.01) * 1.003, 4)
            logger.info(f"CRYPTO BUY {sym}: qty={qty} limit={limit_price}")
            request = LimitOrderRequest(
                symbol=sym,
                qty=qty,
                side=OrderSide.BUY,
                limit_price=limit_price,
                time_in_force=TimeInForce.GTC,
            )
            return self.client.submit_order(request)

        limit_price = round(max(quote_ask, 0.01) * 1.003, 4)  # 0.3% above — fills at open reliably

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
        limit_price = round(max(quote_bid, 0.01) * 0.997, 4)  # 0.3% below bid — fills at open reliably

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
