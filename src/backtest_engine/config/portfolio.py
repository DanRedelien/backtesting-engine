"""Portfolio settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import CurrencyCode, NonEmptyStr


class PortfolioSettings(BaseModel):
    """Defaults for portfolio-level orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_currency: CurrencyCode = "USD"
    default_rebalance_cadence: NonEmptyStr = "run_open"
    max_strategy_slots: int = Field(ge=1, default=32)


__all__ = ["PortfolioSettings"]
