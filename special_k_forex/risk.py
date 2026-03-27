import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PositionPlan:
    qty: int
    max_notional: float
    risk_dollars: float
    risk_reward_ratio: float = 0.0


class RiskManager:
    def __init__(self, config):
        self.config = config
        self._daily_start_equity: Optional[float] = None

    def set_start_equity(self, equity: float):
        if self._daily_start_equity is None:
            self._daily_start_equity = equity
            logger.info(f"Daily start equity set: ${equity:,.2f}")

    def kill_switch_triggered(self, current_equity: float) -> bool:
        if self._daily_start_equity is None:
            return False
        drawdown = (self._daily_start_equity - current_equity) / self._daily_start_equity * 100
        if drawdown >= self.config.daily_kill_switch_pct:
            logger.warning(f"KILL SWITCH: drawdown {drawdown:.2f}% >= {self.config.daily_kill_switch_pct}%")
            return True
        return False

    def max_exposure_reached(self, portfolio_value: float, open_position_value: float) -> bool:
        pct = (open_position_value / portfolio_value * 100) if portfolio_value > 0 else 0
        if pct >= self.config.max_portfolio_exposure_pct:
            logger.info(f"Max exposure reached: {pct:.1f}% >= {self.config.max_portfolio_exposure_pct}%")
            return True
        return False

    def buying_power_too_low(self, buying_power: float) -> bool:
        """
        Returns True when available buying power is below the configured minimum.
        When this fires, the engine skips new entries and waits for open positions
        to close and return cash before trading again.
        """
        if buying_power < self.config.min_buying_power:
            logger.info(
                f"Buying power ${buying_power:,.2f} < min ${self.config.min_buying_power:,.2f} "
                f"— pausing new entries until capital recovers."
            )
            return True
        return False

    def shares_for_trade(
        self,
        price: float,
        atr: float,
        portfolio_value: float,
        stop_price: float,
        take_profit_price: Optional[float] = None,
    ) -> PositionPlan:
        risk_dollars   = portfolio_value * (self.config.risk_per_trade_pct / 100)
        risk_per_share = price - stop_price
        if risk_per_share <= 0:
            return PositionPlan(qty=0, max_notional=0, risk_dollars=0)

        qty = int(risk_dollars / risk_per_share)
        max_notional_by_pct = portfolio_value * (self.config.max_position_pct / 100)
        max_qty_by_notional  = int(max_notional_by_pct / price) if price > 0 else 0
        qty = min(qty, max_qty_by_notional)

        rr = 0.0
        if take_profit_price and qty > 0:
            reward = (take_profit_price - price) * qty
            risk   = risk_per_share * qty
            rr = round(reward / risk, 2) if risk > 0 else 0.0
            logger.info(f"R:R ratio = {rr:.2f} (reward ${reward:.2f} / risk ${risk:.2f})")

        return PositionPlan(
            qty=qty,
            max_notional=qty * price,
            risk_dollars=risk_dollars,
            risk_reward_ratio=rr,
        )
