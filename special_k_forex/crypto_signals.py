"""
Crypto-specific market intelligence signals for Special K Trading.

Provides:
  - Fear & Greed Index (alternative.me — free, no key)
  - BTC Dominance (CoinGecko — free, no key)
  - Funding rates (Binance perp futures — free, no key)
  - Crypto news sentiment (RSS keyword scan)
  - BTC 1H price change (CoinGecko — for altcoin correlation rule)

All functions cache results for 1 hour to avoid hammering free APIs.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger(__name__)

_CACHE_TTL = 3600  # 1 hour

# ── cache store ──────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: int = _CACHE_TTL):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    return None


def _store(key: str, value: object):
    _cache[key] = (time.time(), value)


def _get(url: str, timeout: int = 8) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SpecialKTrading/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.debug(f"HTTP GET failed {url}: {e}")
        return None


# ── Fear & Greed Index ────────────────────────────────────────────────────────

def get_fear_greed() -> dict:
    """
    Fetch the Crypto Fear & Greed Index from alternative.me.
    Returns:
        value (int 0-100), label (str), score_delta (float)
    score_delta:
        0-25 (Extreme Fear) → +1.5  (buy signal per strategy)
        75-100 (Extreme Greed) → -1.5 (avoid longs)
        else → 0
    """
    key = "fear_greed"
    cached = _cached(key)
    if cached:
        return cached

    data = _get("https://api.alternative.me/fng/")
    if not data:
        result = {"value": 50, "label": "Neutral", "score_delta": 0.0, "available": False}
        _store(key, result)
        return result

    try:
        entry = data["data"][0]
        value = int(entry["value"])
        label = entry["value_classification"]
        if value <= 25:
            score_delta = 1.5
        elif value >= 75:
            score_delta = -1.5
        else:
            score_delta = 0.0
        result = {"value": value, "label": label, "score_delta": score_delta, "available": True}
    except Exception as e:
        log.warning(f"Fear & Greed parse failed: {e}")
        result = {"value": 50, "label": "Neutral", "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


# ── BTC Dominance ─────────────────────────────────────────────────────────────

def get_btc_dominance() -> dict:
    """
    Fetch BTC market dominance from CoinGecko.
    Returns:
        pct (float), rising (bool or None), score_delta (float)
    score_delta:
        Rising dominance → -0.5 (flight to safety, bad for alts)
        Falling dominance → +1.0 (altcoin season risk-on)
    """
    key = "btc_dominance"
    cached = _cached(key)
    if cached:
        return cached

    data = _get("https://api.coingecko.com/api/v3/global")
    if not data:
        result = {"pct": 50.0, "rising": None, "score_delta": 0.0, "available": False}
        _store(key, result)
        return result

    try:
        pct = float(data["data"]["market_cap_percentage"]["btc"])
        # Derive trend from previous cached value if available
        prev = _cache.get("btc_dominance_prev")
        prev_pct = prev[1] if prev else None
        if prev_pct is not None:
            rising = pct > prev_pct
        else:
            rising = None  # first fetch, unknown direction
        _store("btc_dominance_prev", pct)

        if rising is True:
            score_delta = -0.5
        elif rising is False:
            score_delta = 1.0
        else:
            score_delta = 0.0

        result = {"pct": round(pct, 2), "rising": rising, "score_delta": score_delta, "available": True}
    except Exception as e:
        log.warning(f"BTC dominance parse failed: {e}")
        result = {"pct": 50.0, "rising": None, "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


def is_bitcoin_season() -> bool:
    """
    Returns True when Bitcoin Season is active (BTC dominance > 55%).
    During Bitcoin Season: only trade BTC and ETH — skip altcoins.
    """
    dom = get_btc_dominance()
    return dom["pct"] > 55.0


# ── Funding Rates (Binance Perp Futures) ─────────────────────────────────────

# Map Alpaca symbol format → Binance perpetual symbol
_BINANCE_SYMBOL_MAP = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "AVAX/USD": "AVAXUSDT",
    "DOGE/USD": "DOGEUSDT",
    "LINK/USD": "LINKUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "AAVE/USD": "AAVEUSDT",
    "UNI/USD": "UNIUSDT",
    "XRP/USD": "XRPUSDT",
    "DOT/USD": "DOTUSDT",
    "MATIC/USD": "MATICUSDT",
    "SHIB/USD": "SHIBUSDT",
    "ADA/USD": "ADAUSDT",
}


def get_funding_rate(symbol: str) -> dict:
    """
    Fetch perpetual futures funding rate from Binance (no API key required).
    Returns:
        rate (float), score_delta (float)
    score_delta:
        Negative rate (shorts paying longs) → +0.5 (oversold, long bias)
        Extreme positive (>0.1%) → -0.5 (overleveraged longs, caution)
    """
    binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
    if not binance_sym:
        return {"rate": 0.0, "score_delta": 0.0, "available": False}

    key = f"funding_{binance_sym}"
    cached = _cached(key, ttl=1800)  # 30-min cache (funding updates every 8h)
    if cached:
        return cached

    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={binance_sym}"
    data = _get(url)
    if not data:
        result = {"rate": 0.0, "score_delta": 0.0, "available": False}
        _store(key, result)
        return result

    try:
        rate = float(data.get("lastFundingRate", 0))
        if rate < 0:
            score_delta = 0.5   # shorts paying longs = oversold bounce
        elif rate > 0.001:      # > 0.1%
            score_delta = -0.5  # overleveraged longs = caution
        else:
            score_delta = 0.0
        result = {"rate": round(rate, 6), "score_delta": score_delta, "available": True}
    except Exception as e:
        log.warning(f"Funding rate parse failed for {symbol}: {e}")
        result = {"rate": 0.0, "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


# ── BTC 1H Change (altcoin correlation rule) ──────────────────────────────────

def get_btc_1h_change() -> float:
    """
    Returns BTC price change over the last ~1 hour using CoinGecko market data.
    Uses the 24h price change as a fallback proxy if hourly not available.
    Returns float (e.g. -3.5 means BTC dropped 3.5%).
    """
    key = "btc_1h_change"
    cached = _cached(key, ttl=300)  # 5-min cache
    if cached is not None:
        return cached

    # CoinGecko simple price with 1h change
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_1hr_change=true"
    data = _get(url)
    change = 0.0
    if data:
        try:
            btc = data.get("bitcoin", {})
            # Try 1h change first, fallback to 24h
            change = float(btc.get("usd_1h_change") or btc.get("usd_24h_change") or 0.0)
        except Exception as e:
            log.debug(f"BTC 1H change parse failed: {e}")

    _store(key, change)
    return change


def btc_flash_crash_active() -> bool:
    """
    Returns True if BTC has dropped more than 3% in the last hour.
    When True: halt all altcoin entries (correlation rule from strategy doc).
    """
    return get_btc_1h_change() < -3.0


# ── Crypto News Sentiment ─────────────────────────────────────────────────────

_CRYPTO_RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/feed",
    "https://www.theblock.co/rss.xml",
]

_BULLISH_KEYWORDS = [
    "etf approved", "etf inflow", "etf approval", "institutional buying",
    "strategic reserve", "bitcoin treasury", "rate cut", "regulatory clarity",
    "sec approval", "coinbase listing", "protocol upgrade", "halving",
    "whale accumulation", "exchange outflow", "adoption", "legal tender",
    "nation state", "treasury allocation", "mainnet launch", "grayscale",
    "blackrock bitcoin", "bullish", "rally", "breakout", "all-time high", "ath",
]

_BEARISH_KEYWORDS = [
    "sec lawsuit", "exchange hack", "rug pull", "ban", "china ban",
    "crackdown", "insolvency", "exploit", "fud", "exchange collapse",
    "exchange inflow", "whale dump", "whale sell", "mt gox", "bankruptcy",
    "sell-off", "crash", "collapse", "bearish", "regulation ban",
    "fraud", "miner capitulation", "stablecoin depegged", "tax crackdown",
]


def _parse_rss_titles(url: str) -> list[str]:
    """Fetch an RSS feed and return a list of item titles."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SpecialKTrading/2.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        titles = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())
        return titles[:10]  # top 10 per feed
    except Exception as e:
        log.debug(f"RSS parse failed {url}: {e}")
        return []


def get_crypto_news_sentiment() -> dict:
    """
    Scan crypto RSS feeds for bullish/bearish keywords.
    Returns:
        bullish_count (int), bearish_count (int),
        score_delta (float), headlines (list[str]), available (bool)

    score_delta up to ±1.5 based on net sentiment.
    """
    key = "crypto_news"
    cached = _cached(key, ttl=1800)  # 30-min cache
    if cached:
        return cached

    all_titles: list[str] = []
    for feed in _CRYPTO_RSS_FEEDS:
        titles = _parse_rss_titles(feed)
        all_titles.extend(titles)

    bullish = 0
    bearish = 0
    bullish_hits: list[str] = []
    bearish_hits: list[str] = []

    for title in all_titles:
        lower = title.lower()
        matched_bull = any(kw in lower for kw in _BULLISH_KEYWORDS)
        matched_bear = any(kw in lower for kw in _BEARISH_KEYWORDS)
        if matched_bull:
            bullish += 1
            bullish_hits.append(title)
        if matched_bear:
            bearish += 1
            bearish_hits.append(title)

    net = bullish - bearish
    if net >= 3:
        score_delta = 1.0
    elif net >= 1:
        score_delta = 0.5
    elif net == 0:
        score_delta = 0.0
    elif net == -1:
        score_delta = -0.5
    elif net == -2:
        score_delta = -1.0
    else:
        score_delta = -1.5

    # Hard override: heavy regulatory/hack news
    if bearish >= 3:
        score_delta = min(score_delta, -1.5)

    result = {
        "bullish_count": bullish,
        "bearish_count": bearish,
        "score_delta": score_delta,
        "headlines": (bullish_hits + bearish_hits)[:5],
        "available": len(all_titles) > 0,
    }
    _store(key, result)
    return result


# ── Halving Cycle Awareness ───────────────────────────────────────────────────

def get_halving_cycle_score() -> dict:
    """
    Bitcoin halving cycle position. Last halving: April 19, 2024.
    Months 0-18 post-halving = peak bull window (+1.5)
    Months 18-36 = extended bull phase (+0.5)
    Months 36-48 = late cycle, caution (0)
    Beyond = pre-halving bear or next cycle (-0.5)
    """
    import datetime
    key = "halving_cycle"
    cached = _cached(key, ttl=86400)  # cache 24h — changes slowly
    if cached:
        return cached

    LAST_HALVING = datetime.date(2024, 4, 19)
    today = datetime.date.today()
    months_since = (today - LAST_HALVING).days / 30.44

    if months_since <= 18:
        score_delta = 1.5
        label = f"peak_bull_window ({months_since:.0f}mo post-halving)"
    elif months_since <= 36:
        score_delta = 0.5
        label = f"extended_bull ({months_since:.0f}mo post-halving)"
    elif months_since <= 48:
        score_delta = 0.0
        label = f"late_cycle ({months_since:.0f}mo post-halving)"
    else:
        score_delta = -0.5
        label = f"pre_halving_bear ({months_since:.0f}mo post-halving)"

    result = {
        "months_post_halving": round(months_since, 1),
        "score_delta": score_delta,
        "label": label,
        "available": True,
    }
    _store(key, result)
    return result


# ── Stablecoin Ratio ──────────────────────────────────────────────────────────

def get_stablecoin_ratio() -> dict:
    """
    USDT + USDC share of total crypto market cap (CoinGecko global endpoint).
    High ratio = dry powder waiting to buy = bullish.
    Low ratio = everyone already in = caution near top.
    """
    key = "stablecoin_ratio"
    cached = _cached(key)
    if cached:
        return cached

    data = _get("https://api.coingecko.com/api/v3/global")
    if not data:
        result = {"ratio": 0.0, "score_delta": 0.0, "available": False}
        _store(key, result)
        return result

    try:
        pcts = data["data"]["market_cap_percentage"]
        stable_pct = pcts.get("usdt", 0) + pcts.get("usdc", 0)

        if stable_pct >= 12.0:
            score_delta = 1.0   # lots of dry powder
        elif stable_pct >= 8.0:
            score_delta = 0.5
        elif stable_pct <= 4.0:
            score_delta = -1.0  # everyone all-in = near top
        else:
            score_delta = 0.0

        result = {"ratio": round(stable_pct, 2), "score_delta": score_delta, "available": True}
    except Exception as e:
        log.warning(f"Stablecoin ratio parse failed: {e}")
        result = {"ratio": 0.0, "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


# ── Open Interest Trend ───────────────────────────────────────────────────────

def get_open_interest_trend(symbol: str) -> dict:
    """
    Binance perp futures open interest (free, no key).
    Rising OI = new money entering, trend has legs (+1).
    Falling OI = positions closing, trend weakening (-0.5).
    """
    binance_sym = _BINANCE_SYMBOL_MAP.get(symbol)
    if not binance_sym:
        return {"oi": 0.0, "score_delta": 0.0, "available": False}

    key = f"oi_{binance_sym}"
    cached = _cached(key, ttl=900)
    if cached:
        return cached

    url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={binance_sym}"
    data = _get(url)
    if not data:
        result = {"oi": 0.0, "score_delta": 0.0, "label": "unavailable", "available": False}
        _store(key, result)
        return result

    try:
        oi = float(data.get("openInterest", 0))
        prev_key = f"oi_prev_{binance_sym}"
        prev = _cache.get(prev_key)
        prev_oi = prev[1] if prev else None
        _store(prev_key, oi)

        if prev_oi and prev_oi > 0:
            pct_change = (oi - prev_oi) / prev_oi * 100
            if pct_change > 2.0:
                score_delta = 1.0
                label = f"oi_rising +{pct_change:.1f}%"
            elif pct_change < -2.0:
                score_delta = -0.5
                label = f"oi_falling {pct_change:.1f}%"
            else:
                score_delta = 0.0
                label = "oi_stable"
        else:
            score_delta = 0.0
            label = "oi_first_read"

        result = {"oi": round(oi, 0), "score_delta": score_delta, "label": label, "available": True}
    except Exception as e:
        log.warning(f"OI parse failed {symbol}: {e}")
        result = {"oi": 0.0, "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


# ── BTC Macro Cycle (200-day EMA) ─────────────────────────────────────────────

def get_btc_macro_cycle() -> dict:
    """
    Is BTC above or below its 200-day EMA? Above = macro bull, below = macro bear.
    Cached 6h — this is a slow-moving signal.
    """
    key = "btc_macro_cycle"
    cached = _cached(key, ttl=21600)  # 6h cache
    if cached:
        return cached

    try:
        from .crypto_data import CryptoDataClient
        from .indicators import compute_crypto_indicators
        bars = CryptoDataClient().get_daily_bars("BTC/USD", lookback_days=210)
        if bars is None or len(bars) < 60:
            result = {"phase": "unknown", "score_delta": 0.0, "available": False}
            _store(key, result)
            return result

        df = compute_crypto_indicators(bars)
        last = df.iloc[-1]
        close = float(last["close"])
        ema200 = float(last.get("ema200") or close)

        if close > ema200 * 1.02:
            phase, score_delta = "bull", 1.0
        elif close < ema200 * 0.98:
            phase, score_delta = "bear", -1.0
        else:
            phase, score_delta = "neutral", 0.0

        result = {
            "phase": phase,
            "close": round(close, 2),
            "ema200": round(ema200, 2),
            "score_delta": score_delta,
            "available": True,
        }
    except Exception as e:
        log.warning(f"BTC macro cycle failed: {e}")
        result = {"phase": "unknown", "score_delta": 0.0, "available": False}

    _store(key, result)
    return result


# ── Composite market context ──────────────────────────────────────────────────

def get_market_context(symbol: str) -> dict:
    """
    Aggregate all 5 layers of crypto market signals.
    Layer 1: Macro cycle (BTC 200d EMA)
    Layer 2: Sentiment (Fear & Greed)
    Layer 3: On-chain (dominance + funding + OI + stablecoin ratio)
    Layer 4: News/narrative
    Layer 5: Technical (handled per-symbol in CryptoStrategy)

    Returns combined context dict with total_on_chain_score.
    """
    fg      = get_fear_greed()
    dom     = get_btc_dominance()
    fund    = get_funding_rate(symbol)
    news    = get_crypto_news_sentiment()
    btc_chg = get_btc_1h_change()
    halving = get_halving_cycle_score()
    stable  = get_stablecoin_ratio()
    oi      = get_open_interest_trend(symbol)
    macro   = get_btc_macro_cycle()

    total = (
        fg["score_delta"]
        + dom["score_delta"]
        + fund["score_delta"]
        + news["score_delta"]
        + halving["score_delta"]
        + stable["score_delta"]
        + oi["score_delta"]
        + macro["score_delta"]
    )
    total = max(-4.0, min(4.0, total))  # clamp ±4 (more signals = wider range)

    return {
        "fear_greed":        fg,
        "btc_dominance":     dom,
        "funding":           fund,
        "news":              news,
        "btc_1h_change":     round(btc_chg, 2),
        "bitcoin_season":    is_bitcoin_season(),
        "halving":           halving,
        "stablecoin_ratio":  stable,
        "open_interest":     oi,
        "macro_cycle":       macro,
        "total_on_chain_score": round(total, 2),
    }
