"""Stable strategy specifications used by run contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from backtest_engine.core.ids import StrategyId, stable_hash
from backtest_engine.core.types import JsonValue, NonEmptyStr, Symbol


class StrategySpec(BaseModel):
    """A canonical strategy definition independent of runtime wrappers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    implementation_id: NonEmptyStr
    policy_version: NonEmptyStr
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        return stable_hash(payload)


class StrategyLegSpec(BaseModel):
    """One ordered instrument binding owned by a strategy slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol


class PortfolioStrategySpec(BaseModel):
    """A portfolio-level slot assignment for one strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: NonEmptyStr
    weight_frac: float = Field(ge=0.0, le=1.0)
    strategy: StrategySpec
    legs: tuple[StrategyLegSpec, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_legs(self) -> "PortfolioStrategySpec":
        if not self.legs:
            raise ValueError("PortfolioStrategySpec requires at least one leg")

        leg_symbols = tuple(leg.symbol for leg in self.legs)
        if len(set(leg_symbols)) != len(leg_symbols):
            raise ValueError("PortfolioStrategySpec legs must not repeat symbols")

        return self


__all__ = ["PortfolioStrategySpec", "StrategyLegSpec", "StrategySpec"]
