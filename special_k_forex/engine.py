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


def _regime_from_bars(bars) -> str:
    if bars is None or len(bars) < 60:
        return "normal"
    return classify_regime(compute_indicators(bars))


def _position_side(pos) -> str:
    """Returns 'long', 'short', or 'bounce' based on Alpaca position."""
    try:
        qty = float(pos.qty)
        side = getattr(pos, "side", None)
        if side:
            return "long" if str(side).lower() == "long" else "short"
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
        for symbol, pos in list(positions.items()):
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue
            side = _position_side(pos)
            should_exit, exit_reason = self.strategy.should_exit(
                compute_indicators(bars), side=side
            )
            if should_exit:
                logger.info(f"EXIT {symbol} [{side}]: {exit_reason}")
                if not self.dry_run:
                    self.broker.close_position(symbol)

        # ── ENTRY PASS ─────────────────────────────────────────────────────────
        positions    = {p.symbol: p for p in self.broker.get_positions()}
        open_value   = sum(float(p.market_value) for p in positions.values())
        buying_power = self.broker.get_buying_power()

        if self.risk.max_exposure_reached(equity, open_value):
            logger.info("Max portfolio exposure reached — skipping entry pass.")
            return

        if self.risk.buying_power_too_low(buying_power):
            logger.info("Waiting for buying power to recover.")
            return

        active_positions = len(positions)
        # In slow markets allow more concurrent small positions
        max_pos = self.config.max_positions * 2 if all(
            _regime_from_bars(self.fetcher.get_daily_bars(s)) == "slow"
            for s in list(self.config.symbols)[:3]
        ) else self.config.max_positions

        if active_positions >= max_pos:
            logger.info(f"Max positions ({max_pos}) reached — no new entries.")
            return

        # Evaluate all three signal types for each symbol
        candidates = []
        for symbol in self.config.symbols:
            if symbol in positions:
                continue
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue

            # Try long → short → bounce, take best score
            long_sig   = self.strategy.evaluate(symbol, bars)
            short_sig  = self.strategy.evaluate_short(symbol, bars)
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
            last_df  = compute_indicators(self.fetcher.get_daily_bars(symbol) or bars)
            last_row = last_df.iloc[-1]
            ai = analyse_signal(
                symbol=symbol,
                pair=getattr(self.config, "forex_pairs", {}).get(symbol, symbol),
                regime=signal.regime,
                score=signal.score + pol["score_delta"],
                rsi=float(last_row.get("rsi", 50) or 50),
                adx=float(last_row.get("adx", 20) or 20),
                atr=atr, price=price,
                sma50=float(last_row.get("sma50", price) or price),
                sma200=float(last_row.get("sma200", price) or price),
                macd_hist=float(last_row.get("macd_hist", 0) or 0),
                pullback_10d_pct=float(last_row.get("pullback_10d_pct", 0) or 0),
                notes=signal.notes,
                political_activity=pol["summary"] if (pol["buys"] or pol["sells"]) else None,
                direction=signal.direction,
            )

            logger.info(f"  {symbol}: AI conf={ai['confidence']} action={ai['action']} [{signal.direction}] — {ai['reason']}")

            # Bounce trades need higher AI confidence (counter-trend = riskier)
            min_conf = 7 if signal.direction == "bounce" else 5
            if ai["action"] == "skip" or ai["confidence"] < min_conf:
                logger.info(f"  {symbol}: AI rejected [{signal.direction}] — skipping.")
                continue

            if ai["action"] == "reduce" or ai["confidence"] < 7:
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

            if plan.qty <= 0:
                logger.info(f"  {symbol}: qty=0 after sizing — skipping.")
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
                    buying_power   -= plan.max_notional
                    active_positions += 1
                except Exception as exc:
                    logger.error(f"  Order failed for {symbol}: {exc}")
            else:
                active_positions += 1
