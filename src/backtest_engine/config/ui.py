"""UI delivery settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UiSettings(BaseModel):
    """Terminal UI settings kept at the edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535, default=8000)


__all__ = ["UiSettings"]
