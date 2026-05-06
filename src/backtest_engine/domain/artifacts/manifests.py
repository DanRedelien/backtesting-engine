"""Artifact manifest contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backtest_engine.core.enums import RuntimeBoundary
from backtest_engine.core.money import Money
from backtest_engine.core.types import NonEmptyStr, Symbol


class ArtifactManifest(BaseModel):
    """A user-facing manifest that describes one persisted bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    run_spec_hash: NonEmptyStr
    runtime_boundary: RuntimeBoundary
    dataset_id: NonEmptyStr
    config_hash: NonEmptyStr = Field(
        description="Currently identical to run_spec_hash because BacktestRunSpec is the resolved config boundary.",
    )
    symbol_universe: tuple[Symbol, ...]
    strategy_ids: tuple[NonEmptyStr, ...]
    capital_base: Money
    semantic_policy_version: NonEmptyStr

    @model_validator(mode="after")
    def _validate_hash_invariant(self) -> "ArtifactManifest":
        if self.config_hash != self.run_spec_hash:
            raise ValueError(
                "config_hash must match run_spec_hash until configuration hashing is split from BacktestRunSpec",
            )
        return self


__all__ = ["ArtifactManifest"]
