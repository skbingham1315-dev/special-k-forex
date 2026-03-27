import logging
from datetime import datetime, timezone

from .broker import Broker
from .config import Settings as Config
from .data import MarketDataClient
from .indicators import compute_indicators
from .risk import RiskManager
from .strategy import ForexETFStrategy

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
        if active_positions >= self.config.max_positions:
            logger.info(f"Max positions ({self.config.max_positions}) reached — no new entries.")
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
            plan   = self.risk.shares_for_trade(price, atr, equity, stop, tp)

            if plan.qty <= 0:
                logger.info(f"  {symbol}: qty=0 after sizing — skipping.")
                continue

            logger.info(
                f"  ENTRY {symbol}: qty={plan.qty} price=${price:.4f} "
                f"stop=${stop:.4f} tp=${tp:.4f} score={signal.score} "
                f"notes={signal.notes} R:R={plan.risk_reward_ratio}"
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
