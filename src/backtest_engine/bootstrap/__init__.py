"""Composition root for the rewrite."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backtest_engine.bootstrap.composition_root import (
        ApplicationContainer,
        BacktestDryRunCommand,
        BacktestDryRunResult,
        InfrastructurePorts,
        build_application_container,
        build_calibration_dataset_materializer,
        build_cli_container,
        build_default_infrastructure_ports,
        build_http_container,
        build_ib_historical_ingestor,
        build_infrastructure_ports,
    )
    from backtest_engine.bootstrap._market_data_runtime import build_market_data_service


_EXPORTS: dict[str, tuple[str, str]] = {
    "ApplicationContainer": ("backtest_engine.bootstrap.composition_root", "ApplicationContainer"),
    "BacktestDryRunCommand": (
        "backtest_engine.bootstrap.composition_root",
        "BacktestDryRunCommand",
    ),
    "BacktestDryRunResult": (
        "backtest_engine.bootstrap.composition_root",
        "BacktestDryRunResult",
    ),
    "InfrastructurePorts": ("backtest_engine.bootstrap.composition_root", "InfrastructurePorts"),
    "build_application_container": (
        "backtest_engine.bootstrap.composition_root",
        "build_application_container",
    ),
    "build_calibration_dataset_materializer": (
        "backtest_engine.bootstrap.composition_root",
        "build_calibration_dataset_materializer",
    ),
    "build_default_infrastructure_ports": (
        "backtest_engine.bootstrap.composition_root",
        "build_default_infrastructure_ports",
    ),
    "build_cli_container": ("backtest_engine.bootstrap.composition_root", "build_cli_container"),
    "build_http_container": ("backtest_engine.bootstrap.composition_root", "build_http_container"),
    "build_ib_historical_ingestor": (
        "backtest_engine.bootstrap.composition_root",
        "build_ib_historical_ingestor",
    ),
    "build_infrastructure_ports": (
        "backtest_engine.bootstrap.composition_root",
        "build_infrastructure_ports",
    ),
    "build_market_data_service": (
        "backtest_engine.bootstrap._market_data_runtime",
        "build_market_data_service",
    ),
}

__all__ = [
    "ApplicationContainer",
    "BacktestDryRunCommand",
    "BacktestDryRunResult",
    "InfrastructurePorts",
    "build_application_container",
    "build_calibration_dataset_materializer",
    "build_cli_container",
    "build_default_infrastructure_ports",
    "build_http_container",
    "build_ib_historical_ingestor",
    "build_market_data_service",
    "build_infrastructure_ports",
]


def __getattr__(name: str) -> Any:
    try:
        module_path, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_path)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
