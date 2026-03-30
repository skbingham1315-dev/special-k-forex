"""
Crypto Engine — runs 24/7, trades BTC/ETH/SOL etc. using the same
bounce + trend strategy logic as the equity engine.
Uses Alpaca's crypto trading API (same TradingClient, GTC orders).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from .config import Settings as Config
from .crypto_data import CryptoDataClient, CRYPTO_SYMBOLS
from .indicators import compute_indicators, classify_regime
from .risk import RiskManager
from .strategy import TrendPullbackStrategy

log = logging.getLogger(__name__)


def _place_crypto_bracket(broker_client, symbol: str, qty: float, price: float, stop: float, tp: float):
    """Place a bracket buy order for crypto using GTC (24/7 markets)."""
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    alpaca_sym = symbol.replace("/", "")  # "BTC/USD" -> "BTCUSD"
    limit_price = round(price * 1.001, 2)
    safe_stop   = round(min(stop,  limit_price * 0.999), 2)
    safe_tp     = round(max(tp,    limit_price * 1.001), 2)
    request = LimitOrderRequest(
        symbol=alpaca_sym, qty=round(qty, 6),
        side=OrderSide.BUY,
        limit_price=limit_price,
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=safe_tp),
        stop_loss=StopLossRequest(stop_price=safe_stop),
    )
    return broker_client.submit_order(request)


class CryptoEngine:
    def __init__(self, config: Config, dry_run: bool = False):
        self.config   = config
        self.dry_run  = dry_run
        self.fetcher  = CryptoDataClient()
        self.strategy = TrendPullbackStrategy()
        self.risk     = RiskManager(config)

    def run(self):
        log.info(f"=== Crypto Engine {'(DRY RUN)' if self.dry_run else '(LIVE)'} ==="
                 f" — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        try:
            from .broker import Broker
            broker  = Broker()
            account = broker.get_account()
            equity  = float(account.equity)
            self.risk.set_start_equity(equity)
        except Exception as e:
            log.error(f"Crypto engine account fetch failed: {e}")
            return

        if self.risk.kill_switch_triggered(equity):
            log.warning("Kill switch active — skipping crypto trades.")
            return

        # Get open positions (crypto positions have alpaca_sym format BTCUSD)
        try:
            positions = {p.symbol: p for p in broker.get_positions()}
        except Exception:
            positions = {}

        open_value  = sum(abs(float(p.market_value)) for p in positions.values())
        budget      = getattr(self.config, "trade_budget", 0.0)
        budget_remaining = (budget - open_value) if budget > 0 else float("inf")

        if budget > 0 and open_value >= budget:
            log.info(f"Crypto: budget ${budget:.2f} fully deployed — skipping.")
            return

        crypto_positions = {s for s in positions if len(s) >= 6 and not s.startswith("EW")}
        max_crypto = max(2, self.config.max_positions // 2)

        symbols_to_scan = CRYPTO_SYMBOLS
        env_crypto = getattr(self.config, "crypto_symbols", None)
        if env_crypto:
            symbols_to_scan = [s.strip() for s in env_crypto.split(",") if s.strip()]

        candidates = []
        for symbol in symbols_to_scan:
            alpaca_sym = symbol.replace("/", "")
            if alpaca_sym in crypto_positions:
                continue
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                log.info(f"  {symbol}: insufficient bars")
                continue

            bounce_sig = self.strategy.evaluate_bounce(symbol, bars)
            long_sig   = self.strategy.evaluate(symbol, bars)
            sigs = [s for s in [bounce_sig, long_sig] if s is not None]
            if sigs:
                best = max(sigs, key=lambda s: s.score)
                candidates.append(best)
                log.info(f"  {symbol}: {best.direction} score={best.score}")
            else:
                log.info(f"  {symbol}: no signal")

        candidates.sort(key=lambda s: s.score, reverse=True)

        active = len(crypto_positions)
        for signal in candidates:
            if active >= max_crypto:
                break
            if budget_remaining < 1.0:
                break

            price = signal.last_close
            atr   = signal.atr
            stop  = signal.stop_price
            tp    = signal.take_profit_price

            risk_pct = 0.3 if signal.direction == "bounce" else self.config.risk_per_trade_pct
            plan = self.risk.shares_for_trade(price, atr, equity, stop, tp, risk_pct_override=risk_pct)

            if budget_remaining < float("inf"):
                max_notional = min(plan.qty * price, budget_remaining)
                plan.qty = round(max_notional / price, 6)

            if plan.qty < 0.000001:
                log.info(f"  {signal.symbol}: qty too small — skipping")
                continue

            regime = classify_regime(compute_indicators(self.fetcher.get_daily_bars(signal.symbol) or bars))
            log.info(f"  CRYPTO ENTRY [{signal.direction.upper()}] {signal.symbol}: "
                     f"qty={plan.qty:.6f} price=${price:.2f} stop=${stop:.2f} tp=${tp:.2f} "
                     f"regime={regime} score={signal.score}")

            if not self.dry_run:
                try:
                    _place_crypto_bracket(broker.client, signal.symbol, plan.qty, price, stop, tp)
                    budget_remaining -= plan.qty * price
                    active += 1
                except Exception as exc:
                    log.error(f"  Crypto order failed for {signal.symbol}: {exc}")
            else:
                active += 1
