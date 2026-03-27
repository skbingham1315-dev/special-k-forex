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
    """Quick regime check without full indicator recompute."""
    if bars is None or len(bars) < 60:
        return "normal"
    return classify_regime(compute_indicators(bars))

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

        # --- account snapshot ---
        account      = self.broker.get_account()
        equity       = float(account.equity)
        cash         = float(account.cash)
        buying_power = float(account.buying_power)
        self.risk.set_start_equity(equity)
        logger.info(
            f"Account: equity=${equity:,.2f}  cash=${cash:,.2f}  buying_power=${buying_power:,.2f}"
        )

        # --- kill switch ---
        if self.risk.kill_switch_triggered(equity):
            logger.warning("Kill switch active — no new trades today.")
            return

        # --- existing positions: run exit pass ---
        positions = {p.symbol: p for p in self.broker.get_positions()}
        open_value = sum(float(p.market_value) for p in positions.values())

        for symbol, pos in list(positions.items()):
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue
            bars = compute_indicators(bars)
            should_exit, exit_reason = self.strategy.should_exit(bars)
            if should_exit:
                logger.info(f"EXIT {symbol}: {exit_reason}")
                if not self.dry_run:
                    self.broker.close_position(symbol)

        # --- entry pass ---
        # Re-fetch positions and buying power after potential exits
        positions    = {p.symbol: p for p in self.broker.get_positions()}
        open_value   = sum(float(p.market_value) for p in positions.values())
        buying_power = self.broker.get_buying_power()

        if self.risk.max_exposure_reached(equity, open_value):
            logger.info("Max portfolio exposure reached — skipping entry pass.")
            return

        if self.risk.buying_power_too_low(buying_power):
            logger.info("Waiting for buying power to recover before opening new trades.")
            return

        active_positions = len(positions)
        # In slow markets allow more simultaneous small positions
        max_pos = self.config.max_positions * 2 if all(
            _regime_from_bars(self.fetcher.get_daily_bars(s)) == "slow"
            for s in list(self.config.symbols)[:3]
        ) else self.config.max_positions
        if active_positions >= max_pos:
            logger.info(f"Max positions ({max_pos}) reached — no new entries.")
            return

        candidates = []
        for symbol in self.config.symbols:
            if symbol in positions:
                continue
            bars = self.fetcher.get_daily_bars(symbol)
            if bars is None or len(bars) < 60:
                continue
            bars = compute_indicators(bars)
            signal = self.strategy.evaluate(symbol, bars)
            logger.info(
                f"  {symbol}: bars={len(bars)} score={signal.score if signal else 'no_signal'}"
            )
            if signal:
                candidates.append(signal)

        # Sort by score descending — take the best setups first
        candidates.sort(key=lambda s: s.score, reverse=True)

        for signal in candidates:
            if active_positions >= self.config.max_positions:
                break
            if self.risk.buying_power_too_low(buying_power):
                logger.info("Buying power too low mid-pass — stopping entries.")
                break

            symbol = signal.symbol
            price  = signal.last_close
            atr    = signal.atr
            stop   = signal.stop_price
            tp     = signal.take_profit_price

            # Regime-adaptive sizing
            if signal.regime == "slow":
                # Small bets in quiet market — keep cash flowing
                risk_pct    = 0.25
                max_pos_pct = 5.0
                logger.info(f"  {symbol}: SLOW regime — micro sizing (risk=0.25%, max_pos=5%)")
            elif signal.regime == "active":
                # Strong trend — size up within reason
                risk_pct    = min(self.config.risk_per_trade_pct * 1.5, 2.0)
                max_pos_pct = self.config.max_position_pct
                logger.info(f"  {symbol}: ACTIVE regime — full sizing (risk={risk_pct:.2f}%)")
            else:
                risk_pct    = self.config.risk_per_trade_pct
                max_pos_pct = self.config.max_position_pct

            # ── Political tracker ──────────────────────────────────────────
            pol = get_political_signal(symbol)
            if pol["score_delta"] > 0:
                logger.info(f"  {symbol}: political BOOST +1 — {pol['summary']}")
            elif pol["score_delta"] < 0:
                logger.info(f"  {symbol}: political WARNING -1 — {pol['summary']}")

            # ── AI analyst validation ───────────────────────────────────────
            last_df = compute_indicators(self.fetcher.get_daily_bars(symbol) or bars)
            last_row = last_df.iloc[-1]
            ai = analyse_signal(
                symbol=symbol,
                pair=getattr(self.config, "forex_pairs", {}).get(symbol, symbol),
                regime=signal.regime,
                score=signal.score + pol["score_delta"],
                rsi=float(last_row.get("rsi", 50)),
                adx=float(last_row.get("adx", 20)),
                atr=atr,
                price=price,
                sma50=float(last_row.get("sma50", price)),
                sma200=float(last_row.get("sma200", price)),
                macd_hist=float(last_row.get("macd_hist", 0)),
                pullback_10d_pct=float(last_row.get("pullback_10d_pct", 0)),
                notes=signal.notes,
                political_activity=pol["summary"] if (pol["buys"] or pol["sells"]) else None,
            )

            logger.info(f"  {symbol}: AI confidence={ai['confidence']} action={ai['action']} — {ai['reason']}")

            # Skip trade if AI says no or confidence too low
            if ai["action"] == "skip" or ai["confidence"] < 5:
                logger.info(f"  {symbol}: AI rejected signal — skipping.")
                continue

            # Reduce size if AI is cautious
            if ai["action"] == "reduce" or ai["confidence"] < 7:
                risk_pct    = risk_pct * 0.5
                max_pos_pct = max_pos_pct * 0.5
                logger.info(f"  {symbol}: AI reduce — halving position size.")

            # Size up slightly on high confidence active regime
            if ai["confidence"] >= 8 and signal.regime == "active":
                risk_pct = min(risk_pct * 1.25, 2.0)
                logger.info(f"  {symbol}: AI high confidence boost — risk_pct={risk_pct:.2f}%")

            plan = self.risk.shares_for_trade(
                price, atr, equity, stop, tp,
                risk_pct_override=risk_pct,
                max_pos_pct_override=max_pos_pct,
            )

            if plan.qty <= 0:
                logger.info(f"  {symbol}: qty=0 after sizing — skipping.")
                continue

            logger.info(
                f"  ENTRY {symbol}: qty={plan.qty} price=${price:.4f} "
                f"stop=${stop:.4f} tp=${tp:.4f} score={signal.score} "
                f"ai_confidence={ai['confidence']} notes={signal.notes} R:R={plan.risk_reward_ratio}"
            )
            if not self.dry_run:
                try:
                    self.broker.place_bracket_buy(symbol, plan.qty, price, stop, tp)
                    # Deduct estimated cost from buying power so we don't over-allocate
                    buying_power -= plan.max_notional
                    active_positions += 1
                except Exception as exc:
                    logger.error(f"  Order failed for {symbol}: {exc}")
            else:
                active_positions += 1
