"""Output rendering helpers for the runnable calibration CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import BacktestEngineError

if TYPE_CHECKING:
    from pathlib import Path

    from backtest_engine.application.calibration import SpreadCalibrationPublicationResult


def print_spread_success(
    result: "SpreadCalibrationPublicationResult",
    *,
    spec_path: "Path",
    run_kind: RunKind,
) -> None:
    """Render a successful spread calibration publication."""

    print(format_spread_success(result, spec_path=spec_path, run_kind=run_kind))


def format_spread_success(
    result: "SpreadCalibrationPublicationResult",
    *,
    spec_path: "Path",
    run_kind: RunKind,
) -> str:
    """Format a successful spread calibration as stable key-value text."""

    return "\n".join(
        [
            "OK spread-calibration",
            f"calibration_id: {result.calibration_id}",
            f"profile_id: {result.profile_id}",
            f"estimator_timeframe: {result.estimator_timeframe}",
            f"target_timeframe: {result.target_timeframe}",
            f"output_dir: {_format_path(result.output_dir)}",
            f"execution_costs_yaml: {_format_path(result.execution_costs_path)}",
            f"calibration_report_json: {_format_path(result.calibration_report_path)}",
            f"calibration_panel_parquet: {_format_path(result.calibration_panel_path)}",
            *_format_diagnostic_artifacts(result),
            f"execution_costs_config_hash: {result.execution_costs_config_hash}",
            "published_symbols:",
            *_format_symbols(result),
            "run_profile_snippet:",
            "  execution_policy:",
            "    execution_costs:",
            f"      profile_id: {result.profile_id}",
            f"      config_content_hash: {result.execution_costs_config_hash}",
            "backtest_handoff:",
            f"  python -m backtest_engine.interfaces.cli.backtest {run_kind.value} \\",
            f"    --spec {_format_path(spec_path)} \\",
            f"    --execution-costs-path {_format_path(result.execution_costs_path)}",
        ]
    )


def print_cli_error(error: BacktestEngineError) -> None:
    """Render a typed CLI error to stdout."""

    print(format_cli_error(error))


def format_cli_error(error: BacktestEngineError) -> str:
    """Format a typed CLI error for terminal display."""

    lines: list[str] = []
    usage = error.context.get("usage")
    if usage is not None:
        lines.append(str(usage))

    argparse_message = error.context.get("argparse_message")
    if argparse_message is None:
        lines.append(f"[{type(error).__name__}] {error.message}")
    else:
        lines.append(f"[{type(error).__name__}] {error.message}: {argparse_message}")
    return "\n".join(lines)


def _format_symbols(result: "SpreadCalibrationPublicationResult") -> list[str]:
    return [f"  {symbol.symbol}" for symbol in result.published_symbols]


def _format_diagnostic_artifacts(result: "SpreadCalibrationPublicationResult") -> list[str]:
    if not result.diagnostic_artifact_paths:
        return []
    return [
        "diagnostic_pngs:",
        *[f"  {_format_path(path)}" for path in result.diagnostic_artifact_paths],
    ]


def _format_path(path: "Path") -> str:
    return path.as_posix()


__all__ = [
    "format_cli_error",
    "format_spread_success",
    "print_cli_error",
    "print_spread_success",
]
