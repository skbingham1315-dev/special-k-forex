"""
Crypto market data client using Alpaca's crypto data API.
Fetches daily OHLCV bars for crypto pairs like BTC/USD, ETH/USD.
"""
from __future__ import annotations
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Supported crypto pairs
CRYPTO_SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD",
    "DOGE/USD", "LINK/USD", "LTC/USD", "BCH/USD",
    "AAVE/USD", "UNI/USD",
]

class CryptoDataClient:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from alpaca.data.historical.crypto import CryptoHistoricalDataClient
                self._client = CryptoHistoricalDataClient()
            except Exception as e:
                log.warning(f"CryptoDataClient init failed: {e}")
        return self._client

    def get_daily_bars(self, symbol: str, lookback_days: int = 200) -> pd.DataFrame | None:
        """Return daily OHLCV DataFrame for a crypto pair (e.g. 'BTC/USD')."""
        client = self._get_client()
        if client is None:
            return None
        try:
            from alpaca.data.requests import CryptoBarsRequest
            from alpaca.data.timeframe import TimeFrame
            end   = datetime.now(timezone.utc)
            start = end - timedelta(days=lookback_days)
            req   = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)
            bars  = client.get_crypto_bars(req)
            df    = bars.df
            if df is None or df.empty:
                return None
            # Handle MultiIndex (symbol, timestamp) -> flatten to just timestamp rows
            if isinstance(df.index, pd.MultiIndex):
                sym_key = symbol
                if sym_key in df.index.get_level_values(0):
                    df = df.xs(sym_key, level=0)
                else:
                    df = df.reset_index(level=0, drop=True)
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.sort_index()
            df = df.rename(columns={"open":"open","high":"high","low":"low","close":"close","volume":"volume"})
            for col in ["open","high","low","close","volume"]:
                if col not in df.columns:
                    return None
            return df.reset_index(drop=True)
        except Exception as e:
            log.warning(f"CryptoDataClient.get_daily_bars({symbol}) failed: {e}")
            return None
