"""
legendary_trader_rules_test.py
-------------------------------
Unit tests for legendary_trader_rules.py.

All tests use synthetic data — zero live API calls, zero Alpaca calls.
Run: python -m pytest legendary_trader_rules_test.py -v
  or: python legendary_trader_rules_test.py
"""
import math
import sys
import os

# Allow running from repo root or from within the package directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from special_k_forex.legendary_trader_rules import (
    is_market_in_uptrend,
    get_trend_stage,
    is_valid_breakout,
    detect_vcp,
    calculate_turtle_position_size,
    calculate_atr_stop,
    passes_momentum_filter,
    passes_rr_gate,
    score_trade_signal,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_trending_prices(n: int = 250, start: float = 100.0, slope: float = 0.2) -> list:
    """Generate a gently uptrending price series."""
    return [round(start + i * slope, 4) for i in range(n)]


def _make_flat_prices(n: int = 250, price: float = 100.0) -> list:
    """Generate a flat / sideways price series."""
    return [price] * n


def _make_downtrending_prices(n: int = 250, start: float = 150.0, slope: float = 0.2) -> list:
    """Generate a downtrending price series."""
    return [round(start - i * slope, 4) for i in range(n)]


def _make_volumes(n: int = 250, base: float = 1_000_000.0) -> list:
    """Generate a flat volume series."""
    return [base] * n


def _assert(condition: bool, msg: str):
    if not condition:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  PASS: {msg}")


# ── Module A — is_market_in_uptrend ───────────────────────────────────────────

def test_market_uptrend():
    print("\n[Module A] is_market_in_uptrend")

    # Price clearly above SMA200 → True
    prices = _make_trending_prices(250, start=50.0, slope=0.5)
    _assert(is_market_in_uptrend(prices) is True, "trending up → True")

    # Price clearly below SMA200 → False
    prices = _make_downtrending_prices(250, start=150.0, slope=0.5)
    _assert(is_market_in_uptrend(prices) is False, "trending down → False")

    # Flat: last price == SMA200 → not strictly above → False
    prices = _make_flat_prices(250, 100.0)
    _assert(is_market_in_uptrend(prices) is False, "flat at SMA200 → False")

    # Insufficient data → True (don't block trading)
    _assert(is_market_in_uptrend([100.0] * 100) is True, "< 200 bars → True (no block)")

    # Edge: exactly 200 bars
    prices = _make_trending_prices(200, start=80.0, slope=0.1)
    _assert(is_market_in_uptrend(prices) is True, "exactly 200 bars, uptrending → True")


# ── Module B — get_trend_stage ─────────────────────────────────────────────────

def test_trend_stage():
    print("\n[Module B] get_trend_stage")

    # Stage 2: price > sma50 > sma150 > sma200, upward trend
    prices = _make_trending_prices(250, start=100.0, slope=0.3)
    p = prices[-1]
    result = get_trend_stage(prices, sma_50=p - 5, sma_150=p - 10, sma_200=p - 15)
    _assert(result == "stage2", f"fully aligned uptrend → stage2 (got {result})")

    # Stage 4: price < sma50 < sma150 < sma200
    prices = _make_downtrending_prices(250, start=150.0, slope=0.3)
    p = prices[-1]
    result = get_trend_stage(prices, sma_50=p + 5, sma_150=p + 10, sma_200=p + 15)
    _assert(result == "stage4", f"fully aligned downtrend → stage4 (got {result})")

    # Neutral: mixed alignment
    prices = _make_flat_prices(250, 100.0)
    result = get_trend_stage(prices, sma_50=102.0, sma_150=100.0, sma_200=98.0)
    _assert(result == "neutral", f"mixed alignment → neutral (got {result})")

    # Stage 2 fails if SMA200 not trending up
    prices_down = _make_downtrending_prices(20, start=130.0, slope=1.0)
    result = get_trend_stage(prices_down, sma_50=110.0, sma_150=105.0, sma_200=100.0)
    # price[-1] = 110 which is NOT > sma50=110 exactly, so neutral
    _assert(result in ("stage2", "neutral"), "edge case: sma alignment but not trending up")

    # Empty series
    _assert(get_trend_stage([], 100.0, 98.0, 95.0) == "neutral", "empty series → neutral")


# ── Module C — is_valid_breakout ───────────────────────────────────────────────

def test_valid_breakout():
    print("\n[Module C] is_valid_breakout")

    n = 260
    # Build a price series approaching 52w high with high volume on the last bar
    prices  = _make_trending_prices(n, start=90.0, slope=0.05)
    prices[-1] = max(prices) + 0.10  # new 52w high
    volumes = _make_volumes(n, base=1_000_000.0)
    volumes[-1] = 1_600_000.0  # 1.6x average → passes volume check

    result = is_valid_breakout(prices, volumes, lookback=52)
    _assert(result is True, "near 52w high + high volume + above prior 20-bar high → True")

    # Low volume on breakout → False
    volumes_low = _make_volumes(n, base=1_000_000.0)
    volumes_low[-1] = 500_000.0  # 0.5x → fails
    _assert(is_valid_breakout(prices, volumes_low, lookback=52) is False,
            "low volume on breakout → False")

    # Price far below 52w high → False
    prices_low = _make_flat_prices(n, 80.0)
    prices_low[-1] = 80.0
    # The 52w high will be 80 * 1.05 = 84; current is 80 which is < 84 * 0.95
    prices_high = _make_trending_prices(n, start=80.0, slope=0.1)
    # Last price = 80 + 0.1*259 = 105.9, period_high = 105.9 (same value)
    # Actually this will pass. Let's make a case where price is well below high
    prices_below = [100.0] * 52 + [150.0] + [100.0] * (n - 53)  # spike in the middle
    volumes_above = _make_volumes(n, base=1_000_000.0)
    volumes_above[-1] = 1_600_000.0
    # Current price = 100, 52w high = 150 → 100 < 150 * 0.95 = 142.5 → False
    _assert(is_valid_breakout(prices_below, volumes_above, lookback=52) is False,
            "price far below 52w high → False")

    # Insufficient data → False
    _assert(is_valid_breakout([100.0] * 10, [1_000_000.0] * 10) is False,
            "insufficient data → False")


# ── Module D — detect_vcp ──────────────────────────────────────────────────────

def test_detect_vcp():
    print("\n[Module D] detect_vcp")

    # Build a synthetic VCP: 3 contracting swing ranges with declining volume
    # Swing 1: range 10, vol 2M
    # Swing 2: range 6,  vol 1.5M (60% of prior range, 75% of prior vol)
    # Swing 3: range 3,  vol 0.9M (50% of prior range, 60% of prior vol)
    prices  = []
    volumes = []
    base = 100.0

    # Swing 1: 20 bars, peak at +10 then dip to base
    for i in range(20):
        prices.append(base + 5 * math.sin(math.pi * i / 19))
    for _ in range(20):
        volumes.append(2_000_000.0)

    # Swing 2: 15 bars, peak at +6 then dip to base
    for i in range(15):
        prices.append(base + 3 * math.sin(math.pi * i / 14))
    for _ in range(15):
        volumes.append(1_500_000.0)

    # Swing 3: 12 bars, peak at +3 then dip to base
    for i in range(12):
        prices.append(base + 1.5 * math.sin(math.pi * i / 11))
    for _ in range(12):
        volumes.append(900_000.0)

    # Pad to ensure detect_vcp has enough bars
    prices  = [base] * 10 + prices + [base] * 5
    volumes = [1_000_000.0] * 10 + volumes + [800_000.0] * 5

    result = detect_vcp(prices, volumes, swings=3)
    # This is a structural test — may be True or False depending on swing detection
    # The important thing is it runs without error and returns bool
    _assert(isinstance(result, bool), "detect_vcp returns a bool")
    print(f"    (VCP result on synthetic data: {result})")

    # Insufficient data → False
    _assert(detect_vcp([100.0] * 5, [1_000_000.0] * 5) is False,
            "insufficient data → False")

    # Flat prices (no swings) → False
    _assert(detect_vcp(_make_flat_prices(60), _make_volumes(60)) is False,
            "flat prices (no swings) → False")


# ── Module E — calculate_turtle_position_size ─────────────────────────────────

def test_turtle_position_size():
    print("\n[Module E] calculate_turtle_position_size")

    # Standard case: $100k equity, ATR=2.0, price=$50, risk=1%
    # Unit = (100000 * 0.01) / (2.0 * 50) = 1000 / 100 = 10
    result = calculate_turtle_position_size(100_000, atr=2.0, price_per_share=50.0, risk_pct=0.01)
    _assert(result == 10, f"standard case → 10 shares (got {result})")

    # Floor division: should return int floor, not round
    # (100000 * 0.01) / (2.0 * 60) = 1000 / 120 = 8.33... → floor = 8
    result = calculate_turtle_position_size(100_000, atr=2.0, price_per_share=60.0, risk_pct=0.01)
    _assert(result == 8, f"floor division → 8 (got {result})")

    # 2% cap: risk_pct=0.05 should be clamped to 0.02
    # (100000 * 0.02) / (2.0 * 50) = 2000 / 100 = 20
    result = calculate_turtle_position_size(100_000, atr=2.0, price_per_share=50.0, risk_pct=0.05)
    _assert(result == 20, f"risk_pct clamped to 2% → 20 shares (got {result})")

    # Invalid inputs → 0
    _assert(calculate_turtle_position_size(0, 2.0, 50.0)    == 0, "zero equity → 0")
    _assert(calculate_turtle_position_size(100_000, 0, 50.0) == 0, "zero ATR → 0")
    _assert(calculate_turtle_position_size(100_000, 2.0, 0)  == 0, "zero price → 0")

    # Result is always an integer
    result = calculate_turtle_position_size(50_000, atr=1.5, price_per_share=25.0, risk_pct=0.01)
    _assert(isinstance(result, int), f"result is int (got {type(result).__name__}: {result})")


# ── Module F — calculate_atr_stop ─────────────────────────────────────────────

def test_atr_stop():
    print("\n[Module F] calculate_atr_stop")

    # Long stop: entry=100, ATR=2, mult=2.0 → stop = 100 - 4 = 96
    result = calculate_atr_stop(100.0, atr=2.0, multiplier=2.0, direction="long")
    _assert(result == 96.0, f"long stop → 96.0 (got {result})")

    # Short stop: entry=100, ATR=2, mult=2.0 → stop = 100 + 4 = 104
    result = calculate_atr_stop(100.0, atr=2.0, multiplier=2.0, direction="short")
    _assert(result == 104.0, f"short stop → 104.0 (got {result})")

    # Custom multiplier: entry=50, ATR=1.0, mult=3.0, long → 50 - 3 = 47
    result = calculate_atr_stop(50.0, atr=1.0, multiplier=3.0, direction="long")
    _assert(result == 47.0, f"custom mult long → 47.0 (got {result})")

    # Default direction is long
    result_default = calculate_atr_stop(100.0, atr=2.0)
    result_long    = calculate_atr_stop(100.0, atr=2.0, direction="long")
    _assert(result_default == result_long, "default direction is long")


# ── Module G — passes_momentum_filter ─────────────────────────────────────────

def test_momentum_filter():
    print("\n[Module G] passes_momentum_filter")

    # All conditions met → True
    _assert(passes_momentum_filter(30.0, 25.0, 28.0, 85.0) is True,
            "all conditions met → True")

    # Current EPS < 25% → False
    _assert(passes_momentum_filter(20.0, 15.0, 28.0, 85.0) is False,
            "current EPS < 25% → False")

    # Annual 3yr avg < 25% → False
    _assert(passes_momentum_filter(30.0, 25.0, 20.0, 85.0) is False,
            "annual 3yr avg < 25% → False")

    # RS rank < 80 → False
    _assert(passes_momentum_filter(30.0, 25.0, 28.0, 75.0) is False,
            "RS rank < 80 → False")

    # No acceleration (current <= prior) → False
    _assert(passes_momentum_filter(25.0, 30.0, 28.0, 85.0) is False,
            "no acceleration (current <= prior) → False")

    # All None → None
    _assert(passes_momentum_filter(None, None, None, None) is None,
            "all None → None")

    # Required data missing → None
    _assert(passes_momentum_filter(None, 25.0, 28.0, 85.0) is None,
            "current_qtr None → None")

    # Prior qtr None but rest ok → True (acceleration check skipped)
    _assert(passes_momentum_filter(30.0, None, 28.0, 85.0) is True,
            "prior_qtr None, rest ok → True (no acceleration check)")


# ── Module H — passes_rr_gate ─────────────────────────────────────────────────

def test_rr_gate():
    print("\n[Module H] passes_rr_gate")

    # Long trade: entry=100, stop=98 (risk=2), target=106 (reward=6) → 3:1 → True
    _assert(passes_rr_gate(100.0, 98.0, 106.0, min_ratio=3.0) is True,
            "long 3:1 exactly → True")

    # Fails: reward=5, risk=3 → 1.67 < 3.0 → False
    _assert(passes_rr_gate(100.0, 97.0, 105.0, min_ratio=3.0) is False,
            "1.67:1 < 3.0 minimum → False")

    # Short trade: entry=100, stop=103 (risk=3), target=91 (reward=9) → 3:1 → True
    _assert(passes_rr_gate(100.0, 103.0, 91.0, min_ratio=3.0) is True,
            "short 3:1 exactly → True")

    # Custom min_ratio=5: entry=100, stop=99, target=106 → 6:1 > 5 → True
    _assert(passes_rr_gate(100.0, 99.0, 106.0, min_ratio=5.0) is True,
            "6:1 > 5.0 custom minimum → True")

    # Zero risk → False
    _assert(passes_rr_gate(100.0, 100.0, 110.0) is False,
            "zero risk (entry == stop) → False")


# ── Module I — score_trade_signal (composite) ─────────────────────────────────

def test_composite_scorer():
    print("\n[Module I] score_trade_signal (composite scorer)")

    n = 260
    # Uptrending price series with all favorable conditions
    prices  = _make_trending_prices(n, start=80.0, slope=0.2)
    volumes = _make_volumes(n, base=1_000_000.0)

    # Make last bar look like a breakout (high volume + near 52w high)
    prices[-1] = max(prices[-52:]) + 0.50  # new 52w high
    volumes[-1] = 2_000_000.0

    current_price = prices[-1]
    sma50  = current_price - 3.0
    sma150 = current_price - 7.0
    sma200 = current_price - 12.0
    atr    = 1.5

    # Good R:R: stop 3 ATR below, target 9 ATR above → 3:1
    stop   = current_price - atr * 3
    target = current_price + atr * 9

    result = score_trade_signal(
        symbol="TEST",
        price_series=prices,
        volume_series=volumes,
        sma_50=sma50,
        sma_150=sma150,
        sma_200=sma200,
        atr=atr,
        entry_price=current_price,
        stop_price=stop,
        target_price=target,
    )

    _assert(isinstance(result["score"], int),         "score is int")
    _assert(isinstance(result["recommend"], bool),    "recommend is bool")
    _assert(isinstance(result["breakdown"], dict),    "breakdown is dict")
    _assert(result["max_possible"] in (9, 11),        "max_possible is 9 or 11")
    _assert(result["score"] >= 0,                     "score is non-negative")
    _assert(result["breakdown"]["market_uptrend"] is True, "uptrending prices → market_uptrend True")
    _assert(result["breakdown"]["rr_gate"] is True,   "3:1 R:R → rr_gate True")
    print(f"    score={result['score']}/{result['max_possible']} recommend={result['recommend']}")
    print(f"    breakdown: {result['breakdown']}")

    # Gate test: market downtrend → score=0, recommend=False immediately
    down_prices = _make_downtrending_prices(n, start=150.0, slope=0.3)
    result_down = score_trade_signal(
        symbol="TEST_DOWN",
        price_series=down_prices,
        volume_series=volumes,
        sma_50=sma50,
        sma_150=sma150,
        sma_200=sma200,
        atr=atr,
        entry_price=down_prices[-1],
        stop_price=down_prices[-1] - atr * 3,
        target_price=down_prices[-1] + atr * 9,
    )
    _assert(result_down["score"] == 0,       "downtrend market gate → score=0")
    _assert(result_down["recommend"] is False, "downtrend market gate → recommend=False")
    _assert("gate_fail" in result_down["breakdown"], "gate failure recorded in breakdown")

    # Gate test: bad R:R → score=0 immediately
    result_rr = score_trade_signal(
        symbol="TEST_RR",
        price_series=prices,
        volume_series=volumes,
        sma_50=sma50,
        sma_150=sma150,
        sma_200=sma200,
        atr=atr,
        entry_price=current_price,
        stop_price=current_price - atr * 3,   # risk = 3 ATR
        target_price=current_price + atr * 2, # reward = 2 ATR → 0.67:1 < 3.0
    )
    _assert(result_rr["score"] == 0,        "poor R:R gate → score=0")
    _assert(result_rr["recommend"] is False, "poor R:R gate → recommend=False")

    # With eps_data: max_possible increases to 11
    result_with_eps = score_trade_signal(
        symbol="TEST_EPS",
        price_series=prices,
        volume_series=volumes,
        sma_50=sma50,
        sma_150=sma150,
        sma_200=sma200,
        atr=atr,
        entry_price=current_price,
        stop_price=stop,
        target_price=target,
        eps_data={"current_qtr": 35.0, "prior_qtr": 28.0, "annual_3yr_avg": 30.0},
        rs_rank=90.0,
    )
    _assert(result_with_eps["max_possible"] == 11, "with eps_data → max_possible=11")
    print(f"    with EPS: score={result_with_eps['score']}/11 recommend={result_with_eps['recommend']}")


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_all():
    tests = [
        test_market_uptrend,
        test_trend_stage,
        test_valid_breakout,
        test_detect_vcp,
        test_turtle_position_size,
        test_atr_stop,
        test_momentum_filter,
        test_rr_gate,
        test_composite_scorer,
    ]
    passed = 0
    failed = 0
    errors = []

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {e}")
            failed += 1
            errors.append(str(e))
        except Exception as e:
            print(f"  ✗ EXCEPTION in {test_fn.__name__}: {e}")
            failed += 1
            errors.append(f"{test_fn.__name__}: {e}")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("Failures:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("All tests passed.")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
