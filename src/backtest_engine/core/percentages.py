"""Percentage value objects with explicit unit conversions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Percentage(BaseModel):
    """An immutable percentage value stored in percent units."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value_pct: float = Field(ge=-100_000.0, le=100_000.0)

    @property
    def value_frac(self) -> float:
        return self.value_pct / 100.0


__all__ = ["Percentage"]
