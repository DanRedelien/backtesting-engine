"""Passive Nautilus wrapper used to validate the runtime boundary."""

from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy


class PassiveBarStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the passive-bar runtime smoke wrapper."""

    instrument_id: str
    bar_type: str
    strategy_id: str = ""


class PassiveBarStrategy(Strategy):
    """Subscribe to one bar stream without placing orders."""

    def __init__(self, config: PassiveBarStrategyConfig) -> None:
        _validate_strategy_id(config.strategy_id)
        super().__init__(config)

    def on_start(self) -> None:
        self.subscribe_bars(BarType.from_str(self.config.bar_type))

    def on_bar(self, bar: Bar) -> None:
        del bar
        return None


def _validate_strategy_id(strategy_id: str) -> None:
    if not strategy_id:
        raise ValueError("strategy_id must be provided")


__all__ = ["PassiveBarStrategy", "PassiveBarStrategyConfig"]
