from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from .config import settings

logger = logging.getLogger(__name__)

# Crypto symbols supported by Alpaca (format: "BTC/USD")
CRYPTO_SYMBOLS = {
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
    "LINK/USD", "LTC/USD", "BCH/USD", "SHIB/USD", "UNI/USD",
    "AAVE/USD", "XTZ/USD", "BAT/USD", "CRV/USD", "GRT/USD",
}


def is_crypto(symbol: str) -> bool:
    return "/" in symbol or symbol.upper() in {s.replace("/", "") for s in CRYPTO_SYMBOLS}


def normalise_crypto(symbol: str) -> str:
    """Ensure crypto symbol has slash: BTCUSD → BTC/USD"""
    s = symbol.upper()
    if "/" in s:
        return s
    if s.endswith("USD") and len(s) > 3:
        return s[:-3] + "/USD"
    return s


class MarketDataClient:
    def __init__(self) -> None:
        self.stock_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self.crypto_client = CryptoHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )

    def get_daily_bars(self, symbol: str, days: Optional[int] = None) -> pd.DataFrame:
        if is_crypto(symbol):
            return self._get_crypto_bars(normalise_crypto(symbol), days)
        return self._get_stock_bars(symbol, days)

    def _get_stock_bars(self, symbol: str, days: Optional[int] = None) -> pd.DataFrame:
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
            bars = self.stock_client.get_stock_bars(request)
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

    def _get_crypto_bars(self, symbol: str, days: Optional[int] = None) -> pd.DataFrame:
        lookback_days = days or settings.lookback_days
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        request = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        try:
            bars = self.crypto_client.get_crypto_bars(request)
        except Exception as exc:
            logger.warning("Crypto data fetch failed for %s: %s", symbol, exc)
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
        if is_crypto(symbol):
            return None  # crypto price comes from bars
        request = StockLatestQuoteRequest(
            symbol_or_symbols=symbol,
            feed=DataFeed.IEX,
        )
        try:
            quotes = self.stock_client.get_stock_latest_quote(request)
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
