"""
legendary_trader_rules.py
-------------------------
Standalone signal quality filter module inspired by the world's best traders:
Weinstein, Minervini, O'Neil (CAN SLIM), Darvas, Livermore, Seykota / Turtle System,
Paul Tudor Jones, Wyckoff.

USAGE CONTRACT:
- This file is self-contained with no side effects on import.
- It imports ONLY libraries already used in the project (math, typing).
- It contains NO modification to any existing class or function.
- All functions are pure — data in, result out, no orders placed.

Integration: see the comment block at the bottom of this file.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence


# ── Module A — Market Condition Gate ──────────────────────────────────────────

def is_market_in_uptrend(price_series_200_days: Sequence[float]) -> bool:
    """
    Returns True if the most recent close is above its 200-bar simple moving average.

    Used as a master gate: if False, suppress ALL new long entries. This is the
    single most important filter — O'Neil, Minervini, and Weinstein all agree that
    the majority of big stock moves happen when the general market is in an uptrend.

    Args:
        price_series_200_days: Closing prices, most recent last. At least 200 required.

    Returns:
        True  — price above SMA200 → long entries permitted.
        False — price below SMA200 → suppress all new longs.
        True  — if fewer than 200 bars provided (insufficient data, do not block).
    """
    prices = list(price_series_200_days)
    if len(prices) < 200:
        return True  # insufficient data — do not block
    sma200 = sum(prices[-200:]) / 200
    return prices[-1] > sma200


# ── Module B — Trend Stage Filter (Weinstein / Minervini) ─────────────────────

def get_trend_stage(
    price_series: Sequence[float],
    sma_50: float,
    sma_150: float,
    sma_200: float,
) -> str:
    """
    Classify trend stage using Stan Weinstein Stage Analysis and Mark Minervini's
    trend template.

    Stage 2 (BUY ZONE):
        price > SMA50 > SMA150 > SMA200  AND  SMA200 trending upward.
        This is the only stage where Minervini takes long trades.

    Stage 4 (SHORT ZONE):
        price < SMA50 < SMA150 < SMA200.
        All three moving averages in bearish alignment — valid short entry zone.

    Stage 1 or 3 (NEUTRAL):
        Mixed alignment — basing or topping phase, no directional edge.

    Args:
        price_series: Closing prices, most recent last (at least 10 bars).
        sma_50:       Current 50-day simple moving average.
        sma_150:      Current 150-day simple moving average.
        sma_200:      Current 200-day simple moving average.

    Returns:
        "stage2", "stage4", or "neutral"
    """
    prices = list(price_series)
    if not prices:
        return "neutral"

    current_price = prices[-1]

    # SMA200 trending up: current price is higher than 10 bars ago (directional proxy)
    sma200_trending_up = True
    if len(prices) >= 10:
        sma200_trending_up = prices[-1] > prices[-10]

    if (current_price > sma_50 > sma_150 > sma_200) and sma200_trending_up:
        return "stage2"

    if current_price < sma_50 < sma_150 < sma_200:
        return "stage4"

    return "neutral"


# ── Module C — Breakout Signal (O'Neil / Darvas / Livermore) ──────────────────

def is_valid_breakout(
    price_series: Sequence[float],
    volume_series: Sequence[float],
    lookback: int = 52,
) -> bool:
    """
    Returns True if the current bar is a valid high-volume breakout.

    O'Neil's CANSLIM, Nicolas Darvas box breakouts, and Livermore's pivotal point
    all require price near a new high + surging volume to confirm institutional buying.

    Conditions (ALL must be true):
    1. Price is within 5% of the lookback-period high (within striking range of 52w high).
    2. Current volume >= 1.4x the 50-bar average volume (institutional accumulation).
    3. Price closed ABOVE the prior 20-bar high (broke prior resistance).

    Args:
        price_series:  Daily closing prices, most recent last.
        volume_series: Daily volumes, must match price_series in length.
        lookback:      Window for the "52-week" high in bars (default 52).

    Returns:
        True if all three conditions are met. False otherwise.
    """
    prices  = list(price_series)
    volumes = list(volume_series)

    min_bars = max(lookback, 50, 21)
    if len(prices) < min_bars or len(volumes) < 50:
        return False

    current_price  = prices[-1]
    current_volume = volumes[-1]

    # Condition 1: within 5% of lookback-period high
    period_high = max(prices[-lookback:])
    if current_price < period_high * 0.95:
        return False

    # Condition 2: volume >= 1.4x 50-bar average (exclude today)
    avg_vol_50 = sum(volumes[-51:-1]) / 50
    if avg_vol_50 <= 0 or current_volume < avg_vol_50 * 1.4:
        return False

    # Condition 3: closed above prior 20-bar high (resistance break)
    prior_20_high = max(prices[-21:-1])
    if current_price <= prior_20_high:
        return False

    return True


# ── Module D — Volatility Contraction Pattern Detector (Minervini VCP) ────────

def detect_vcp(
    price_series: Sequence[float],
    volume_series: Sequence[float],
    swings: int = 3,
) -> bool:
    """
    Detect a Volatility Contraction Pattern (VCP) — Mark Minervini's highest-
    conviction setup from "Trade Like a Stock Market Wizard."

    A VCP is a series of price range contractions, each one smaller than the last,
    while volume also contracts. The pattern shows sellers are exhausted and the
    stock is coiling for a breakout.

    Criteria:
    - Each price swing range <= 75% of the prior swing range (contraction).
    - Volume contracts alongside price (each swing's avg volume < prior swing's).
    - Need at least `swings` contractions.

    Args:
        price_series:  Daily closing prices, most recent last.
        volume_series: Daily volumes matching price_series.
        swings:        Minimum number of contracting swings (default 3).

    Returns:
        True if a valid VCP is detected. False otherwise.
    """
    prices  = list(price_series)
    volumes = list(volume_series)

    min_bars = swings * 10 + 5
    if len(prices) < min_bars or len(volumes) < min_bars:
        return False

    # Find local swing highs using a 5-bar window
    window = 5
    highs: list[tuple[int, float]] = []
    lows:  list[tuple[int, float]] = []

    for i in range(window, len(prices) - window):
        seg = prices[i - window: i + window + 1]
        if prices[i] == max(seg):
            highs.append((i, prices[i]))
        if prices[i] == min(seg):
            lows.append((i, prices[i]))

    if len(highs) < swings or len(lows) < swings:
        return False

    # Pair each swing high with the first swing low that follows it
    ranges: list[float]  = []
    vol_avgs: list[float] = []

    for hi_pos, hi_val in highs:
        lo_candidates = [(pos, val) for pos, val in lows if pos > hi_pos]
        if not lo_candidates:
            continue
        lo_pos, lo_val = lo_candidates[0]
        price_range = hi_val - lo_val
        if price_range > 0:
            seg_vol = volumes[hi_pos: lo_pos + 1]
            avg_vol = sum(seg_vol) / max(1, len(seg_vol))
            ranges.append(price_range)
            vol_avgs.append(avg_vol)
        if len(ranges) >= swings:
            break

    if len(ranges) < swings:
        return False

    # Verify contracting ranges AND contracting volume
    for i in range(1, len(ranges)):
        if ranges[i] > ranges[i - 1] * 0.75:
            return False
        if vol_avgs[i] >= vol_avgs[i - 1]:
            return False

    return True


# ── Module E — ATR Position Sizer (Turtle System) ─────────────────────────────

def calculate_turtle_position_size(
    account_equity: float,
    atr: float,
    price_per_share: float,
    risk_pct: float = 0.01,
) -> int:
    """
    Calculate position size using the original Turtle Trading System unit formula.

    Formula: Unit = (account_equity * risk_pct) / (atr * price_per_share)

    The Turtles defined 1 Unit as the position size that risked exactly 1% of
    equity per 1 ATR move. This keeps every position's volatility-adjusted risk equal.

    Hard cap: risk_pct is clamped to 2% maximum regardless of input.

    Args:
        account_equity:  Total portfolio equity in dollars.
        atr:             14-day Average True Range of the instrument.
        price_per_share: Current market price per share/unit.
        risk_pct:        Fraction of equity to risk per ATR unit (default 0.01 = 1%).

    Returns:
        Integer number of shares/units (floor — never rounds up). 0 if inputs invalid.
    """
    if atr <= 0 or price_per_share <= 0 or account_equity <= 0:
        return 0

    effective_risk_pct = min(risk_pct, 0.02)  # hard 2% cap
    dollar_risk = account_equity * effective_risk_pct
    raw_unit    = dollar_risk / (atr * price_per_share)

    return math.floor(raw_unit)


# ── Module F — ATR Trailing Stop (Seykota / Turtle) ───────────────────────────

def calculate_atr_stop(
    entry_price: float,
    atr: float,
    multiplier: float = 2.0,
    direction: str = "long",
) -> float:
    """
    Calculate an ATR-based stop-loss price (Seykota / Turtle method).

    Long stop  = entry_price - (atr * multiplier)
    Short stop = entry_price + (atr * multiplier)

    A 2x ATR stop keeps the trade alive through normal volatility while cutting
    losses if the move fails. Ed Seykota and the Turtles both used 2x ATR as
    their default stop distance.

    Args:
        entry_price: Trade entry price.
        atr:         Average True Range of the instrument.
        multiplier:  ATR multiplier for stop distance (default 2.0).
        direction:   "long" or "short" (default "long").

    Returns:
        Stop price as float, rounded to 6 decimal places.
    """
    if direction == "short":
        return round(entry_price + (atr * multiplier), 6)
    return round(entry_price - (atr * multiplier), 6)


# ── Module G — Momentum Quality Filter (O'Neil CAN SLIM) ──────────────────────

def passes_momentum_filter(
    eps_growth_current_qtr: Optional[float],
    eps_growth_prior_qtr: Optional[float],
    eps_growth_annual_3yr_avg: Optional[float],
    relative_strength_rank: Optional[float],
) -> Optional[bool]:
    """
    Quality gate inspired by William O'Neil's CAN SLIM methodology.

    O'Neil found that the biggest winning stocks shared these characteristics
    before their major moves: accelerating EPS growth, strong relative strength.

    Returns True if ALL of:
    - EPS growth current quarter >= 25%
    - EPS growth 3-year annual average >= 25%
    - Relative Strength Rank >= 80 (top 20% vs. market)
    - Current quarter EPS growth > prior quarter (acceleration — key CAN SLIM rule)

    NOTE: If fundamental data is unavailable, returns None — NOT False. The caller
    decides whether to skip the trade or proceed on technical signals only.

    Args:
        eps_growth_current_qtr:    Current quarter EPS growth % (e.g. 30.0 = 30%).
        eps_growth_prior_qtr:      Prior quarter EPS growth %.
        eps_growth_annual_3yr_avg: 3-year average annual EPS growth %.
        relative_strength_rank:    RS rank 0–100 vs. market universe.

    Returns:
        True if all conditions pass. False if any fails. None if data unavailable.
    """
    # All data missing → None (caller decides)
    if all(v is None for v in [
        eps_growth_current_qtr, eps_growth_prior_qtr,
        eps_growth_annual_3yr_avg, relative_strength_rank,
    ]):
        return None

    # Any required data missing → None
    if any(v is None for v in [
        eps_growth_current_qtr,
        eps_growth_annual_3yr_avg,
        relative_strength_rank,
    ]):
        return None

    if eps_growth_current_qtr < 25:
        return False
    if eps_growth_annual_3yr_avg < 25:
        return False
    if relative_strength_rank < 80:
        return False

    # Acceleration check (current must beat prior)
    if eps_growth_prior_qtr is not None:
        if eps_growth_current_qtr <= eps_growth_prior_qtr:
            return False

    return True


# ── Module H — Risk/Reward Gate (Paul Tudor Jones) ────────────────────────────

def passes_rr_gate(
    entry_price: float,
    stop_price: float,
    target_price: float,
    min_ratio: float = 3.0,
) -> bool:
    """
    Enforce a minimum reward-to-risk ratio before entering any trade.

    Paul Tudor Jones famously said: "Don't risk more than 1% to make 5%."
    Wyckoff's 9th buying test: estimated profit must be at least 3x the risk.
    This gate hard-vetoes any trade that doesn't meet the minimum R:R.

    Args:
        entry_price:  Intended entry price.
        stop_price:   Stop-loss price.
        target_price: Profit target price.
        min_ratio:    Minimum reward/risk ratio (default 3.0 = 3:1).

    Returns:
        True if reward/risk >= min_ratio. False otherwise.
    """
    risk   = abs(entry_price - stop_price)
    reward = abs(target_price - entry_price)

    if risk <= 0:
        return False

    return (reward / risk) >= min_ratio


# ── Module I — Composite Signal Scorer ────────────────────────────────────────

def score_trade_signal(
    symbol: str,
    price_series: Sequence[float],
    volume_series: Sequence[float],
    sma_50: float,
    sma_150: float,
    sma_200: float,
    atr: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    eps_data: Optional[dict] = None,
    rs_rank: Optional[float] = None,
) -> dict:
    """
    Composite scorer running all legendary trader filters (Modules A–H).

    Scoring breakdown:
    +2  Module A (market uptrend)  — GATE: fails → score=0 immediately
    +2  Module B (Stage 2 trend)
    +2  Module C (valid breakout)
    +1  Module D (VCP pattern)
    +2  Module G (momentum filter) — skipped if eps_data=None (no penalty)
    +2  Module H (R/R gate)        — GATE: fails → score=0 immediately
    ─────────────────────────────────────────────
    Max possible with fundamentals:    11
    Max possible without fundamentals:  9

    recommend=True if score >= 7.

    Args:
        symbol:        Ticker symbol (for breakdown labeling).
        price_series:  Closing prices, most recent last.
        volume_series: Volumes, most recent last.
        sma_50:        Current 50-day SMA.
        sma_150:       Current 150-day SMA.
        sma_200:       Current 200-day SMA.
        atr:           Current ATR(14).
        entry_price:   Intended entry price.
        stop_price:    Stop-loss price.
        target_price:  Profit target price.
        eps_data:      Optional dict: {'current_qtr', 'prior_qtr', 'annual_3yr_avg'}.
        rs_rank:       Optional RS rank 0–100.

    Returns:
        {
          "score":        int,
          "max_possible": int,
          "breakdown":    dict,   # per-module True/False/None
          "recommend":    bool,   # True if score >= 7
        }
    """
    breakdown: dict = {}
    score = 0
    max_possible = 9  # base (no fundamentals); grows to 11 if eps_data provided

    # ── Module A: Market uptrend gate ─────────────────────────────────────
    market_up = is_market_in_uptrend(price_series)
    breakdown["market_uptrend"] = market_up

    if not market_up:
        return {
            "score": 0,
            "max_possible": max_possible,
            "breakdown": {**breakdown, "gate_fail": "market_not_in_uptrend"},
            "recommend": False,
        }
    score += 2

    # ── Module B: Trend stage ──────────────────────────────────────────────
    stage = get_trend_stage(price_series, sma_50, sma_150, sma_200)
    breakdown["trend_stage"] = stage
    if stage == "stage2":
        score += 2

    # ── Module C: Breakout signal ──────────────────────────────────────────
    breakout = is_valid_breakout(price_series, volume_series)
    breakdown["valid_breakout"] = breakout
    if breakout:
        score += 2

    # ── Module D: VCP pattern ──────────────────────────────────────────────
    vcp = detect_vcp(price_series, volume_series)
    breakdown["vcp_pattern"] = vcp
    if vcp:
        score += 1

    # ── Module G: Momentum quality filter ─────────────────────────────────
    if eps_data is not None:
        max_possible += 2
        momentum_result = passes_momentum_filter(
            eps_data.get("current_qtr"),
            eps_data.get("prior_qtr"),
            eps_data.get("annual_3yr_avg"),
            rs_rank,
        )
        breakdown["momentum_filter"] = momentum_result
        if momentum_result is True:
            score += 2
    else:
        breakdown["momentum_filter"] = None  # skipped — no penalty

    # ── Module H: R/R gate ────────────────────────────────────────────────
    rr_pass = passes_rr_gate(entry_price, stop_price, target_price)
    breakdown["rr_gate"] = rr_pass

    if not rr_pass:
        return {
            "score": 0,
            "max_possible": max_possible,
            "breakdown": {**breakdown, "gate_fail": "rr_below_3_to_1"},
            "recommend": False,
        }
    score += 2

    return {
        "score": score,
        "max_possible": max_possible,
        "breakdown": breakdown,
        "recommend": score >= 7,
    }


# --- OPTIONAL INTEGRATION EXAMPLE ---
# Wire the legendary scorer into engine.py's entry loop as an additional
# quality gate AFTER the existing quant signal fires and BEFORE the order.
# This is purely additive — it does NOT replace any existing logic.
#
# ── In engine.py, add near the top of the file: ──────────────────────────────
#
# from .legendary_trader_rules import (
#     score_trade_signal,
#     calculate_turtle_position_size,
#     calculate_atr_stop,
# )
#
# ── Inside the candidates loop, after signal is confirmed and sized: ──────────
#
# # Build raw lists from bars DataFrame (bars is the raw_df from fetcher)
# _prices  = self.fetcher.get_daily_bars(symbol)["close"].tolist()
# _volumes = self.fetcher.get_daily_bars(symbol)["volume"].tolist()
# _sma150  = float(last_df["sma150"].iloc[-1]) if "sma150" in last_df.columns else sma_50
#
# lt = score_trade_signal(
#     symbol=symbol,
#     price_series=_prices,
#     volume_series=_volumes,
#     sma_50=float(last_row.get("sma50", price)),
#     sma_150=_sma150,
#     sma_200=float(last_row.get("sma200", price)),
#     atr=atr,
#     entry_price=price,
#     stop_price=stop,
#     target_price=tp,
# )
# logger.info(
#     f"  {symbol}: LegendaryScore={lt['score']}/{lt['max_possible']} "
#     f"recommend={lt['recommend']} | {lt['breakdown']}"
# )
#
# # For LONG signals only — require at least a recommend from the legendary filter
# # (short/bounce signals skip the market-uptrend gate, so apply selectively)
# if signal.direction == "long" and not lt["recommend"]:
#     logger.info(f"  {symbol}: LegendaryTrader veto — skipping.")
#     continue
#
# # Optional: Turtle sizing as a conservative second opinion
# turtle_qty = calculate_turtle_position_size(equity, atr, price)
# # Use conservative sizing: min(plan.qty, turtle_qty) if turtle_qty > 0 else plan.qty
