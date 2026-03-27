"""
Political / Congressional Trade Tracker

Pulls recent stock trades disclosed by US Congress members (STOCK Act filings).
Uses the free Capitol Trades public API — no key required.

For each symbol in the watchlist we check:
  - Any buys in last 90 days → bullish signal boost
  - Any sells in last 90 days → bearish warning

Returns a summary string for AI analysis and a numeric score delta (+1/-1/0).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

# Simple in-memory cache: {symbol: (timestamp, result)}
_cache: dict = {}
_CACHE_TTL = 3600  # 1 hour


def _fetch_capitol_trades(symbol: str) -> list:
    """Fetch recent congressional trades for a symbol from Capitol Trades API."""
    try:
        import urllib.request, json
        url = f"https://capitoltrades.com/api/trades?ticker={symbol}&pageSize=20"
        req = urllib.request.Request(url, headers={"User-Agent": "SpecialKTrading/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        log.debug(f"Capitol Trades fetch failed for {symbol}: {e}")
        return []


def _fetch_quiver_quant(symbol: str) -> list:
    """Fallback: Quiver Quant congressional trading data."""
    try:
        import urllib.request, json
        url = f"https://api.quiverquant.com/beta/live/congresstrading/{symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "SpecialKTrading/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.debug(f"Quiver Quant fetch failed for {symbol}: {e}")
        return []


def get_political_signal(symbol: str) -> dict:
    """
    Returns dict with:
      score_delta: int  (+1 buys outweigh sells, -1 sells, 0 neutral)
      summary: str      human-readable summary for AI analyst
      trades: list      raw recent trades
    """
    now = time.time()
    if symbol in _cache:
        ts, cached = _cache[symbol]
        if now - ts < _CACHE_TTL:
            return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    trades = _fetch_capitol_trades(symbol)

    # Try quiver quant as fallback if no results
    if not trades:
        trades = _fetch_quiver_quant(symbol)

    buys, sells, names = [], [], []
    for t in trades:
        # Capitol Trades format
        tx_date_str = t.get("txDate") or t.get("transaction_date") or t.get("Date", "")
        tx_type = (t.get("txType") or t.get("type") or t.get("Transaction", "")).lower()
        politician = t.get("politician", {})
        name = politician.get("name") if isinstance(politician, dict) else t.get("Representative") or t.get("Senator", "Unknown")

        try:
            if tx_date_str:
                tx_date = datetime.fromisoformat(tx_date_str.replace("Z", "+00:00"))
                if tx_date < cutoff:
                    continue
        except Exception:
            pass

        if "buy" in tx_type or "purchase" in tx_type:
            buys.append(name)
        elif "sell" in tx_type or "sale" in tx_type:
            sells.append(name)

    score_delta = 0
    if len(buys) > len(sells):
        score_delta = 1
    elif len(sells) > len(buys):
        score_delta = -1

    if buys or sells:
        buy_names  = ", ".join(set(str(n) for n in buys[:3]))  if buys  else "none"
        sell_names = ", ".join(set(str(n) for n in sells[:3])) if sells else "none"
        summary = f"{len(buys)} congressional buy(s) [{buy_names}], {len(sells)} sell(s) [{sell_names}] in last 90 days"
    else:
        summary = "No recent congressional trades found"

    result = {"score_delta": score_delta, "summary": summary, "buys": len(buys), "sells": len(sells)}
    _cache[symbol] = (now, result)
    return result
