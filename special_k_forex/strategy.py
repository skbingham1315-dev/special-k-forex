from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .config import settings
from .indicators import compute_indicators


@dataclass(slots=True)
class Signal:
    symbol: str
    action: str
    score: int
    last_close: float
    atr: float
    stop_price: float
    take_profit_price: float
    notes: list[str]


class ForexETFStrategy:
    """
    Trend-pullback strategy tuned for forex ETFs.

    Forex ETFs (FXE, FXB, FXY, FXC, FXA, UUP) are low-volatility instruments
    driven by macro currency trends rather than corporate events. The logic is
    the same as Special K equity strategy but with relaxed thresholds:

    - Trend gate: close > SMA50 > SMA200
    - Entry: RSI pullback + Bollinger Band proximity + controlled 10-day pullback
    - Exit: price closes below SMA50 OR RSI overbought
    """

    def evaluate(self, symbol: str, raw_df: pd.DataFrame) -> Optional[Signal]:
        if raw_df.empty or len(raw_df) < 220:
            return None

        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        score = 0
        notes: list[str] = []

        if pd.isna(last["sma50"]) or pd.isna(last["sma200"]) or pd.isna(last["atr14"]):
            return None

        # Hard trend gate
        if not (last["close"] > last["sma50"] > last["sma200"]):
            return None
        notes.append("trend_up")
        score += 2

        # Liquidity check (forex ETFs have lower volume than equities)
        if last["avg_dollar_volume20"] >= settings.min_avg_dollar_volume:
            score += 1
            notes.append("liquid")

        # RSI pullback — forex ETFs rarely get below 35, so we use a wider zone
        if 38 <= last["rsi"] <= 50:
            score += 2
            notes.append("healthy_pullback_rsi")
        elif 30 <= last["rsi"] < 38:
            score += 3
            notes.append("deeper_pullback_rsi")

        # Bollinger Band proximity
        if last["close"] <= last["bb_lower"]:
            score += 2
            notes.append("below_lower_band")
        elif last["close"] <= last["bb_mid"]:
            score += 1
            notes.append("below_mid_band")

        # 10-day pullback — forex ETFs move slowly, use tighter range
        if -4.0 <= last["pullback_10d_pct"] <= -0.5:
            score += 2
            notes.append("controlled_pullback")
        elif last["pullback_10d_pct"] < -4.0:
            notes.append("pullback_too_deep")
            score -= 1

        # Positive trend slope
        if last["trend_slope_20"] > 0:
            score += 1
            notes.append("trend_slope_positive")

        # MACD histogram turning positive (momentum shift)
        if not pd.isna(last["macd_hist"]) and last["macd_hist"] > 0:
            score += 1
            notes.append("macd_turning")

        atr_value = float(last["atr14"])
        close = float(last["close"])
        stop_price = round(close - (atr_value * settings.stop_atr_multiplier), 4)
        take_profit_price = round(close + (atr_value * settings.take_profit_atr_multiplier), 4)

        if score < settings.min_signal_score:
            return None

        return Signal(
            symbol=symbol,
            action="buy",
            score=score,
            last_close=close,
            atr=atr_value,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            notes=notes,
        )

    def should_exit(self, raw_df: pd.DataFrame) -> tuple[bool, str]:
        if raw_df.empty or len(raw_df) < 220:
            return False, ""
        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        if pd.isna(last["sma50"]) or pd.isna(last["rsi"]):
            return False, ""
        if last["close"] < last["sma50"]:
            return True, "close_below_sma50"
        if last["rsi"] > 70:
            return True, "rsi_overbought"
        return False, ""
