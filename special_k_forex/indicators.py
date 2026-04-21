import pandas as pd
import numpy as np


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    df["sma50"]  = c.rolling(50).mean()
    df["sma150"] = c.rolling(150).mean()
    df["sma200"] = c.rolling(200).mean()
    df["ema9"]   = c.ewm(span=9, adjust=False).mean()
    df["ema20"]  = c.ewm(span=20, adjust=False).mean()

    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Bollinger Bands
    mid = c.rolling(20).mean()
    std = c.rolling(20).std()
    df["bb_upper"] = mid + 2 * std
    df["bb_lower"] = mid - 2 * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / mid
    df["bb_mid"]   = mid

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd_line"]   = ema12 - ema26
    df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd_line"] - df["macd_signal"]

    # ATR (True Range)
    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    df["atr"]   = tr.ewm(span=14, adjust=False).mean()
    df["atr14"] = df["atr"]

    # ADX
    dm_plus  = ((h - h.shift()) > (l.shift() - l)).astype(float) * (h - h.shift()).clip(lower=0)
    dm_minus = ((l.shift() - l) > (h - h.shift())).astype(float) * (l.shift() - l).clip(lower=0)
    atr14    = tr.ewm(span=14, adjust=False).mean()
    di_plus  = 100 * dm_plus.ewm(span=14, adjust=False).mean() / atr14.replace(0, np.nan)
    di_minus = 100 * dm_minus.ewm(span=14, adjust=False).mean() / atr14.replace(0, np.nan)
    dx       = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    df["adx"] = dx.ewm(span=14, adjust=False).mean()

    # Volume ratio vs 20-day avg
    df["vol_ratio"] = v / v.rolling(20).mean()

    # Dollar volume (for liquidity floor)
    df["avg_dollar_volume20"] = c * v.rolling(20).mean()

    # Pullback and trend slope
    df["pullback_10d_pct"] = (c - c.shift(10)) / c.shift(10) * 100
    df["trend_slope_20"]   = c.ewm(span=20, adjust=False).mean().diff()

    # ── On-Balance Volume (Wyckoff volume accumulation) ────────────────────
    # OBV rises when closes are up (accumulation) and falls when down (distribution).
    # Bullish: OBV trending up while price pulls back = institutional buying.
    obv_raw = np.where(c > c.shift(1), v, np.where(c < c.shift(1), -v, 0))
    df["obv"] = pd.Series(obv_raw, index=df.index).cumsum()
    df["obv_ema20"] = df["obv"].ewm(span=20, adjust=False).mean()
    # True when OBV is above its 20-period EMA → accumulation bias
    df["obv_trending_up"] = df["obv"] > df["obv_ema20"]

    # ── Volume declining on pullback (Wyckoff healthy retracement) ─────────
    # A valid trend pullback has SHRINKING volume (sellers drying up).
    # High volume on a dip = distribution, not a safe bounce zone.
    vol_recent = v.rolling(5).mean()
    vol_prior  = v.shift(5).rolling(5).mean()
    df["vol_declining_pullback"] = vol_recent < vol_prior * 0.85

    # ── RSI divergence (Constance Brown / classic technical analysis) ──────
    # Bullish: price makes a lower low but RSI makes a higher low = momentum
    # is improving even as price falls → reversal signal.
    price_chg_10 = c - c.shift(10)
    rsi_chg_10   = df["rsi"] - df["rsi"].shift(10)
    df["rsi_bull_divergence"] = (price_chg_10 < -0.001) & (rsi_chg_10 > 2.0)
    # Bearish: price higher high but RSI lower high → momentum fading
    df["rsi_bear_divergence"] = (price_chg_10 > 0.001) & (rsi_chg_10 < -2.0)

    # ── Bollinger Band squeeze (Bill Williams volatility cycle) ────────────
    # When BB width compresses to its lowest point in 20 bars, the market is
    # coiling for a breakout. Entry signals during a squeeze carry higher
    # conviction because the subsequent move tends to be larger.
    bb_pctile = df["bb_width"].rolling(20).rank(pct=True)
    df["bb_squeeze"] = bb_pctile < 0.2   # width in bottom 20% of last 20 bars

    # ── Fibonacci retracement levels (Constance Brown / harmonic trading) ──
    # Calculate from the dominant 50-bar swing high/low.
    # Entries near the 38.2–61.8% retracement zone are highest probability.
    swing_high = h.rolling(50).max()
    swing_low  = l.rolling(50).min()
    fib_range  = (swing_high - swing_low).replace(0, np.nan)
    df["fib_38"] = swing_high - fib_range * 0.382
    df["fib_50"] = swing_high - fib_range * 0.500
    df["fib_62"] = swing_high - fib_range * 0.618
    tol = c * 0.005   # within 0.5% of price counts as "at the level"
    df["near_fib_support"] = (
        (abs(c - df["fib_38"]) < tol) |
        (abs(c - df["fib_50"]) < tol) |
        (abs(c - df["fib_62"]) < tol)
    )

    return df


def compute_crypto_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Crypto-optimised indicators. Uses EMAs (not SMAs) since crypto trades 24/7
    and EMAs react faster to price changes. Adds StochRSI, ROC, vol_regime,
    pullback_from_high. Requires only 60 bars (not 220).
    """
    df = compute_indicators(df)  # get base indicators (RSI, MACD, BB, ATR, OBV, etc.)

    c = df["close"]
    h = df["high"]
    v = df["volume"]

    # Crypto trend gates use EMAs not SMAs
    df["ema50"]  = c.ewm(span=50,  adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()

    # Stochastic RSI (more responsive for crypto volatility)
    rsi_min = df["rsi"].rolling(14).min()
    rsi_max = df["rsi"].rolling(14).max()
    df["stoch_rsi"] = (df["rsi"] - rsi_min) / (rsi_max - rsi_min + 1e-10)

    # Rate of Change
    df["roc_10"] = c.pct_change(10) * 100
    df["roc_30"] = c.pct_change(30) * 100

    # Pullback from recent 20-day high (for breakout detection)
    df["high_20d"]           = h.rolling(20).max()
    df["pullback_from_high"] = (c - df["high_20d"]) / df["high_20d"] * 100

    # Volatility percentile (for position sizing context)
    df["atr_pct"]    = df["atr14"] / c * 100
    df["vol_regime"] = df["atr_pct"].rolling(90).rank(pct=True)  # 0=low, 1=high vol

    # EMA20 slope (3-bar diff for smoothness)
    df["ema20_slope"] = df["ema20"].diff(3)

    # Exchange flow approximation (spec Part 9D)
    # Capitulation: price drops hard on high volume = potential buy
    df["exflow_capitulation"] = (df["vol_ratio"] > 1.5) & (df["roc_10"] < -5.0)
    # Accumulation: price flat + volume drying up = smart money loading quietly
    df["exflow_accumulation"] = (df["vol_ratio"] < 0.7) & (df["roc_10"].abs() < 2.0)
    # Distribution: price up + volume declining = late buyers, weak hands
    df["exflow_distribution"] = (df["vol_ratio"] < 0.7) & (df["roc_10"] > 3.0)

    return df


def classify_regime(df: pd.DataFrame) -> str:
    """
    Classify market regime based on ADX and ATR volatility.

    Returns:
        "slow"   — ADX < 18, choppy/ranging market. Trade smaller, lower signal bar.
        "normal" — ADX 18–28, moderate trend strength. Use default parameters.
        "active" — ADX > 28, strong directional move. Use full/larger sizing.
    """
    if df.empty or "adx" not in df.columns or "atr14" not in df.columns:
        return "normal"
    last = df.iloc[-1]
    adx = float(last["adx"]) if not pd.isna(last["adx"]) else 20.0
    if adx < 18:
        return "slow"
    if adx > 28:
        return "active"
    return "normal"
