"""Artifact provenance contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr


class ProvenanceRecord(BaseModel):
    """Normalized provenance for one persisted result bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    run_spec_hash: NonEmptyStr
    dataset_id: NonEmptyStr
    created_at_utc: datetime

    @field_validator("created_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


__all__ = ["ProvenanceRecord"]
