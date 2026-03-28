"""
Hedge Manager — automatically opens offsetting positions when the portfolio
drawdown exceeds a configurable threshold.

Forex hedge logic:
  Long FXE/FXB/FXA/FXC/FXY → hedge with UUP (USD strengthens when these fall)
  Long UUP                  → hedge with FXE (EUR strengthens when USD falls)

Hedge lifecycle:
  1. Each engine run: check total unrealized P&L % across all positions.
  2. If below -hedge_trigger_pct → open hedge (once per instrument, skips if already open).
  3. If recovered above -hedge_trigger_pct + buffer → close hedge.
  4. Hedge size = hedge_ratio × original position market value.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Maps a watched symbol to its hedge instrument
HEDGE_MAP: Dict[str, str] = {
    "FXE": "UUP",
    "FXB": "UUP",
    "FXA": "UUP",
    "FXC": "UUP",
    "FXY": "UUP",
    "UUP": "FXE",   # if long dollar, hedge with euro
}

# Instruments we treat as hedges (so the engine doesn't try to hedge hedges)
HEDGE_INSTRUMENTS = set(HEDGE_MAP.values())


class HedgeManager:
    def __init__(self, config):
        self.config = config
        # drawdown % that triggers a hedge (negative number, e.g. 1.5 means -1.5%)
        self.trigger_pct: float = getattr(config, "hedge_trigger_pct", 1.5)
        # % recovery buffer before closing hedge (avoid whipsaw)
        self.recovery_buffer: float = getattr(config, "hedge_recovery_buffer", 0.5)
        # fraction of losing position value to hedge (0.5 = 50%)
        self.ratio: float = getattr(config, "hedge_ratio", 0.5)
        self.enabled: bool = getattr(config, "hedge_enabled", True)

    # ── Evaluation ────────────────────────────────────────────────────────────

    def portfolio_unrealized_pct(self, positions, equity: float) -> float:
        """Total unrealized P&L as % of equity."""
        if equity <= 0:
            return 0.0
        total_unreal = sum(
            float(getattr(p, "unrealized_pl", 0) or 0)
            for p in positions.values()
            if p.symbol not in HEDGE_INSTRUMENTS
        )
        return (total_unreal / equity) * 100

    def needs_hedge(self, positions, equity: float) -> bool:
        """True when portfolio drawdown exceeds the trigger threshold."""
        if not self.enabled:
            return False
        pnl_pct = self.portfolio_unrealized_pct(positions, equity)
        return pnl_pct < -self.trigger_pct

    def should_close_hedge(self, positions, equity: float) -> bool:
        """True when portfolio has recovered enough to close the hedge."""
        pnl_pct = self.portfolio_unrealized_pct(positions, equity)
        return pnl_pct >= -(self.trigger_pct - self.recovery_buffer)

    # ── Sizing ────────────────────────────────────────────────────────────────

    def hedge_qty(self, losing_positions, fetcher) -> Dict[str, int]:
        """
        Returns {hedge_symbol: qty} for each unique hedge instrument needed.
        Consolidates multiple positions that map to the same hedge instrument.
        """
        hedge_totals: Dict[str, float] = {}
        for pos in losing_positions.values():
            sym = pos.symbol
            if sym in HEDGE_INSTRUMENTS:
                continue
            hedge_sym = HEDGE_MAP.get(sym)
            if hedge_sym is None:
                continue
            unreal_pct = float(getattr(pos, "unrealized_plpc", 0) or 0) * 100
            if unreal_pct >= -self.trigger_pct:
                continue  # only hedge genuinely losing positions
            mktval = abs(float(getattr(pos, "market_value", 0) or 0))
            hedge_totals[hedge_sym] = hedge_totals.get(hedge_sym, 0.0) + mktval * self.ratio

        result: Dict[str, int] = {}
        for hedge_sym, notional in hedge_totals.items():
            bars = fetcher.get_daily_bars(hedge_sym)
            if bars is None or len(bars) == 0:
                logger.warning(f"Hedge: no bars for {hedge_sym}, skipping")
                continue
            price = float(bars.iloc[-1]["close"])
            qty = int(notional / price)
            if qty >= 1:
                result[hedge_sym] = qty
        return result

    # ── Open / Close ──────────────────────────────────────────────────────────

    def open_hedges(self, broker, fetcher, positions, dry_run: bool = False):
        """Open hedge positions for any currently losing positions."""
        hedge_qtys = self.hedge_qty(positions, fetcher)
        opened = []
        existing = {p.symbol for p in broker.get_positions()}
        for hedge_sym, qty in hedge_qtys.items():
            if hedge_sym in existing:
                logger.info(f"Hedge: {hedge_sym} already open — skipping.")
                continue
            bars = fetcher.get_daily_bars(hedge_sym)
            if bars is None or len(bars) == 0:
                continue
            price = float(bars.iloc[-1]["close"])
            atr   = float(bars.iloc[-1].get("atr", price * 0.005) or price * 0.005)
            stop  = round(price - 1.5 * atr, 4)
            tp    = round(price + 2.0 * atr, 4)
            logger.info(
                f"HEDGE OPEN {hedge_sym}: qty={qty} price={price:.4f} "
                f"stop={stop:.4f} tp={tp:.4f}"
            )
            if not dry_run:
                try:
                    broker.place_bracket_buy(hedge_sym, qty, price, stop, tp)
                    opened.append(hedge_sym)
                except Exception as exc:
                    logger.error(f"Hedge order failed for {hedge_sym}: {exc}")
        return opened

    def close_hedges(self, broker, dry_run: bool = False):
        """Close all open hedge positions."""
        positions = broker.get_positions()
        closed = []
        for pos in positions:
            if pos.symbol in HEDGE_INSTRUMENTS:
                logger.info(f"HEDGE CLOSE {pos.symbol}: portfolio recovered.")
                if not dry_run:
                    try:
                        broker.close_position(pos.symbol)
                        closed.append(pos.symbol)
                    except Exception as exc:
                        logger.error(f"Hedge close failed for {pos.symbol}: {exc}")
        return closed

    def status(self, broker, positions, equity: float) -> dict:
        """Return hedge status dict for the API."""
        open_hedges = [
            p.symbol for p in broker.get_positions()
            if p.symbol in HEDGE_INSTRUMENTS
        ]
        pnl_pct = self.portfolio_unrealized_pct(positions, equity)
        return {
            "enabled":      self.enabled,
            "trigger_pct":  self.trigger_pct,
            "ratio":        self.ratio,
            "pnl_pct":      round(pnl_pct, 2),
            "hedged":       len(open_hedges) > 0,
            "open_hedges":  open_hedges,
            "needs_hedge":  self.needs_hedge(positions, equity),
        }
