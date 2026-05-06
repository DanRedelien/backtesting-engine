"""Pure strategy-policy protocols."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.domain.strategy.intent import SignalIntent


class StrategyContext(BaseModel):
    """Normalized inputs available to pure strategy policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_utc: datetime
    latest_prices: dict[str, float] = Field(default_factory=dict)
    open_position_sizes: dict[str, float] = Field(default_factory=dict)


class StrategyPolicy(Protocol):
    """A pure policy that maps normalized context to signal intents."""

    def evaluate(self, context: StrategyContext) -> tuple[SignalIntent, ...]:
        """Return one or more intents derived from normalized inputs."""
        ...


__all__ = ["StrategyContext", "StrategyPolicy"]
