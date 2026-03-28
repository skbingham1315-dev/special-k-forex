"""
AI Trend Memory — Claude learns and remembers market trends over time.

On startup and once daily, Claude analyzes recent price history for each symbol
and builds a "market intelligence" snapshot. This gets fed into every signal
analysis so Claude has context beyond just the current bar's indicators.

Memory structure (per symbol):
  - trend_direction: "bullish" | "bearish" | "neutral"
  - trend_strength: "strong" | "moderate" | "weak"
  - key_support: float
  - key_resistance: float
  - pattern_notes: str  (what's forming, e.g. "double bottom", "compression")
  - macro_context: str  (why this currency is moving)
  - watch_for: str      (what would trigger a trade signal)
  - last_updated: str

Plus a macro_overview: Claude's read on the overall currency landscape.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# In-memory store — rebuilt on startup, refreshed every 24h
_memory: dict = {
    "symbols": {},
    "macro_overview": "",
    "last_updated": None,
    "refresh_interval": 86400,  # 24 hours
}

_REFRESH_INTERVAL = 86400  # 24 hours


def _get_client():
    try:
        import anthropic
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not key:
            return None
        return anthropic.Anthropic(api_key=key)
    except ImportError:
        return None


def _price_summary(df) -> str:
    """Convert last 30 days of OHLCV to a compact text description for Claude."""
    recent = df.tail(30).copy()
    lines = []
    for _, row in recent.iterrows():
        try:
            date = str(row.name)[:10] if hasattr(row.name, '__str__') else "?"
            lines.append(
                f"{date}: O={row['open']:.4f} H={row['high']:.4f} L={row['low']:.4f} "
                f"C={row['close']:.4f} V={int(row['volume'])}"
            )
        except Exception:
            continue
    return "\n".join(lines)


def build_symbol_memory(symbol: str, pair: str, df, indicators_df) -> dict:
    """Ask Claude to analyze a symbol's recent price history and build trend memory."""
    client = _get_client()
    if client is None:
        return {}

    last = indicators_df.iloc[-1]

    price_data = _price_summary(df)
    prompt = f"""You are a forex market analyst studying {symbol} ({pair}).

Recent 30-day price history (OHLCV):
{price_data}

Current indicators:
- Price: {float(last['close']):.4f}
- SMA50: {float(last['sma50']):.4f} | SMA200: {float(last['sma200']):.4f}
- RSI(14): {float(last['rsi']):.1f}
- ADX: {float(last['adx']):.1f}
- ATR: {float(last['atr14']):.4f}
- BB Upper: {float(last['bb_upper']):.4f} | BB Lower: {float(last['bb_lower']):.4f}
- MACD Hist: {float(last['macd_hist']):.5f}
- 10-day pullback: {float(last['pullback_10d_pct']):.2f}%

Analyze this instrument and respond in exactly this JSON format (no other text):
{{
  "trend_direction": "<bullish|bearish|neutral>",
  "trend_strength": "<strong|moderate|weak>",
  "key_support": <price float>,
  "key_resistance": <price float>,
  "pattern_notes": "<what pattern or structure is forming, max 20 words>",
  "macro_context": "<why this currency pair is moving this way, max 20 words>",
  "watch_for": "<what indicator/price action would trigger a buy signal, max 20 words>",
  "risk_notes": "<key risks to watch, max 15 words>"
}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        data = json.loads(raw)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["symbol"] = symbol
        data["pair"] = pair
        log.info(f"Trend memory built for {symbol}: {data.get('trend_direction')} / {data.get('pattern_notes')}")
        return data
    except Exception as e:
        log.warning(f"Trend memory failed for {symbol}: {e}")
        return {}


def build_macro_overview(symbols_memory: dict) -> str:
    """Ask Claude for a macro overview across all symbols."""
    client = _get_client()
    if client is None:
        return ""

    summaries = []
    for sym, mem in symbols_memory.items():
        if mem:
            summaries.append(
                f"  {sym} ({mem.get('pair', sym)}): {mem.get('trend_direction','?')} / "
                f"{mem.get('trend_strength','?')} — {mem.get('pattern_notes','')}"
            )

    if not summaries:
        return ""

    prompt = f"""You are a macro forex analyst. Here is the current state of 6 currency ETFs:

{chr(10).join(summaries)}

Write 3 sentences:
1. Which currencies are showing the strongest trends and why
2. What the overall USD picture looks like
3. What to watch for in the coming week

Plain text only, no markdown, no bullet points."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=180,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning(f"Macro overview failed: {e}")
        return ""


def refresh_memory(symbols: list, pairs: dict, data_client, indicators_fn) -> None:
    """
    Full memory refresh — call on startup and once daily.
    Runs synchronously; call from a background thread to avoid blocking.
    """
    global _memory
    log.info("Trend memory: starting refresh...")
    updated = {}
    for sym in symbols:
        try:
            bars = data_client.get_daily_bars(sym)
            if bars is None or len(bars) < 60:
                continue
            df_ind = indicators_fn(bars.copy())
            mem = build_symbol_memory(sym, pairs.get(sym, sym), bars, df_ind)
            if mem:
                updated[sym] = mem
            time.sleep(0.3)  # avoid rate-limiting
        except Exception as e:
            log.warning(f"Memory refresh failed for {sym}: {e}")

    macro = build_macro_overview(updated)
    _memory["symbols"] = updated
    _memory["macro_overview"] = macro
    _memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    log.info(f"Trend memory refresh complete: {len(updated)} symbols")


def get_symbol_memory(symbol: str) -> dict:
    """Get cached memory for a symbol."""
    return _memory["symbols"].get(symbol, {})


def get_macro_overview() -> str:
    return _memory.get("macro_overview", "")


def get_all_memory() -> dict:
    return dict(_memory)


def needs_refresh() -> bool:
    ts = _memory.get("last_updated")
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts)
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return age > _REFRESH_INTERVAL
    except Exception:
        return True
