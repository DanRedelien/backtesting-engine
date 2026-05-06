from __future__ import annotations

from pathlib import Path

import pytest

from backtest_engine.interfaces.cli.backtest.parsing import ParserUsageError, build_parser


def test_backtest_cli_parser_accepts_single_with_required_spec() -> None:
    args = build_parser().parse_args(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--requested-by",
            "operator",
            "--correlation-id",
            "correlation-001",
            "--bundle-label",
            "phase-1",
            "--execution-costs-path",
            "var/runtime/calibration/costs.yaml",
        ]
    )

    assert args.command == "single"
    assert args.spec == Path("run_profiles/fx_single_asset.yaml")
    assert args.requested_by == "operator"
    assert args.correlation_id == "correlation-001"
    assert args.bundle_label == "phase-1"
    assert args.execution_costs_path == Path("var/runtime/calibration/costs.yaml")
    assert args.dry_run is False


def test_backtest_cli_parser_accepts_portfolio_with_required_spec() -> None:
    args = build_parser().parse_args(
        [
            "portfolio",
            "--spec",
            "run_profiles/three_slot_portfolio.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/portfolio_costs.yaml",
        ]
    )

    assert args.command == "portfolio"
    assert args.spec == Path("run_profiles/three_slot_portfolio.yaml")
    assert args.requested_by == "cli"
    assert args.correlation_id is None
    assert args.execution_costs_path == Path("var/runtime/calibration/portfolio_costs.yaml")
    assert args.dry_run is False


@pytest.mark.parametrize("subcommand", ("single", "portfolio"))
def test_backtest_cli_parser_accepts_dry_run(subcommand: str) -> None:
    args = build_parser().parse_args(
        [
            subcommand,
            "--spec",
            "run_profiles/profile.yaml",
            "--dry-run",
        ]
    )

    assert args.command == subcommand
    assert args.dry_run is True


@pytest.mark.parametrize("argv", (["single"], ["portfolio"]))
def test_backtest_cli_parser_rejects_missing_spec(argv: list[str]) -> None:
    with pytest.raises(ParserUsageError) as exc_info:
        build_parser().parse_args(argv)

    assert "usage" in exc_info.value.context
    assert "--spec" in str(exc_info.value.context["argparse_message"])
