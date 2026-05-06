"""Portfolio limit contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import NonEmptyStr


class PortfolioLimit(BaseModel):
    """A named portfolio safety limit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    limit_name: NonEmptyStr
    threshold_value: float = Field(ge=0.0)


__all__ = ["PortfolioLimit"]
