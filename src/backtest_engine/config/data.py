"""Data, cache, IB, and MT5 ingestion settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import NonEmptyStr

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class IbDataSettings(BaseModel):
    """Typed connectivity and pacing settings for the IB ingestion path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: NonEmptyStr = "127.0.0.1"
    port: int = Field(default=7497, ge=1)
    client_id: int = Field(default=1, ge=0)
    timeout_sec: int = Field(default=30, ge=1)
    use_rth: bool = False
    max_historical_years: int = Field(default=2, ge=1)
    delayed_data_minutes: int = Field(default=15, ge=0)
    pacing_delay_sec: float = Field(default=11.0, gt=0.0)
    chunk_duration: NonEmptyStr = "1 W"


class Mt5DataSettings(BaseModel):
    """Typed settings for the MT5 historical ingestion path.

    ``broker_timezone_name`` has no default on purpose: the operator must
    set ``BTE_DATA__MT5__BROKER_TIMEZONE_NAME`` explicitly so that session
    semantics are never silently wrong.  Pass ``None`` (the default) to
    use MT5 settings without downloading data; the provider will reject
    the request with a clear error if it is still ``None`` at runtime.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    terminal_path: Path | None = None
    timeout_ms: int = Field(default=30_000, ge=1_000)
    broker_timezone_name: NonEmptyStr | None = None
    max_poll_attempts: int = Field(default=3, ge=1)
    poll_delay_sec: float = Field(default=2.0, gt=0.0)
    chunk_days: int = Field(default=30, ge=1)


class DataSettings(BaseModel):
    """Canonical settings for dataset storage and normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_cache_root: Path = Field(default_factory=lambda: _REPOSITORY_ROOT / "data" / "cache")
    data_root: Path = Field(default_factory=lambda: _REPOSITORY_ROOT / "var" / "data")
    cache_root: Path = Field(default_factory=lambda: _REPOSITORY_ROOT / "var" / "cache")
    normalization_policy: NonEmptyStr = "nautilus_v1"
    ib: IbDataSettings = IbDataSettings()
    mt5: Mt5DataSettings = Mt5DataSettings()


__all__ = ["DataSettings", "IbDataSettings", "Mt5DataSettings"]
