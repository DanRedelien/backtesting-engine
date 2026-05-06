"""Root settings assembly for the rewrite."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from backtest_engine.config.data import DataSettings
from backtest_engine.config.optimization import OptimizationSettings
from backtest_engine.config.portfolio import PortfolioSettings
from backtest_engine.config.runtime import RuntimeSettings
from backtest_engine.config.ui import UiSettings


class PlatformSettings(BaseSettings):
    """Immutable platform settings loaded once at the edge."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_prefix="BTE_",
        extra="ignore",
        frozen=True,
    )

    runtime: RuntimeSettings = RuntimeSettings()
    data: DataSettings = DataSettings()
    portfolio: PortfolioSettings = PortfolioSettings()
    optimization: OptimizationSettings = OptimizationSettings()
    ui: UiSettings = UiSettings()


def load_settings() -> PlatformSettings:
    """Load platform settings from environment variables once."""

    return PlatformSettings()


__all__ = ["PlatformSettings", "load_settings"]
