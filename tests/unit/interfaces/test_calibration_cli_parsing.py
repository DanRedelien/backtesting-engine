from __future__ import annotations

from pathlib import Path

import pytest

from backtest_engine.interfaces.cli.calibration.parsing import ParserUsageError, build_parser


def test_calibration_cli_parser_accepts_spread_command() -> None:
    args = build_parser().parse_args(
        [
            "spread",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--estimator-timeframe",
            "1m",
            "--output-root",
            "var/runtime/calibration",
            "--requested-by",
            "operator",
            "--correlation-id",
            "calibration-001",
        ]
    )

    assert args.command == "spread"
    assert args.spec == Path("run_profiles/fx_single_asset.yaml")
    assert args.estimator_timeframe == "1m"
    assert args.output_root == Path("var/runtime/calibration")
    assert args.requested_by == "operator"
    assert args.correlation_id == "calibration-001"


def test_calibration_cli_parser_rejects_missing_spec() -> None:
    with pytest.raises(ParserUsageError) as exc_info:
        build_parser().parse_args(["spread"])

    assert "usage" in exc_info.value.context
    assert "--spec" in str(exc_info.value.context["argparse_message"])
