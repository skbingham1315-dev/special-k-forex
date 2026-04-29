"""
AI Analyst — Claude-powered signal validation for Special K Forex.

Each candidate signal is evaluated by Claude (haiku) before a trade is placed.
Claude receives a structured summary of the indicator data, market regime, and
recent congressional trading activity, then returns:
  - confidence: 1–10
  - action: "enter" | "skip" | "reduce"
  - reason: one sentence

A confidence < 5 skips the trade. 5–7 uses normal sizing. 8+ sizes up slightly.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

try:
    from .trader_brain import get_brain_context
    _BRAIN_AVAILABLE = True
except ImportError:
    _BRAIN_AVAILABLE = False
    def get_brain_context(**kwargs) -> str:
        return ""

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
            key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not key:
                return None
            _client = anthropic.Anthropic(api_key=key)
        except ImportError:
            log.warning("anthropic package not installed — AI analysis disabled")
            return None
    return _client


def analyse_signal(
    symbol: str,
    pair: str,
    regime: str,
    score: int,
    rsi: float,
    adx: float,
    atr: float,
    price: float,
    sma50: float,
    sma200: float,
    macd_hist: float,
    pullback_10d_pct: float,
    notes: list,
    political_activity: Optional[str] = None,
    trend_memory: Optional[str] = None,
    direction: str = "long",
) -> dict:
    """
    Ask Claude to validate a trading signal.

    Returns dict with keys: confidence (int 1-10), action (str), reason (str), raw (str)
    Falls back gracefully if API is unavailable.
    """
    client = _get_client()
    if client is None:
        return {"confidence": 5, "action": "enter", "reason": "AI analysis unavailable — proceeding at reduced confidence.", "raw": ""}

    trend_desc = "above both SMA50 and SMA200 (uptrend)" if price > sma50 > sma200 else \
                 "above SMA50 but below SMA200 (partial trend)" if price > sma50 else \
                 "below SMA50 (downtrend)"

    political_section = f"\nCongressional trading activity: {political_activity}" if political_activity else ""
    memory_section = f"\nLearned trend context: {trend_memory}" if trend_memory else ""

    # Pull relevant sections from the synthesized trading knowledge base
    near_52w_high = price >= sma200 * 1.05  # rough proxy
    brain_context = get_brain_context(
        regime=regime,
        direction=direction,
        rsi=rsi,
        adx=adx,
        volume_ratio=1.0,  # not available at this call site
        near_52w_high=near_52w_high,
    )
    brain_section = f"\n\n=== TRADING KNOWLEDGE BASE (apply these principles) ===\n{brain_context}" if brain_context else ""

    direction_context = {
        "long":   "LONG (trend-pullback buy): price in uptrend, RSI dipped 30-50, expecting bounce higher.",
        "short":  "SHORT (trend-continuation sell): price in downtrend, RSI bounced to 52-75, expecting resumption lower.",
        "bounce": "BOUNCE (counter-trend long): RSI extremely oversold <22, expecting violent snap-back to SMA50. RISKY — needs strong conviction.",
    }.get(direction, "LONG")

    prompt = f"""You are a quantitative trading analyst reviewing a forex ETF signal for Special K Trading.

Instrument: {symbol} ({pair})
Trade type: {direction_context}
Current price: ${price:.4f}
Market regime: {regime.upper()} (ADX={adx:.1f})
Trend: {trend_desc} — SMA50=${sma50:.4f}, SMA200=${sma200:.4f}
RSI(14): {rsi:.1f}
ATR(14): {atr:.4f} ({atr/price*100:.2f}% of price)
MACD histogram: {macd_hist:.5f} ({'positive' if macd_hist > 0 else 'negative'})
10-day move: {pullback_10d_pct:.2f}%
Quant signal score: {score}/10
Signal notes: {', '.join(notes)}{political_section}{memory_section}{brain_section}

Based on these indicators AND the trading knowledge base above, should we enter this {direction.upper()} trade?

Respond in exactly this JSON format (no other text):
{{"confidence": <1-10>, "action": "<enter|skip|reduce>", "reason": "<one sentence max 15 words>"}}

Rules:
- confidence 8-10: strong setup, clear trend + pullback alignment
- confidence 5-7: decent setup, proceed with normal sizing
- confidence 1-4: weak or risky setup, skip
- action "reduce": enter but use half normal size
- Be direct and data-driven. No hedging."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        import json
        # Parse the JSON response
        data = json.loads(raw)
        confidence = int(data.get("confidence", 7))
        action = data.get("action", "enter")
        reason = data.get("reason", "No reason provided.")
        log.info(f"AI [{symbol}]: confidence={confidence} action={action} | {reason}")
        return {"confidence": confidence, "action": action, "reason": reason, "raw": raw}
    except Exception as e:
        log.warning(f"AI analysis failed for {symbol}: {e}")
        return {"confidence": 5, "action": "enter", "reason": f"AI error — proceeding at reduced confidence.", "raw": ""}


def analyse_crypto_signal(
    symbol: str,
    regime: str,
    score: int,
    rsi: float,
    adx: float,
    atr: float,
    price: float,
    sma50: float,
    sma200: float,
    macd_hist: float,
    pullback_10d_pct: float,
    notes: list,
    direction: str = "long",
    on_chain_context: Optional[dict] = None,
) -> dict:
    """
    Ask Claude to validate a crypto trading signal.
    Same return shape as analyse_signal: confidence, action, reason, raw.
    """
    client = _get_client()
    if client is None:
        return {"confidence": 5, "action": "enter", "reason": "AI analysis unavailable — proceeding at reduced confidence.", "raw": ""}

    trend_desc = "above both EMA20 and EMA50 (uptrend)" if price > sma50 > sma200 else \
                 "above EMA20 but below EMA50 (partial trend)" if price > sma50 else \
                 "below EMA20 (downtrend)"

    direction_context = {
        "long":   "LONG (trend-pullback buy): price in uptrend, RSI dipped 30-50, expecting bounce higher.",
        "short":  "SHORT (trend-continuation sell): price in downtrend, RSI bounced to 52-75, expecting resumption lower.",
        "bounce": "BOUNCE (counter-trend long): RSI extremely oversold <22, expecting violent snap-back. RISKY — needs strong conviction.",
    }.get(direction, "LONG")

    # Build on-chain context section
    ctx = on_chain_context or {}
    fg   = ctx.get("fear_greed", {})
    dom  = ctx.get("btc_dominance", {})
    fund = ctx.get("funding", {})
    news = ctx.get("news", {})
    btc_chg = ctx.get("btc_1h_change", 0.0)
    on_chain_score = ctx.get("total_on_chain_score", 0.0)

    on_chain_lines = []
    if fg.get("available"):
        on_chain_lines.append(f"Fear & Greed Index: {fg['value']}/100 ({fg['label']}) → score delta {fg['score_delta']:+.1f}")
    if dom.get("available"):
        direction_str = "RISING (flight to BTC, bad for alts)" if dom.get("rising") else "FALLING (altcoin season risk-on)" if dom.get("rising") is False else "direction unknown"
        on_chain_lines.append(f"BTC Dominance: {dom['pct']:.1f}% — {direction_str} → score delta {dom['score_delta']:+.1f}")
    if fund.get("available"):
        rate_pct = fund['rate'] * 100
        on_chain_lines.append(f"Funding Rate: {rate_pct:.4f}% ({'negative=oversold' if fund['rate'] < 0 else 'positive=longs paying'}) → score delta {fund['score_delta']:+.1f}")
    if btc_chg != 0.0:
        on_chain_lines.append(f"BTC 1H change: {btc_chg:+.2f}%")
    if news.get("available"):
        on_chain_lines.append(f"Crypto news: {news['bullish_count']} bullish / {news['bearish_count']} bearish headlines → score delta {news['score_delta']:+.1f}")
        if news.get("headlines"):
            on_chain_lines.append(f"Top headlines: {'; '.join(news['headlines'][:3])}")

    on_chain_section = ""
    if on_chain_lines:
        on_chain_section = "\n\nOn-Chain & Market Intelligence:\n" + "\n".join(f"  {l}" for l in on_chain_lines)
        on_chain_section += f"\n  Composite on-chain score: {on_chain_score:+.2f}"

    prompt = f"""You are a quantitative crypto trading analyst using the Special K v2.0 strategy framework.

Asset: {symbol}
Trade type: {direction_context}
Current price: ${price:.4f}
Market regime: {regime.upper()} (ADX={adx:.1f})
Trend: {trend_desc} — EMA20=${sma50:.4f}, EMA50=${sma200:.4f}
RSI(14): {rsi:.1f}
ATR(14): {atr:.4f} ({atr/price*100:.2f}% of price — crypto volatility)
MACD histogram: {macd_hist:.5f} ({'positive' if macd_hist > 0 else 'negative'})
10-day move: {pullback_10d_pct:.2f}%
Quant signal score: {score}/10
Signal notes: {', '.join(notes)}{on_chain_section}

Key rules:
- Only take longs when price is above 50 EMA daily (trend alignment)
- Fear & Greed < 25 = Extreme Fear is a BUY signal; > 75 = avoid longs
- Rising BTC dominance = favor BTC/ETH only, skip alts
- Negative funding rate = oversold bounce opportunity
- Bearish news (SEC lawsuit, hack, ban) = hard skip regardless of technicals
- Altcoins require extra caution vs BTC/ETH (2.5x volatility)

Should we enter this {direction.upper()} trade?

Respond in exactly this JSON format (no other text):
{{"confidence": <1-10>, "action": "<enter|skip|reduce>", "reason": "<one sentence max 15 words>"}}

Rules:
- confidence 8-10: strong setup with on-chain confirmation
- confidence 5-7: decent setup, proceed with normal sizing
- confidence 1-4: weak, risky, or bearish news environment — skip
- action "reduce": enter but use half normal size
- Be direct and data-driven. No hedging."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        import json
        data = json.loads(raw)
        confidence = int(data.get("confidence", 7))
        action = data.get("action", "enter")
        reason = data.get("reason", "No reason provided.")
        log.info(f"AI [{symbol}]: confidence={confidence} action={action} | {reason}")
        return {"confidence": confidence, "action": action, "reason": reason, "raw": raw}
    except Exception as e:
        log.warning(f"AI crypto analysis failed for {symbol}: {e}")
        return {"confidence": 5, "action": "enter", "reason": f"AI error — proceeding at reduced confidence.", "raw": ""}


def analyse_market_overview(symbols_data: list) -> str:
    """
    Ask Claude for a brief macro take on the current forex ETF landscape.
    Used for the dashboard overview panel.
    Returns a 2-3 sentence market summary string.
    """
    client = _get_client()
    if client is None:
        return ""

    lines = []
    for s in symbols_data:
        lines.append(
            f"  {s['symbol']} ({s['pair']}): price={s.get('last_close','?')}, "
            f"RSI={s.get('rsi','?')}, ADX={s.get('adx','?')}, "
            f"regime={s.get('regime','normal')}, trend={'UP' if s.get('trend_up') else 'DOWN'}"
        )
    summary = "\n".join(lines)

    prompt = f"""You are a forex market analyst. Here is the current state of 6 forex ETFs:

{summary}

Give a 2-sentence macro summary of what this data tells us about currency markets right now.
Be specific about which currencies look strongest/weakest. Plain text only, no markdown."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning(f"Market overview AI failed: {e}")
        return ""


def analyse_crypto_market_overview(symbols_data: list) -> str:
    """
    Ask Claude for a brief macro take on the current crypto landscape.
    Used for the dashboard overview panel.
    Returns a 2-3 sentence market summary string.
    """
    client = _get_client()
    if client is None:
        return ""

    lines = []
    for s in symbols_data:
        lines.append(
            f"  {s['symbol']}: price={s.get('last_close','?')}, "
            f"RSI={s.get('rsi','?')}, ADX={s.get('adx','?')}, "
            f"regime={s.get('regime','normal')}, trend={'UP' if s.get('trend_up') else 'DOWN'}"
        )
    summary = "\n".join(lines)

    prompt = f"""You are a crypto market analyst. Here is the current state of these crypto assets:

{summary}

Give a 2-sentence macro summary of what this data tells us about the crypto market right now.
Be specific about which assets look strongest/weakest and whether BTC is leading. Plain text only, no markdown."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning(f"Crypto market overview AI failed: {e}")
        return ""
