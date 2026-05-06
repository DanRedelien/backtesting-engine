"""Output rendering helpers for the runnable backtest CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from backtest_engine.core.errors import BacktestEngineError

if TYPE_CHECKING:
    from backtest_engine.application.backtests.dry_run_backtest import BacktestDryRunResult
    from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
    from backtest_engine.application.single.run_single_backtest import SingleRunResult


def print_single_success(result: "SingleRunResult") -> None:
    """Render a successful single backtest."""

    print(format_single_success(result))


def print_portfolio_success(result: "PortfolioRunResult") -> None:
    """Render a successful portfolio backtest."""

    print(format_portfolio_success(result))


def print_dry_run_success(result: "BacktestDryRunResult") -> None:
    """Render a successful backtest dry-run."""

    print(format_dry_run_success(result))


def format_single_success(result: "SingleRunResult") -> str:
    """Format a successful single backtest as stable key-value text."""

    return "\n".join(
        [
            "OK single",
            f"run_id: {result.run_id}",
            f"bundle_id: {result.bundle_id}",
            f"bundle_uri: {result.bundle_uri}",
            f"runtime_root: {result.runtime_root}",
            *_format_metrics(result.metric_values),
        ]
    )


def format_portfolio_success(result: "PortfolioRunResult") -> str:
    """Format a successful portfolio backtest as stable key-value text."""

    return "\n".join(
        [
            "OK portfolio",
            f"run_id: {result.run_id}",
            f"bundle_id: {result.bundle_id}",
            f"bundle_uri: {result.bundle_uri}",
            f"runtime_root: {result.runtime_root}",
            f"allocation_count: {result.allocation_count}",
            f"position_count: {result.position_count}",
            *_format_metrics(result.metric_values),
        ]
    )


def format_dry_run_success(result: "BacktestDryRunResult") -> str:
    """Format a successful dry-run as stable key-value text."""

    return "\n".join(
        [
            "OK dry-run",
            f"run_id: {result.run_id}",
            f"run_kind: {result.run_kind.value}",
            f"dataset_id: {result.dataset_id}",
            f"runtime_root: {result.runtime_root}",
            f"artifact_root: {result.artifact_root}",
            f"catalog_root: {result.catalog_root}",
            f"data_count: {result.data_count}",
            *_format_sequence("venue_names", result.venue_names),
            *_format_sequence("instrument_ids", result.instrument_ids),
            *_format_sequence("bar_types", result.bar_types),
            *_format_sequence("strategy_ids", result.strategy_ids),
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
    lines.extend(_format_actionable_context(error.context))
    return "\n".join(lines)


def _format_metrics(metric_values: Mapping[str, float]) -> list[str]:
    lines = ["metrics:"]
    for metric_name in sorted(metric_values):
        lines.append(f"  {metric_name}: {metric_values[metric_name]}")
    return lines


def _format_sequence(label: str, values: tuple[str, ...]) -> list[str]:
    lines = [f"{label}:"]
    for value in values:
        lines.append(f"  {value}")
    return lines


def _format_actionable_context(context: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for key in (
        "execution_costs_path",
        "expected_config_content_hash",
        "actual_config_content_hash",
        "run_id",
    ):
        value = context.get(key)
        if value is not None:
            lines.append(f"{key}: {value}")

    snippet = context.get("run_profile_snippet")
    if isinstance(snippet, Mapping):
        lines.append("run_profile_snippet:")
        lines.extend(_format_mapping_block(snippet, indent=2))
    return lines


def _format_mapping_block(mapping: Mapping[object, object], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            lines.append(f"{prefix}{key}:")
            lines.extend(_format_mapping_block(value, indent=indent + 2))
        else:
            lines.append(f"{prefix}{key}: {value}")
    return lines


__all__ = [
    "format_cli_error",
    "format_dry_run_success",
    "format_portfolio_success",
    "format_single_success",
    "print_cli_error",
    "print_dry_run_success",
    "print_portfolio_success",
    "print_single_success",
]
