"""Strategy-domain contracts."""

from backtest_engine.domain.strategy.intent import SignalIntent
from backtest_engine.domain.strategy.policy import StrategyContext, StrategyPolicy
from backtest_engine.domain.strategy.signal import StrategySignal
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)

__all__ = [
    "PortfolioStrategySpec",
    "SignalIntent",
    "StrategyContext",
    "StrategyLegSpec",
    "StrategyPolicy",
    "StrategySignal",
    "StrategySpec",
]
