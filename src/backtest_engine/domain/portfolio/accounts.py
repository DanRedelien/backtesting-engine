"""Portfolio account snapshots."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.money import Money


class AccountSnapshot(BaseModel):
    """A normalized portfolio account snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    equity: Money
    cash: Money


__all__ = ["AccountSnapshot"]
