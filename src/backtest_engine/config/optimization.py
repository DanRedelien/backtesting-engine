"""Optimization settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import NonEmptyStr


class OptimizationSettings(BaseModel):
    """Defaults for batch and walk-forward orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_folds: int = Field(ge=1, default=5)
    max_parallel_trials: int = Field(ge=1, default=1)
    objective_metric: NonEmptyStr = "net_profit"


__all__ = ["OptimizationSettings"]
