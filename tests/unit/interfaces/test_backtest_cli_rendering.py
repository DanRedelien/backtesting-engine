from __future__ import annotations

from backtest_engine.application.backtests.dry_run_backtest import BacktestDryRunResult
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.application.single.run_single_backtest import SingleRunResult
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.interfaces.cli.backtest.rendering import (
    format_cli_error,
    format_dry_run_success,
    format_portfolio_success,
    format_single_success,
)


def test_single_success_rendering_includes_required_fields_and_sorted_metrics() -> None:
    output = format_single_success(
        SingleRunResult(
            run_id="run-001",
            bundle_id="bundle-001",
            bundle_uri="results/bundle-001/bundle.json",
            runtime_root="var/runtime/nautilus/run-001",
            metric_values={"z_metric": 2.0, "a_metric": 1.0},
        )
    )

    assert output.splitlines() == [
        "OK single",
        "run_id: run-001",
        "bundle_id: bundle-001",
        "bundle_uri: results/bundle-001/bundle.json",
        "runtime_root: var/runtime/nautilus/run-001",
        "metrics:",
        "  a_metric: 1.0",
        "  z_metric: 2.0",
    ]


def test_portfolio_success_rendering_includes_counts_and_sorted_metrics() -> None:
    output = format_portfolio_success(
        PortfolioRunResult(
            run_id="run-portfolio",
            bundle_id="bundle-portfolio",
            bundle_uri="results/bundle-portfolio/bundle.json",
            runtime_root="var/runtime/nautilus/run-portfolio",
            allocation_count=3,
            position_count=5,
            metric_values={"z_metric": 2.0, "a_metric": 1.0},
        )
    )

    assert output.splitlines() == [
        "OK portfolio",
        "run_id: run-portfolio",
        "bundle_id: bundle-portfolio",
        "bundle_uri: results/bundle-portfolio/bundle.json",
        "runtime_root: var/runtime/nautilus/run-portfolio",
        "allocation_count: 3",
        "position_count: 5",
        "metrics:",
        "  a_metric: 1.0",
        "  z_metric: 2.0",
    ]


def test_cli_error_rendering_is_clean_human_text() -> None:
    output = format_cli_error(
        ApplicationError(
            "run-profile validation failed",
            usage="usage: bte-backtest single --spec SPEC",
            argparse_message="the following arguments are required: --spec",
        )
    )

    assert output.splitlines() == [
        "usage: bte-backtest single --spec SPEC",
        (
            "[ApplicationError] run-profile validation failed: "
            "the following arguments are required: --spec"
        ),
    ]


def test_dry_run_success_rendering_includes_required_fields_and_ordered_sequences() -> None:
    output = format_dry_run_success(
        BacktestDryRunResult(
            run_id="run-dry",
            run_kind=RunKind.PORTFOLIO,
            dataset_id="dataset-dry",
            runtime_root="var/runtime/nautilus/run-dry",
            artifact_root="var/runtime/nautilus/run-dry/artifacts",
            catalog_root="var/cache/nautilus_catalogs/dataset-dry",
            venue_names=("CME", "SIM"),
            data_count=2,
            instrument_ids=("AAA.SIM", "ZZZ.SIM"),
            bar_types=(
                "AAA.SIM-30-MINUTE-LAST-EXTERNAL",
                "ZZZ.SIM-30-MINUTE-LAST-EXTERNAL",
            ),
            strategy_ids=("fixture_strategy_b", "fixture_strategy_a"),
        )
    )

    assert output.splitlines() == [
        "OK dry-run",
        "run_id: run-dry",
        "run_kind: portfolio",
        "dataset_id: dataset-dry",
        "runtime_root: var/runtime/nautilus/run-dry",
        "artifact_root: var/runtime/nautilus/run-dry/artifacts",
        "catalog_root: var/cache/nautilus_catalogs/dataset-dry",
        "data_count: 2",
        "venue_names:",
        "  CME",
        "  SIM",
        "instrument_ids:",
        "  AAA.SIM",
        "  ZZZ.SIM",
        "bar_types:",
        "  AAA.SIM-30-MINUTE-LAST-EXTERNAL",
        "  ZZZ.SIM-30-MINUTE-LAST-EXTERNAL",
        "strategy_ids:",
        "  fixture_strategy_b",
        "  fixture_strategy_a",
    ]
