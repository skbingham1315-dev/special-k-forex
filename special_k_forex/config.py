from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)).strip())


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)).strip())


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


# Default forex ETF watchlist:
#   FXE  = Euro (EUR/USD proxy)
#   FXB  = British Pound (GBP/USD proxy)
#   FXY  = Japanese Yen (USD/JPY inverse proxy)
#   FXC  = Canadian Dollar (USD/CAD inverse proxy)
#   FXA  = Australian Dollar (AUD/USD proxy)
#   UUP  = US Dollar Index bullish
_DEFAULT_SYMBOLS = ["FXE", "FXB", "FXY", "FXC", "FXA", "UUP"]


@dataclass(slots=True)
class Settings:
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "").strip()
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "").strip()
    alpaca_paper: bool = _env_bool("ALPACA_PAPER", True)

    symbols: List[str] = field(default_factory=lambda: _env_list("SYMBOLS", _DEFAULT_SYMBOLS))

    max_positions: int = _env_int("MAX_POSITIONS", 3)
    max_portfolio_exposure_pct: float = _env_float("MAX_PORTFOLIO_EXPOSURE_PCT", 60.0)
    max_position_pct: float = _env_float("MAX_POSITION_PCT", 20.0)
    risk_per_trade_pct: float = _env_float("RISK_PER_TRADE_PCT", 1.0)
    daily_kill_switch_pct: float = _env_float("DAILY_KILL_SWITCH_PCT", 3.0)

    # Minimum buying power before pausing new entries.
    # When cash drops below this, no new trades are opened until
    # existing positions close and buying power recovers.
    min_buying_power: float = _env_float("MIN_BUYING_POWER", 500.0)

    stop_atr_multiplier: float = _env_float("STOP_ATR_MULTIPLIER", 1.2)
    take_profit_atr_multiplier: float = _env_float("TAKE_PROFIT_ATR_MULTIPLIER", 2.5)

    # Forex ETFs are much less volatile than equities — lower volume floor
    min_avg_dollar_volume: float = _env_float("MIN_AVG_DOLLAR_VOLUME", 5_000_000)

    rsi_period: int = 14
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    sma_fast_period: int = 50
    sma_slow_period: int = 200
    atr_period: int = 14

    lookback_days: int = 400
    min_signal_score: int = 4
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper().strip()

    def validate(self) -> None:
        if not self.alpaca_api_key or not self.alpaca_secret_key:
            raise ValueError("Missing Alpaca API keys. Add them to .env first.")
        if self.max_positions < 1:
            raise ValueError("MAX_POSITIONS must be at least 1.")
        if self.max_position_pct <= 0 or self.max_position_pct > 100:
            raise ValueError("MAX_POSITION_PCT must be between 0 and 100.")
        if self.risk_per_trade_pct <= 0:
            raise ValueError("RISK_PER_TRADE_PCT must be greater than 0.")
        if self.stop_atr_multiplier <= 0 or self.take_profit_atr_multiplier <= 0:
            raise ValueError("ATR multipliers must be greater than 0.")
        if self.min_buying_power < 0:
            raise ValueError("MIN_BUYING_POWER must be >= 0.")


settings = Settings()
