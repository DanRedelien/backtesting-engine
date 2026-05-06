"""Command-line entrypoint for offline calibration workflows."""

from __future__ import annotations

import argparse
from typing import Any, Sequence

from backtest_engine.core.errors import BacktestEngineError
from backtest_engine.interfaces.cli.calibration import parsing as calibration_parsing
from backtest_engine.interfaces.cli.calibration import rendering as calibration_rendering
from backtest_engine.interfaces.run_profiles import load_run_profile_spec


def main(argv: Sequence[str] | None = None) -> int:
    parser = calibration_parsing.build_parser()
    try:
        args = parser.parse_args(argv)
    except calibration_parsing.ParserUsageError as exc:
        calibration_rendering.print_cli_error(exc)
        return 2
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise

    if not _command_selection_is_valid(args, parser):
        return 2

    try:
        run_spec = load_run_profile_spec(args.spec)
        materializer = build_calibration_dataset_materializer()
        from backtest_engine.interfaces.cli.run_spread_calibration import (
            SpreadCalibrationCliCommand,
        )

        result = run_spread_calibration_cli(
            command=SpreadCalibrationCliCommand(
                run_spec=run_spec,
                spec_path=args.spec,
                estimator_timeframe=args.estimator_timeframe,
                output_root=args.output_root,
                requested_by=args.requested_by,
                correlation_id=args.correlation_id,
            ),
            materializer=materializer,
        )
        calibration_rendering.print_spread_success(
            result,
            spec_path=args.spec,
            run_kind=run_spec.run_kind,
        )
        return 0
    except BacktestEngineError as exc:
        calibration_rendering.print_cli_error(exc)
        return 1


def _command_selection_is_valid(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> bool:
    if getattr(args, "command", None) != "spread":
        parser.print_help()
        return False
    return True


def build_calibration_dataset_materializer() -> Any:
    """Build calibration materializer after parsing selects the calibration command."""

    from backtest_engine.bootstrap.composition_root import (
        build_calibration_dataset_materializer as _build,
    )

    return _build()


def run_spread_calibration_cli(*, command: Any, materializer: Any) -> Any:
    """Run spread calibration after command-line validation succeeds."""

    from backtest_engine.interfaces.cli.run_spread_calibration import (
        run_spread_calibration_cli as _run,
    )

    return _run(command=command, materializer=materializer)


if __name__ == "__main__":
    raise SystemExit(main())
