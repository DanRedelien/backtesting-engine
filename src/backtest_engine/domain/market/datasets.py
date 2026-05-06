"""Dataset identity contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, computed_field

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.ids import build_dataset_id, stable_hash
from backtest_engine.core.types import ContentHash, NonEmptyStr, Symbol, Timeframe


class DatasetSpec(BaseModel):
    """A canonical dataset identity for caching, replay, and manifests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: DatasetSource
    normalization_policy: NonEmptyStr
    schema_version: NonEmptyStr
    symbol_universe: tuple[Symbol, ...]
    timeframe: Timeframe
    dataset_version: NonEmptyStr

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> ContentHash:
        payload = self.model_dump(mode="json", exclude={"content_hash", "dataset_id"})
        return stable_hash(payload)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dataset_id(self) -> str:
        return build_dataset_id(self.content_hash)


__all__ = ["DatasetSpec"]
