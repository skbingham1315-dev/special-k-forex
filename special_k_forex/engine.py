import logging
from datetime import datetime, timezone

from .broker import Broker
from .config import Settings as Config
from .data import MarketDataClient
from .indicators import compute_indicators, classify_regime
from .risk import RiskManager
from .strategy import ForexETFStrategy
from .ai_analyst import analyse_signal
from .political_tracker import get_political_signal
from .hedge import HedgeManager, HEDGE_INSTRUMENTS
from .legendary_trader_rules import score_trade_signal

try:
    from .trend_memory import get_symbol_memory
    _TREND_MEMORY_AVAILABLE = True
except ImportError:
    _TREND_MEMORY_AVAILABLE = False
    def get_symbol_memory(symbol):
        return {}


def _regime_from_bars(bars) -> str:
    if bars is None or len(bars) < 60:
        return "normal"
    return classify_regime(compute_indicators(bars))


def _position_side(pos) -> str:
    """Returns 'long' or 'short' based on Alpaca position."""
    try:
        qty = float(pos.qty)
        side = getattr(pos, "side", None)
        if side:
            # PositionSide enum: .value is "long"/"short"; str() gives "PositionSide.LONG"
            side_str = getattr(side, "value", str(side)).lower()
            return "long" if side_str == "long" else "short"
        return "long" if qty > 0 else "short"
    except Exception:
        return "long"


logger = logging.getLogger(__name__)


class ForexEngine:
    def __init__(self, config: Config, dry_run: bool = False):
        self.config   = config
        self.dry_run  = dry_run
        self.broker   = Broker()
        self.fetcher  = MarketDataClient()
        self.risk     = RiskManager(config)
        self.strategy = ForexETFStrategy()
        self.hedge    = HedgeManager(config)

    def run(self):
        logger.info(f"=== Special K Forex {'(DRY RUN)' if self.dry_run else '(LIVE)'} ==="
                    f" — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

        account      = self.broker.get_account()
        equity       = float(account.equity)
        cash         = float(account.cash)
        buying_power = float(account.buying_power)
        self.risk.set_start_equity(equity)
        logger.info(f"Account: equity=${equity:,.2f}  cash=${cash:,.2f}  buying_power=${buying_power:,.2f}")

        if self.risk.kill_switch_triggered(equity):
            logger.warning("Kill switch active — no new trades today.")
            return

        # ── EXIT PASS ──────────────────────────────────────────────────────────
        positions = {p.symbol: p for p in self.broker.get_positions()}

        # PDT guard: if account is near/at the 3 day-trade limit, identify which
        # positions were opened today so we can skip closing them (would be a day trade).
        pdt = self.broker.get_pdt_info()
        todays_opens: set = set()
        if pdt["near_limit"] and not self.dry_run:
            todays_opens = self.broker.get_todays_opened_symbols()
            logger.warning(
                f"PDT limit reached ({pdt['daytrade_count']}/3 day trades used) — "
                f"skipping same-day exits for: {todays_opens or 'none'}"
            )

        for symbol, pos in list(positions.items()):
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue
            side = _position_side(pos)
            should_exit, exit_reason = self.strategy.should_exit(
                bars, side=side
            )
            if should_exit:
                # Skip closing if position was opened today and we're at PDT limit
                if pdt["near_limit"] and symbol in todays_opens:
                    logger.info(f"  HOLD {symbol} [{side}]: exit condition met ({exit_reason}) but opened today — PDT protected, closing tomorrow.")
                    continue
                logger.info(f"EXIT {symbol} [{side}]: {exit_reason}")
                if not self.dry_run:
                    try:
                        self.broker.close_position(symbol)
                    except Exception as exc:
                        err = str(exc)
                        if "pattern day trading" in err.lower() or "40310100" in err:
                            logger.warning(f"  EXIT {symbol} blocked by PDT rule — will close tomorrow.")
                        else:
                            logger.error(f"  EXIT {symbol} failed: {exc}")

        # ── HEDGE PASS ─────────────────────────────────────────────────────────
        positions = {p.symbol: p for p in self.broker.get_positions()}
        if self.hedge.enabled:
            if self.hedge.needs_hedge(positions, equity):
                logger.info(
                    f"HEDGE TRIGGER: portfolio drawdown "
                    f"{self.hedge.portfolio_unrealized_pct(positions, equity):.2f}% "
                    f"< -{self.hedge.trigger_pct}% — opening hedges."
                )
                self.hedge.open_hedges(self.broker, self.fetcher, positions, self.dry_run)
            elif self.hedge.should_close_hedge(positions, equity):
                closed = self.hedge.close_hedges(self.broker, self.dry_run)
                if closed:
                    logger.info(f"HEDGE CLOSE: portfolio recovered — closed {closed}")

        # ── ENTRY PASS ─────────────────────────────────────────────────────────
        positions    = {p.symbol: p for p in self.broker.get_positions()}
        open_value   = sum(abs(float(p.market_value)) for p in positions.values())
        buying_power = self.broker.get_buying_power()

        if self.risk.max_exposure_reached(equity, open_value):
            logger.info("Max portfolio exposure reached — skipping entry pass.")
            return

        if self.risk.buying_power_too_low(buying_power):
            logger.info("Waiting for buying power to recover.")
            return

        # ── Budget cap ─────────────────────────────────────────────────────────
        budget = getattr(self.config, "trade_budget", 0.0)
        if budget > 0 and open_value >= budget:
            logger.info(f"Trade budget ${budget:,.2f} fully deployed (open=${open_value:,.2f}) — no new entries.")
            return
        budget_remaining = (budget - open_value) if budget > 0 else float("inf")
        logger.info(f"Budget: {'unlimited' if budget == 0 else f'${budget:,.2f}'} | deployed: ${open_value:,.2f} | remaining: {'unlimited' if budget == 0 else f'${budget_remaining:,.2f}'}")

        active_positions = len(positions)
        max_pos = self.config.max_positions

        if active_positions >= max_pos:
            logger.info(f"Max positions ({max_pos}) reached — no new entries.")
            return

        # Evaluate all three signal types for each symbol
        candidates = []
        for symbol in self.config.symbols:
            if symbol in positions:
                continue
            if symbol in HEDGE_INSTRUMENTS:
                continue  # managed by hedge pass only
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue

            # Try long → short → bounce, take best score
            long_sig   = self.strategy.evaluate(symbol, bars)
            short_sig  = self.strategy.evaluate_short(symbol, bars) if self.broker.shorting_enabled else None
            bounce_sig = self.strategy.evaluate_bounce(symbol, bars)

            # Collect all valid signals, sorted by score
            sigs = [s for s in [long_sig, short_sig, bounce_sig] if s is not None]
            if sigs:
                best = max(sigs, key=lambda s: s.score)
                candidates.append(best)
                logger.info(
                    f"  {symbol}: best={best.direction} score={best.score} "
                    f"(long={long_sig.score if long_sig else '-'} "
                    f"short={short_sig.score if short_sig else '-'} "
                    f"bounce={bounce_sig.score if bounce_sig else '-'})"
                )
            else:
                logger.info(f"  {symbol}: no signal")

        candidates.sort(key=lambda s: s.score, reverse=True)

        for signal in candidates:
            if active_positions >= max_pos:
                break
            if self.risk.buying_power_too_low(buying_power):
                logger.info("Buying power too low mid-pass — stopping entries.")
                break

            symbol = signal.symbol
            price  = signal.last_close
            atr    = signal.atr
            stop   = signal.stop_price
            tp     = signal.take_profit_price

            # ── Regime-adaptive sizing ──────────────────────────────────────
            if signal.direction == "bounce":
                # Counter-trend: very small — limit the risk
                risk_pct    = 0.15
                max_pos_pct = 3.0
                logger.info(f"  {symbol}: BOUNCE — micro sizing (risk=0.15%, max_pos=3%)")
            elif signal.regime == "slow":
                risk_pct    = 0.25
                max_pos_pct = 5.0
                logger.info(f"  {symbol}: SLOW regime — micro sizing (risk=0.25%, max_pos=5%)")
            elif signal.regime == "active":
                risk_pct    = min(self.config.risk_per_trade_pct * 1.5, 2.0)
                max_pos_pct = self.config.max_position_pct
                logger.info(f"  {symbol}: ACTIVE regime — full sizing (risk={risk_pct:.2f}%)")
            else:
                risk_pct    = self.config.risk_per_trade_pct
                max_pos_pct = self.config.max_position_pct

            # ── Political tracker ───────────────────────────────────────────
            pol = get_political_signal(symbol)
            if pol["score_delta"] > 0:
                logger.info(f"  {symbol}: political BOOST — {pol['summary']}")
            elif pol["score_delta"] < 0:
                logger.info(f"  {symbol}: political WARNING — {pol['summary']}")

            # ── AI validation ───────────────────────────────────────────────
            _fresh = self.fetcher.get_daily_bars(symbol)
            last_df  = compute_indicators(_fresh if (_fresh is not None and not _fresh.empty) else bars)
            last_row = last_df.iloc[-1]

            # Pull trend memory if available — gives Claude context beyond current bar
            sym_mem    = get_symbol_memory(symbol)
            trend_ctx  = None
            if sym_mem:
                trend_ctx = (
                    f"Trend memory: {sym_mem.get('trend_direction','?')} / "
                    f"{sym_mem.get('trend_strength','?')} | "
                    f"Pattern: {sym_mem.get('pattern_notes','')} | "
                    f"Watch for: {sym_mem.get('watch_for','')} | "
                    f"Macro: {sym_mem.get('macro_context','')}"
                )

            def _safe(val, default):
                v = last_row.get(val, default)
                return default if (v is None or (hasattr(v, '__float__') and __import__('math').isnan(float(v)))) else float(v)

            ai = analyse_signal(
                symbol=symbol,
                pair=getattr(self.config, "forex_pairs", {}).get(symbol, symbol),
                regime=signal.regime,
                score=signal.score + pol["score_delta"],
                rsi=_safe("rsi", 50),
                adx=_safe("adx", 20),
                atr=atr, price=price,
                sma50=_safe("sma50", price),
                sma200=_safe("sma200", price),
                macd_hist=_safe("macd_hist", 0),
                pullback_10d_pct=_safe("pullback_10d_pct", 0),
                notes=signal.notes,
                political_activity=pol["summary"] if (pol["buys"] or pol["sells"]) else None,
                trend_memory=trend_ctx,
                direction=signal.direction,
            )

            logger.info(f"  {symbol}: AI conf={ai['confidence']} action={ai['action']} [{signal.direction}] — {ai['reason']}")

            # Hard skip on low confidence — raised from ≤3 to ≤4 for tighter quality control
            if ai["confidence"] <= 4:
                logger.info(f"  {symbol}: AI hard reject (conf≤4) — skipping.")
                continue

            if ai["action"] == "skip" or ai["confidence"] <= 5:
                risk_pct    *= 0.25
                max_pos_pct *= 0.25
                logger.info(f"  {symbol}: AI low conf — quarter size.")
            elif ai["action"] == "reduce" or ai["confidence"] <= 6:
                risk_pct    *= 0.5
                max_pos_pct *= 0.5
                logger.info(f"  {symbol}: AI reduce — halving size.")

            if ai["confidence"] >= 8 and signal.regime == "active":
                risk_pct = min(risk_pct * 1.25, 2.0)

            plan = self.risk.shares_for_trade(
                price, atr, equity, stop, tp,
                risk_pct_override=risk_pct,
                max_pos_pct_override=max_pos_pct,
            )

            # Clamp qty to budget_remaining (fractional-aware)
            if budget_remaining < float("inf") and plan.qty > 0:
                max_qty_by_budget = round(budget_remaining / price, 3)
                if max_qty_by_budget < 0.001:
                    logger.info(f"  {symbol}: budget exhausted (${budget_remaining:.2f} left at ${price:.4f}) — skipping.")
                    continue
                if plan.qty > max_qty_by_budget:
                    logger.info(f"  {symbol}: qty capped by budget {plan.qty}→{max_qty_by_budget}")
                    plan.qty = max_qty_by_budget
                    plan.max_notional = max_qty_by_budget * price

            if plan.qty < 0.001:
                logger.info(f"  {symbol}: qty too small after sizing — skipping.")
                continue

            # Minimum R:R gate — must achieve at least 2:1 reward to risk.
            # Wyckoff ideal is 3:1 but 2:1 allows tighter setups while still having edge.
            MIN_RR = 2.0
            if plan.risk_reward_ratio > 0 and plan.risk_reward_ratio < MIN_RR:
                logger.info(f"  {symbol}: R:R {plan.risk_reward_ratio:.2f} < {MIN_RR} minimum — skipping.")
                continue

            # ── Legendary Trader quality gate (long signals only) ────────────
            # Short/bounce signals skip the market-uptrend gate since they trade
            # in downtrends by design. Apply the full legendary filter to longs only.
            if signal.direction == "long":
                _b = self.fetcher.get_daily_bars(symbol)
                _bars = _b if (_b is not None and not _b.empty) else bars
                _prices    = _bars["close"].tolist()
                _volumes   = _bars["volume"].tolist()
                _sma150    = float(last_row.get("sma150", last_row.get("sma50", price)) or price)
                lt = score_trade_signal(
                    symbol=symbol,
                    price_series=_prices,
                    volume_series=_volumes,
                    sma_50=float(last_row.get("sma50", price) or price),
                    sma_150=_sma150,
                    sma_200=float(last_row.get("sma200", price) or price),
                    atr=atr,
                    entry_price=price,
                    stop_price=stop,
                    target_price=tp,
                )
                logger.info(
                    f"  {symbol}: LegendaryScore={lt['score']}/{lt['max_possible']} "
                    f"recommend={lt['recommend']} | {lt['breakdown']}"
                )
                if lt["score"] < 5:
                    logger.info(f"  {symbol}: LegendaryTrader veto (score={lt['score']}<5) — skipping long.")
                    continue

            logger.info(
                f"  ENTRY [{signal.direction.upper()}] {symbol}: qty={plan.qty} "
                f"price=${price:.4f} stop=${stop:.4f} tp=${tp:.4f} "
                f"score={signal.score} ai={ai['confidence']} R:R={plan.risk_reward_ratio}"
            )

            if not self.dry_run:
                try:
                    if signal.direction in ("long", "bounce"):
                        self.broker.place_bracket_buy(symbol, plan.qty, price, stop, tp)
                    else:
                        self.broker.place_bracket_short(symbol, plan.qty, price, stop, tp)
                    buying_power     -= plan.max_notional
                    budget_remaining -= plan.max_notional
                    active_positions += 1
                except Exception as exc:
                    err = str(exc)
                    if "pattern day trading" in err.lower() or "40310100" in err:
                        logger.warning(f"  {symbol}: blocked by PDT rule — skipping (max 3 day trades/5 days under $25K).")
                        break  # PDT hit — stop trying to enter more trades today
                    elif "not allowed to short" in err.lower() or "40310000" in err:
                        logger.warning(f"  {symbol}: account does not support shorting — skipping short.")
                    else:
                        logger.error(f"  Order failed for {symbol}: {exc}")
            else:
                active_positions += 1
