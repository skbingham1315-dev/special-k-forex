"""
Crypto Engine — runs 24/7, trades BTC/ETH/SOL etc. using the Special K v2.0
crypto strategy with on-chain intelligence (Fear & Greed, BTC dominance,
funding rates, news sentiment, BTC correlation rules).
Uses Alpaca's crypto trading API (same TradingClient, GTC orders).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from .config import Settings as Config
from .crypto_data import CryptoDataClient, CRYPTO_SYMBOLS
from .indicators import compute_indicators, classify_regime
from .risk import RiskManager
from .strategy import ForexETFStrategy as TrendPullbackStrategy
from .ai_analyst import analyse_crypto_signal
from .crypto_signals import (
    get_market_context,
    btc_flash_crash_active,
    get_fear_greed,
)

log = logging.getLogger(__name__)

# Symbols considered "majors" — tradeable during Bitcoin Season
_BTC_MAJORS = {"BTC/USD", "ETH/USD", "BTCUSD", "ETHUSD"}


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

        # ── Fetch market-wide context once (cached 1h) ────────────────────
        mkt = get_market_context("BTC/USD")
        fg  = mkt["fear_greed"]
        dom = mkt["btc_dominance"]
        news = mkt["news"]
        btc_chg = mkt["btc_1h_change"]
        bitcoin_season = mkt["bitcoin_season"]
        on_chain_score = mkt["total_on_chain_score"]

        log.info(
            f"  Market context — F&G: {fg.get('value','?')} ({fg.get('label','?')}) | "
            f"BTC Dom: {dom.get('pct','?'):.1f}% ({'rising' if dom.get('rising') else 'falling' if dom.get('rising') is False else '?'}) | "
            f"BTC 1H: {btc_chg:+.2f}% | News: {news.get('bullish_count',0)}↑/{news.get('bearish_count',0)}↓ | "
            f"On-chain score: {on_chain_score:+.2f}"
        )

        # ── Kill switch: Fear & Greed < 10 (capitulation) ─────────────────
        if fg.get("available") and fg.get("value", 50) < 10:
            log.warning("F&G capitulation (<10) — halting all crypto entries. Wait for bounce.")
            return

        # ── Kill switch: BTC flash crash (>3% drop in 1H) ─────────────────
        if btc_flash_crash_active():
            log.warning(f"BTC flash crash detected ({btc_chg:.2f}% in 1H) — halting all entries.")
            return

        # ── Kill switch: heavy bearish news ───────────────────────────────
        if news.get("available") and news.get("bearish_count", 0) >= 4:
            log.warning(f"Heavy bearish news ({news['bearish_count']} bearish headlines) — halting entries.")
            return

        # ── EXIT PASS — close all positions that hit exit conditions ──────────
        # Handles both crypto AND any legacy equity positions (BA, EEM, USO etc.)
        try:
            all_positions = {p.symbol: p for p in broker.get_positions()}
        except Exception:
            all_positions = {}

        _crypto_keys = {s.replace("/", "") for s in CRYPTO_SYMBOLS}

        for sym_key, pos in list(all_positions.items()):
            side_val = getattr(pos.side, "value", str(pos.side)).lower()
            side = "long" if "long" in side_val else "short"

            if sym_key in _crypto_keys:
                # Use crypto data client
                crypto_sym = next((s for s in CRYPTO_SYMBOLS if s.replace("/", "") == sym_key), None)
                bars = self.fetcher.get_daily_bars(crypto_sym) if crypto_sym else None
            else:
                # Use equity data client for legacy positions
                try:
                    from .data import MarketDataClient
                    bars = MarketDataClient().get_daily_bars(sym_key)
                except Exception:
                    bars = None

            if bars is None or len(bars) < 60:
                continue
            should_exit, reason = self.strategy.should_exit(bars, side=side)
            if should_exit:
                log.info(f"  EXIT {sym_key} [{side}]: {reason}")
                if not self.dry_run:
                    try:
                        broker.close_position(sym_key)
                    except Exception as exc:
                        log.error(f"  Exit failed {sym_key}: {exc}")

        # Get open positions
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

        # ── Bitcoin Season: only majors ────────────────────────────────────
        if bitcoin_season:
            log.info(f"  Bitcoin Season active (BTC dom {dom.get('pct','?'):.1f}%) — restricting to BTC/ETH only.")
            symbols_to_scan = [s for s in symbols_to_scan if s in _BTC_MAJORS]

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
                # Boost score with on-chain composite
                best.score = round(best.score + on_chain_score)
                candidates.append(best)
                log.info(f"  {symbol}: {best.direction} score={best.score} (on-chain adj)")
            else:
                log.info(f"  {symbol}: no signal")

        candidates.sort(key=lambda s: s.score, reverse=True)

        # ── Fear & Greed sizing multiplier ─────────────────────────────────
        fg_value = fg.get("value", 50)
        if fg_value <= 25:
            fg_size_mult = 1.25   # Extreme Fear: size up 25%
        elif fg_value >= 75:
            fg_size_mult = 0.5    # Extreme Greed: size down 50%
        elif btc_chg <= -5.0:
            fg_size_mult = 0.25   # BTC down 5%+ intraday: size down 75%
        else:
            fg_size_mult = 1.0

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

            # Recompute indicators for the AI call
            bars = self.fetcher.get_daily_bars(signal.symbol)
            indic = compute_indicators(bars) if bars is not None else {}
            last_row = indic.iloc[-1].to_dict() if hasattr(indic, "iloc") and len(indic) else {}
            regime = classify_regime(indic)

            # Get per-symbol on-chain context (funding rate differs per symbol)
            sym_ctx = get_market_context(signal.symbol)

            ai = analyse_crypto_signal(
                symbol=signal.symbol,
                regime=regime,
                score=signal.score,
                rsi=float(last_row.get("rsi", 50) or 50),
                adx=float(last_row.get("adx", 20) or 20),
                atr=atr,
                price=price,
                sma50=float(last_row.get("sma50", price) or price),
                sma200=float(last_row.get("sma200", price) or price),
                macd_hist=float(last_row.get("macd_hist", 0) or 0),
                pullback_10d_pct=float(last_row.get("pullback_10d_pct", 0) or 0),
                notes=signal.notes,
                direction=signal.direction,
                on_chain_context=sym_ctx,
            )

            log.info(f"  {signal.symbol}: AI conf={ai['confidence']} action={ai['action']} [{signal.direction}] — {ai['reason']}")

            if ai["confidence"] <= 4:
                log.info(f"  {signal.symbol}: AI hard reject (conf≤4) — skipping.")
                continue

            risk_pct = 0.3 if signal.direction == "bounce" else self.config.risk_per_trade_pct

            if ai["action"] == "skip" or ai["confidence"] <= 5:
                risk_pct *= 0.25
                log.info(f"  {signal.symbol}: AI low conf — quarter size.")
            elif ai["action"] == "reduce" or ai["confidence"] <= 6:
                risk_pct *= 0.5
                log.info(f"  {signal.symbol}: AI reduce — halving size.")
            elif ai["confidence"] >= 8 and regime == "active":
                risk_pct = min(risk_pct * 1.25, 2.0)

            # Apply Fear & Greed sizing multiplier
            risk_pct = risk_pct * fg_size_mult
            if fg_size_mult != 1.0:
                log.info(f"  {signal.symbol}: F&G size mult={fg_size_mult:.2f} (F&G={fg_value})")

            plan = self.risk.shares_for_trade(price, atr, equity, stop, tp, risk_pct_override=risk_pct)

            if budget_remaining < float("inf"):
                max_notional = min(plan.qty * price, budget_remaining)
                plan.qty = round(max_notional / price, 6)

            if plan.qty < 0.000001:
                log.info(f"  {signal.symbol}: qty too small — skipping")
                continue

            log.info(f"  CRYPTO ENTRY [{signal.direction.upper()}] {signal.symbol}: "
                     f"qty={plan.qty:.6f} price=${price:.2f} stop=${stop:.2f} tp=${tp:.2f} "
                     f"regime={regime} score={signal.score} AI={ai['confidence']}")

            if not self.dry_run:
                try:
                    _place_crypto_bracket(broker.client, signal.symbol, plan.qty, price, stop, tp)
                    budget_remaining -= plan.qty * price
                    active += 1
                except Exception as exc:
                    log.error(f"  Crypto order failed for {signal.symbol}: {exc}")
            else:
                active += 1
