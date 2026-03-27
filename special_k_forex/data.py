from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from .config import settings

logger = logging.getLogger(__name__)


class MarketDataClient:
    def __init__(self) -> None:
        self.client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )

    def get_daily_bars(self, symbol: str, days: Optional[int] = None) -> pd.DataFrame:
        lookback_days = days or settings.lookback_days
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            adjustment="split",
            feed=DataFeed.IEX,
        )
        try:
            bars = self.client.get_stock_bars(request)
        except Exception as exc:
            logger.warning("Data fetch failed for %s: %s", symbol, exc)
            return pd.DataFrame()

        if not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return pd.DataFrame()

        df = bars.df.copy()
        if isinstance(df.index, pd.MultiIndex):
            try:
                df = df.xs(symbol, level="symbol")
            except KeyError:
                return pd.DataFrame()

        df = df.reset_index()
        return df.rename(columns={"timestamp": "date"})[["date", "open", "high", "low", "close", "volume"]]

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        request = StockLatestQuoteRequest(
            symbol_or_symbols=symbol,
            feed=DataFeed.IEX,
        )
        try:
            quotes = self.client.get_stock_latest_quote(request)
        except Exception as exc:
            logger.warning("Quote fetch failed for %s: %s", symbol, exc)
            return None

        quote = quotes.get(symbol)
        if not quote:
            return None
        return {
            "bid": float(quote.bid_price) if quote.bid_price else None,
            "ask": float(quote.ask_price) if quote.ask_price else None,
        }
