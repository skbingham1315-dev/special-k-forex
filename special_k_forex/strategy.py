from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .config import settings
from .indicators import compute_indicators, classify_regime


@dataclass(slots=True)
class Signal:
    symbol: str
    action: str          # "buy" | "short" | "bounce"
    score: int
    last_close: float
    atr: float
    stop_price: float
    take_profit_price: float
    notes: list[str]
    regime: str = "normal"   # "slow" | "normal" | "active"
    direction: str = "long"  # "long" | "short" | "bounce"


class ForexETFStrategy:
    """
    Three-mode strategy for forex ETFs:

    LONG   — trend-pullback (close > SMA50 > SMA200, RSI dip, buy the bounce)
    SHORT  — trend-continuation (close < SMA50 < SMA200, RSI bounce to sell into)
    BOUNCE — counter-trend (RSI < 22, deeply oversold, expect snap-back, tiny size)
    """

    # ── LONG ──────────────────────────────────────────────────────────────────
    def evaluate(self, symbol: str, raw_df: pd.DataFrame) -> Optional[Signal]:
        if raw_df.empty or len(raw_df) < 220:
            return None
        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        score = 0
        notes: list[str] = []

        if pd.isna(last["sma50"]) or pd.isna(last["sma200"]) or pd.isna(last["atr14"]):
            return None

        regime = classify_regime(df)

        # Trend gate — relaxed in slow markets
        if regime == "slow":
            if not (last["close"] > last["sma50"]):
                return None
            notes.append("partial_trend")
            score += 1
        else:
            if not (last["close"] > last["sma50"] > last["sma200"]):
                return None
            notes.append("trend_up")
            score += 2

        if last["avg_dollar_volume20"] >= settings.min_avg_dollar_volume:
            score += 1
            notes.append("liquid")

        if 38 <= last["rsi"] <= 50:
            score += 2
            notes.append("healthy_pullback_rsi")
        elif 30 <= last["rsi"] < 38:
            score += 3
            notes.append("deeper_pullback_rsi")

        if last["close"] <= last["bb_lower"]:
            score += 2
            notes.append("below_lower_band")
        elif last["close"] <= last["bb_mid"]:
            score += 1
            notes.append("below_mid_band")

        if -4.0 <= last["pullback_10d_pct"] <= -0.5:
            score += 2
            notes.append("controlled_pullback")
        elif last["pullback_10d_pct"] < -4.0:
            notes.append("pullback_too_deep")
            score -= 1

        if last["trend_slope_20"] > 0:
            score += 1
            notes.append("trend_slope_positive")

        if not pd.isna(last["macd_hist"]) and last["macd_hist"] > 0:
            score += 1
            notes.append("macd_turning")

        # ── New: volume & divergence confirmation (Wyckoff + RSI divergence) ─
        if last.get("obv_trending_up", False):
            score += 1
            notes.append("obv_accumulation")

        if last.get("vol_declining_pullback", False):
            score += 1
            notes.append("vol_drying_up")    # healthy Wyckoff retracement

        if last.get("rsi_bull_divergence", False):
            score += 2
            notes.append("rsi_bull_divergence")   # strongest reversal signal

        if last.get("near_fib_support", False):
            score += 1
            notes.append("fib_support_zone")   # Constance Brown entry zone

        if last.get("bb_squeeze", False):
            score += 1
            notes.append("bb_squeeze")   # volatility coiling = bigger move ahead

        atr_value = float(last["atr14"])
        close = float(last["close"])

        if regime == "slow":
            stop_mult = settings.stop_atr_multiplier * 0.7
            tp_mult   = settings.take_profit_atr_multiplier * 0.8
        else:
            stop_mult = settings.stop_atr_multiplier
            tp_mult   = settings.take_profit_atr_multiplier

        stop_price        = round(close - atr_value * stop_mult, 4)
        take_profit_price = round(close + atr_value * tp_mult, 4)

        min_score = 3 if regime == "slow" else settings.min_signal_score
        if score < min_score:
            return None

        return Signal(
            symbol=symbol, action="buy", score=score,
            last_close=close, atr=atr_value,
            stop_price=stop_price, take_profit_price=take_profit_price,
            notes=notes, regime=regime, direction="long",
        )

    # ── SHORT ─────────────────────────────────────────────────────────────────
    def evaluate_short(self, symbol: str, raw_df: pd.DataFrame) -> Optional[Signal]:
        """
        Short when price is in a confirmed downtrend and has bounced (RSI risen),
        giving us a good entry to sell into. Mirrors the long logic in reverse.
        """
        if raw_df.empty or len(raw_df) < 220:
            return None
        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        score = 0
        notes: list[str] = []

        if pd.isna(last["sma50"]) or pd.isna(last["sma200"]) or pd.isna(last["atr14"]):
            return None

        regime = classify_regime(df)

        # Bearish trend gate — need confirmed downtrend
        if regime == "slow":
            if not (last["close"] < last["sma50"]):
                return None
            notes.append("partial_downtrend")
            score += 1
        else:
            if not (last["close"] < last["sma50"] and last["sma50"] < last["sma200"]):
                return None
            notes.append("trend_down")
            score += 2

        # Liquidity
        if last["avg_dollar_volume20"] >= settings.min_avg_dollar_volume:
            score += 1
            notes.append("liquid")

        # RSI: we want a bounce INTO overbought zone — better entry to short
        rsi = float(last["rsi"])
        if 52 <= rsi <= 65:
            score += 2
            notes.append("bounce_rsi_sell_zone")
        elif 65 < rsi <= 75:
            score += 3
            notes.append("extended_bounce_rsi")
        elif rsi > 75:
            score += 2
            notes.append("overbought_rsi")
            notes.append("overbought_warning")

        # Price bounced toward or above Bollinger mid — good short entry
        if last["close"] >= last["bb_upper"]:
            score += 2
            notes.append("above_upper_band")
        elif last["close"] >= last["bb_mid"]:
            score += 1
            notes.append("above_mid_band")

        # 10-day rally — price went up, giving us a level to sell into
        pull = float(last["pullback_10d_pct"])
        if 0.5 <= pull <= 4.0:
            score += 2
            notes.append("bounce_rally")
        elif pull > 4.0:
            score += 1
            notes.append("extended_rally")

        # Negative trend slope confirms direction
        if last["trend_slope_20"] < 0:
            score += 1
            notes.append("trend_slope_negative")

        # MACD histogram negative (momentum still down)
        if not pd.isna(last["macd_hist"]) and last["macd_hist"] < 0:
            score += 1
            notes.append("macd_bearish")

        # ── New: volume & divergence confirmation for shorts ──────────────
        if not last.get("obv_trending_up", True):   # OBV falling = distribution
            score += 1
            notes.append("obv_distribution")

        if last.get("rsi_bear_divergence", False):  # price up but RSI fading
            score += 2
            notes.append("rsi_bear_divergence")

        if last.get("bb_squeeze", False):
            score += 1
            notes.append("bb_squeeze")

        atr_value = float(last["atr14"])
        close = float(last["close"])

        # For shorts: stop ABOVE entry, target BELOW entry
        if regime == "slow":
            stop_mult = settings.stop_atr_multiplier * 0.7
            tp_mult   = settings.take_profit_atr_multiplier * 0.8
        else:
            stop_mult = settings.stop_atr_multiplier
            tp_mult   = settings.take_profit_atr_multiplier

        stop_price        = round(close + atr_value * stop_mult, 4)   # above entry
        take_profit_price = round(close - atr_value * tp_mult, 4)     # below entry

        min_score = 3 if regime == "slow" else settings.min_signal_score
        if score < min_score:
            return None

        return Signal(
            symbol=symbol, action="short", score=score,
            last_close=close, atr=atr_value,
            stop_price=stop_price, take_profit_price=take_profit_price,
            notes=notes, regime=regime, direction="short",
        )

    # ── BOUNCE ────────────────────────────────────────────────────────────────
    def evaluate_bounce(self, symbol: str, raw_df: pd.DataFrame) -> Optional[Signal]:
        """
        Counter-trend long when RSI is extremely oversold (< 22).
        Expects a snap-back to ~SMA50. Very small sizing, AI must approve.
        """
        if raw_df.empty or len(raw_df) < 220:
            return None
        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        score = 0
        notes: list[str] = []

        if pd.isna(last["rsi"]) or pd.isna(last["atr14"]):
            return None

        rsi = float(last["rsi"])
        if rsi >= 35:
            return None

        if rsi < 15:
            score += 4
            notes.append("extreme_oversold_rsi")
        elif rsi < 20:
            score += 3
            notes.append("deeply_oversold_rsi")
        elif rsi < 25:
            score += 2
            notes.append("oversold_rsi")
        else:
            score += 1
            notes.append("mild_oversold_rsi")

        # Below Bollinger lower band = extra confirmation
        if last["close"] <= last["bb_lower"]:
            score += 2
            notes.append("below_lower_band")

        # ADX > 25 means the downtrend was strong — moves like this tend to snap back hard
        adx = float(last["adx"]) if not pd.isna(last["adx"]) else 0
        if adx > 25:
            score += 1
            notes.append("strong_prior_trend")

        # MACD histogram turning less negative = momentum shifting
        if not pd.isna(last["macd_hist"]):
            hist = float(last["macd_hist"])
            if hist > -0.01:
                score += 1
                notes.append("macd_turning")

        # Liquidity
        if last["avg_dollar_volume20"] >= settings.min_avg_dollar_volume:
            score += 1
            notes.append("liquid")

        # ── New: strongest reversal confirmation signals ───────────────────
        if last.get("rsi_bull_divergence", False):   # price lower but RSI higher
            score += 3
            notes.append("rsi_bull_divergence")   # very strong bounce signal

        if last.get("obv_trending_up", False):       # money still flowing in
            score += 1
            notes.append("obv_accumulation")

        if last.get("near_fib_support", False):      # at Fibonacci support level
            score += 2
            notes.append("fib_support_zone")

        if last.get("vol_declining_pullback", False): # volume drying on drop
            score += 1
            notes.append("vol_drying_up")

        atr_value = float(last["atr14"])
        close = float(last["close"])

        # Tight stop (just below current low), target = SMA50 or 2x ATR
        stop_price        = round(close - atr_value * 0.8, 4)
        sma50 = float(last["sma50"]) if not pd.isna(last["sma50"]) else close + atr_value * 2
        take_profit_price = round(min(sma50, close + atr_value * 2.0), 4)

        if score < 4:
            return None

        return Signal(
            symbol=symbol, action="bounce", score=score,
            last_close=close, atr=atr_value,
            stop_price=stop_price, take_profit_price=take_profit_price,
            notes=notes, regime="bounce", direction="bounce",
        )

    # ── EXIT ──────────────────────────────────────────────────────────────────
    def should_exit(self, raw_df: pd.DataFrame, side: str = "long") -> tuple[bool, str]:
        """
        Determine if an open position should be closed.
        side: "long" | "short" | "bounce"
        """
        if raw_df.empty or len(raw_df) < 220:
            return False, ""
        df = compute_indicators(raw_df)
        last = df.iloc[-1]
        if pd.isna(last["sma50"]) or pd.isna(last["rsi"]):
            return False, ""

        rsi = float(last["rsi"])
        close = float(last["close"])
        sma50 = float(last["sma50"])
        sma200 = float(last.get("sma200") or sma50)

        if side == "long":
            # Standard exits
            if close < sma50:
                return True, "close_below_sma50"
            if rsi > 70:
                return True, "rsi_overbought"
            # Emergency: trend fully reversed (below SMA200) — original thesis broken
            if close < sma200 * 0.995:
                return True, "trend_reversed_below_sma200"
            # Emergency: RSI collapsed while still above SMA50 (distribution in progress)
            if rsi < 25 and close < sma50 * 1.01:
                return True, "rsi_collapsed_near_sma50"

        elif side == "short":
            # Cover short when price reclaims SMA50 or gets oversold
            if close > sma50:
                return True, "close_above_sma50_cover"
            if rsi < 30:
                return True, "rsi_oversold_cover"
            # Emergency: price reclaimed SMA200 — downtrend over
            if close > sma200 * 1.005:
                return True, "trend_reversed_above_sma200"

        elif side == "bounce":
            # Exit bounce when RSI recovers to neutral zone or price hits SMA50
            if rsi > 45:
                return True, "rsi_recovered"
            if close > sma50:
                return True, "price_above_sma50"
            # Bounce failed — cut early rather than wait for stop
            if rsi < 12:
                return True, "bounce_failed_extreme_oversold"

        return False, ""
