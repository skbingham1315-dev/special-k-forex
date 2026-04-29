"""
Crypto Engine — runs 24/7, trades BTC/ETH/SOL etc. using the Special K v2.0
crypto strategy with on-chain intelligence (Fear & Greed, BTC dominance,
funding rates, news sentiment, BTC correlation rules).
Uses Alpaca's crypto trading API (same TradingClient, GTC orders).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd
from .config import Settings as Config
from .crypto_data import CryptoDataClient, CRYPTO_SYMBOLS
from .indicators import compute_crypto_indicators, classify_regime
from .risk import RiskManager
from .ai_analyst import analyse_crypto_signal
from .crypto_signals import (
    get_market_context,
    btc_flash_crash_active,
    get_fear_greed,
)


# ── Crypto-native strategy (EMA-based, 60-bar minimum) ───────────────────────

class CryptoStrategy:
    """
    5-layer crypto signal scoring adapted from Special K spec:
    - Trend gate: EMA20 > EMA50 (faster than SMA for 24/7 markets)
    - RSI pullback zone: 40-55 (crypto trends are steeper, less pullback needed)
    - Breakout momentum: price > 20-day high + volume surge
    - Bounce: RSI < 30, extreme oversold snap-back
    - Min bars: 60 (not 220 — crypto has shorter meaningful history)
    - ATR stop: 2.0x  |  ATR target: 4.0x  (wider for crypto volatility)
    """

    MIN_BARS  = 60
    STOP_ATR  = 2.0
    TP_ATR    = 4.0
    MIN_SCORE = 4

    def evaluate(self, symbol: str, df: pd.DataFrame):
        """Trend-pullback long signal using EMA gates."""
        from .strategy import Signal
        if df is None or len(df) < self.MIN_BARS:
            return None
        df = compute_crypto_indicators(df)
        last = df.iloc[-1]

        if pd.isna(last.get("ema50")) or pd.isna(last.get("atr14")):
            return None

        score = 0
        notes = []
        close = float(last["close"])

        # Trend gate: close > EMA20 > EMA50
        if close > float(last["ema20"]) > float(last["ema50"]):
            score += 2
            notes.append("ema_uptrend")
        else:
            return None  # hard gate

        # RSI pullback zone (40-55 for crypto)
        rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
        if 40 <= rsi <= 55:
            score += 2
            notes.append("rsi_pullback")
        elif 30 <= rsi < 40:
            score += 3
            notes.append("rsi_deeper_pullback")
        elif rsi > 70:
            return None  # overbought, no entry

        # MACD turning positive
        if not pd.isna(last.get("macd_hist")) and float(last["macd_hist"]) > 0:
            score += 1
            notes.append("macd_positive")

        # Volume confirmation
        if not pd.isna(last.get("vol_ratio")) and float(last["vol_ratio"]) >= 1.3:
            score += 1
            notes.append("volume_surge")

        # Healthy pullback from recent high
        pb = float(last.get("pullback_from_high", 0) or 0)
        if -20 <= pb <= -3:
            score += 1
            notes.append("healthy_pullback")

        # EMA20 slope positive
        if not pd.isna(last.get("ema20_slope")) and float(last["ema20_slope"]) > 0:
            score += 1
            notes.append("trend_slope_up")

        # Bollinger / OBV (from base indicators)
        if last.get("obv_trending_up"):
            score += 1
            notes.append("obv_accumulation")
        if last.get("rsi_bull_divergence"):
            score += 2
            notes.append("rsi_bull_divergence")

        # Exchange flow patterns
        if last.get("exflow_accumulation"):
            score += 1; notes.append("accumulation_pattern")
        if last.get("exflow_distribution"):
            score -= 1; notes.append("distribution_warning")

        if score < self.MIN_SCORE:
            return None

        regime = classify_regime(df)
        atr = float(last["atr14"])
        stop = round(close - self.STOP_ATR * atr, 4)
        tp   = round(close + self.TP_ATR  * atr, 4)

        return Signal(
            symbol=symbol, action="buy", score=score,
            last_close=close, atr=atr,
            stop_price=stop, take_profit_price=tp,
            notes=notes, regime=regime, direction="long",
        )

    def evaluate_breakout(self, symbol: str, df: pd.DataFrame):
        """Breakout momentum: price clears 20-day high + volume surge + RSI in momentum zone."""
        from .strategy import Signal
        if df is None or len(df) < self.MIN_BARS:
            return None
        df = compute_crypto_indicators(df)
        last = df.iloc[-1]

        if pd.isna(last.get("atr14")):
            return None

        score = 0
        notes = []
        close = float(last["close"])

        # Price at or breaking 20-day high (within 0.5%)
        high_20d = float(last.get("high_20d", close))
        if close >= high_20d * 0.995:
            score += 2
            notes.append("breakout_20d_high")
        else:
            return None  # hard gate

        # Volume surge 2x+
        vol_ratio = float(last.get("vol_ratio", 1) or 1)
        if vol_ratio >= 2.0:
            score += 2
            notes.append("vol_2x_surge")
        elif vol_ratio >= 1.5:
            score += 1
            notes.append("vol_above_avg")
        else:
            return None  # breakout without volume is fake

        # RSI in momentum zone (55-70, not overbought)
        rsi = float(last["rsi"]) if not pd.isna(last.get("rsi")) else 50
        if 55 <= rsi <= 70:
            score += 2
            notes.append("rsi_momentum_zone")
        elif rsi > 70:
            return None  # already extended

        # MACD positive
        if not pd.isna(last.get("macd_hist")) and float(last["macd_hist"]) > 0:
            score += 1
            notes.append("macd_positive")

        if score < 4:
            return None

        regime = classify_regime(df)
        atr = float(last["atr14"])
        # Breakout stop: below breakout candle low or 1.5x ATR
        stop = round(close - 1.5 * atr, 4)
        tp   = round(close + 3.5 * atr, 4)

        return Signal(
            symbol=symbol, action="buy", score=score,
            last_close=close, atr=atr,
            stop_price=stop, take_profit_price=tp,
            notes=notes, regime=regime, direction="long",
        )

    def evaluate_bounce(self, symbol: str, df: pd.DataFrame):
        """Extreme oversold snap-back. RSI < 30, tiny size, AI must approve."""
        from .strategy import Signal
        if df is None or len(df) < self.MIN_BARS:
            return None
        df = compute_crypto_indicators(df)
        last = df.iloc[-1]

        if pd.isna(last.get("rsi")) or pd.isna(last.get("atr14")):
            return None

        rsi = float(last["rsi"])
        if rsi >= 30:
            return None

        score = 0
        notes = []

        if rsi < 15:
            score += 4; notes.append("extreme_oversold")
        elif rsi < 20:
            score += 3; notes.append("deeply_oversold")
        else:
            score += 2; notes.append("oversold")

        if last.get("rsi_bull_divergence"):
            score += 2; notes.append("rsi_bull_divergence")
        if float(last.get("vol_ratio", 1) or 1) >= 1.5:
            score += 1; notes.append("vol_spike")
        if last.get("near_fib_support"):
            score += 1; notes.append("fib_support")
        if last.get("exflow_capitulation"):
            score += 2; notes.append("vol_capitulation")

        if score < 4:
            return None

        close = float(last["close"])
        atr   = float(last["atr14"])
        stop  = round(close - 1.0 * atr, 4)
        tp    = round(close + 2.0 * atr, 4)

        return Signal(
            symbol=symbol, action="bounce", score=score,
            last_close=close, atr=atr,
            stop_price=stop, take_profit_price=tp,
            notes=notes, regime="bounce", direction="bounce",
        )

    def should_exit(self, df: pd.DataFrame, side: str = "long"):
        """Exit using EMA-based gates (EMA20 for fast exit, EMA50 as confirmation)."""
        if df is None or len(df) < self.MIN_BARS:
            return False, ""
        df = compute_crypto_indicators(df)
        last = df.iloc[-1]

        if pd.isna(last.get("ema20")) or pd.isna(last.get("rsi")):
            return False, ""

        close = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last.get("ema50", ema20))
        rsi   = float(last["rsi"])

        if side == "long":
            if close < ema20:
                return True, "close_below_ema20"
            if rsi > 75:
                return True, "rsi_overbought_75"
            if close < ema50 * 0.99:
                return True, "trend_broken_below_ema50"
        elif side == "bounce":
            if rsi > 50:
                return True, "rsi_recovered_bounce"
            if close > ema20:
                return True, "price_above_ema20"
            if rsi < 10:
                return True, "bounce_failed"

        return False, ""

log = logging.getLogger(__name__)

# Symbols considered "majors" — tradeable during Bitcoin Season
_BTC_MAJORS = {"BTC/USD", "ETH/USD", "BTCUSD", "ETHUSD"}


def _price_decimals(price: float) -> int:
    """Return decimal places needed for meaningful price increments at this price level."""
    if price >= 1000:  return 2   # BTC, ETH  ($94,000 → 2 dp fine)
    if price >= 10:    return 3   # SOL, AVAX, LINK  ($130 → 3 dp fine)
    if price >= 0.1:   return 5   # DOGE, XRP, ADA, MATIC ($0.17 → needs 5 dp)
    if price >= 0.001: return 7   # mid-small alts
    return 8                       # micro-price alts


def _place_crypto_bracket(broker_client, symbol: str, qty: float, price: float, stop: float, tp: float):
    """Place a bracket buy order for crypto using GTC (24/7 markets)."""
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    alpaca_sym = symbol.replace("/", "")  # "BTC/USD" -> "BTCUSD"
    prec        = _price_decimals(price)
    limit_price = round(price * 1.001, prec)
    safe_stop   = round(min(stop,  limit_price * 0.999), prec)
    safe_tp     = round(max(tp,    limit_price * 1.001), prec)
    if limit_price <= 0 or safe_stop <= 0 or safe_tp <= limit_price:
        raise ValueError(
            f"Invalid prices after rounding (prec={prec}): "
            f"limit={limit_price} stop={safe_stop} tp={safe_tp}"
        )
    log.info(
        f"  ORDER {alpaca_sym}: qty={qty:.6f} limit={limit_price} "
        f"stop={safe_stop} tp={safe_tp} (prec={prec})"
    )
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
        self.strategy = CryptoStrategy()
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

        halving = mkt.get("halving", {})
        stable  = mkt.get("stablecoin_ratio", {})
        macro   = mkt.get("macro_cycle", {})
        log.info(
            f"  Market context — F&G: {fg.get('value','?')} ({fg.get('label','?')}) | "
            f"BTC Dom: {dom.get('pct','?'):.1f}% | "
            f"BTC 1H: {btc_chg:+.2f}% | News: {news.get('bullish_count',0)}↑/{news.get('bearish_count',0)}↓ | "
            f"Macro: {macro.get('phase','?')} | Halving: {halving.get('label','?')} | "
            f"Stables: {stable.get('ratio','?')}% | On-chain score: {on_chain_score:+.2f}"
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

        # Build crypto key set once — used throughout exit pass and order cleanup
        _crypto_keys = {s.replace("/", "") for s in CRYPTO_SYMBOLS}

        # ── STALE ORDER CLEANUP — cancel unfilled crypto BUY orders > 4 hours old ──
        # GTC orders sit forever if price moves away. Cancel and re-evaluate each run
        # so entries are always based on current market price.
        try:
            _now = datetime.now(timezone.utc)
            for _order in broker.get_open_orders():
                _sym = getattr(_order, "symbol", "")
                _side = str(getattr(getattr(_order, "side", None), "value", "")).lower()
                if _sym not in _crypto_keys and "/" not in _sym:
                    continue  # not crypto
                if _side != "buy":
                    continue  # leave stop/TP legs alone
                _created = getattr(_order, "created_at", None)
                if _created:
                    try:
                        if hasattr(_created, "tzinfo") and _created.tzinfo:
                            _age_h = (_now - _created).total_seconds() / 3600
                        else:
                            _age_h = 999  # unknown age → cancel
                        if _age_h > 4:
                            broker.client.cancel_order_by_id(_order.id)
                            log.info(f"  Cancelled stale order {_sym} (age {_age_h:.1f}h)")
                    except Exception as _ce:
                        log.debug(f"  Could not cancel stale order {_sym}: {_ce}")
        except Exception as _oe:
            log.debug(f"  Stale order cleanup error: {_oe}")

        # ── EXIT PASS — close all positions that hit exit conditions ──────────
        # Non-crypto (equity/ETF) positions are ALWAYS force-closed immediately —
        # this system is crypto-only, no equity should be held.
        # Crypto positions use CryptoStrategy (EMA-based, 60-bar min).
        try:
            all_positions = {p.symbol: p for p in broker.get_positions()}
        except Exception:
            all_positions = {}

        for sym_key, pos in list(all_positions.items()):
            side_val = getattr(pos.side, "value", str(pos.side)).lower()
            side = "long" if "long" in side_val else "short"

            if sym_key not in _crypto_keys:
                # Force-close all equity/ETF positions — crypto-only mode
                log.info(f"  FORCE EXIT equity {sym_key} [{side}]: crypto-only mode")
                if not self.dry_run:
                    try:
                        broker.close_position(sym_key)
                    except Exception as exc:
                        log.error(f"  Force exit failed {sym_key}: {exc}")
                continue

            crypto_sym = next((s for s in CRYPTO_SYMBOLS if s.replace("/", "") == sym_key), None)
            bars = self.fetcher.get_daily_bars(crypto_sym) if crypto_sym else None

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
        max_crypto = self.config.max_positions  # crypto-only — use all position slots

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

            bounce_sig   = self.strategy.evaluate_bounce(symbol, bars)
            long_sig     = self.strategy.evaluate(symbol, bars)
            breakout_sig = self.strategy.evaluate_breakout(symbol, bars)
            sigs = [s for s in [long_sig, breakout_sig, bounce_sig] if s is not None]
            if sigs:
                best = max(sigs, key=lambda s: s.score)
                # Apply on-chain composite boost THEN re-gate on minimum score
                best.score = round(best.score + on_chain_score)
                if best.score < self.strategy.MIN_SCORE:
                    log.info(
                        f"  {symbol}: post-boost score {best.score} < min {self.strategy.MIN_SCORE} "
                        f"(on-chain={on_chain_score:+.1f}) — skip"
                    )
                    continue
                candidates.append(best)
                log.info(
                    f"  {symbol}: best={best.direction} score={best.score} "
                    f"(trend={long_sig.score if long_sig else '-'} "
                    f"breakout={breakout_sig.score if breakout_sig else '-'} "
                    f"bounce={bounce_sig.score if bounce_sig else '-'} "
                    f"on-chain={on_chain_score:+.1f})"
                )
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
            indic = compute_crypto_indicators(bars) if bars is not None else {}
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
                sma50=float(last_row.get("ema50", last_row.get("sma50", price)) or price),
                sma200=float(last_row.get("ema200", last_row.get("sma200", price)) or price),
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
