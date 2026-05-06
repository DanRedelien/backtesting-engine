"""Fill-semantic policy contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.types import NonEmptyStr


class FillSemanticsSpec(BaseModel):
    """A named fill-semantics policy for reproducible execution behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_fill_rule: NonEmptyStr
    exit_fill_rule: NonEmptyStr
    same_bar_collision_policy: NonEmptyStr


__all__ = ["FillSemanticsSpec"]
