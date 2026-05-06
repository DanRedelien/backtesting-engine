"""Command-line entrypoint for backtest run profiles."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from backtest_engine.config.execution_costs import (
    execution_costs_config_hash,
    load_execution_costs,
)
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError, BacktestEngineError
from backtest_engine.interfaces.cli.backtest import diagnostics as backtest_diagnostics
from backtest_engine.interfaces.cli.backtest import parsing as backtest_parsing
from backtest_engine.interfaces.cli.backtest import rendering as backtest_rendering
from backtest_engine.interfaces.run_profiles import load_run_profile_spec

if TYPE_CHECKING:
    from backtest_engine.config.runtime import BacktestRunSpec


def main(argv: Sequence[str] | None = None) -> int:
    parser = backtest_parsing.build_parser()
    try:
        args = parser.parse_args(argv)
    except backtest_parsing.ParserUsageError as exc:
        backtest_rendering.print_cli_error(exc)
        return 2
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise

    if not _command_selection_is_valid(args, parser):
        return 2

    try:
        run_spec = load_run_profile_spec(args.spec)
        execution_costs_path = _validate_execution_costs_handoff(
            run_spec,
            args.execution_costs_path,
        )
        if args.command == RunKind.SINGLE.value:
            _require_run_kind(run_spec, RunKind.SINGLE, subcommand=args.command)
            container = build_cli_container(
                diagnostics=backtest_diagnostics.TerminalBacktestDiagnosticsSink(),
                execution_costs_path=execution_costs_path,
            )
            if args.dry_run:
                from backtest_engine.application.backtests.dry_run_backtest import (
                    BacktestDryRunCommand,
                )

                dry_run_result = container.dry_run_backtest(
                    BacktestDryRunCommand(
                        requested_by=args.requested_by,
                        correlation_id=args.correlation_id,
                    ),
                    run_spec=run_spec,
                )
                backtest_rendering.print_dry_run_success(dry_run_result)
                return 0
            from backtest_engine.interfaces.cli.run_single_backtest import (
                SingleBacktestCliCommand,
                run_single_backtest_cli,
            )

            single_result = run_single_backtest_cli(
                command=SingleBacktestCliCommand(
                    run_spec=run_spec,
                    requested_by=args.requested_by,
                    correlation_id=args.correlation_id,
                    bundle_label=args.bundle_label,
                ),
                runner=container,
            )
            backtest_rendering.print_single_success(single_result)
            return 0

        _require_run_kind(run_spec, RunKind.PORTFOLIO, subcommand=args.command)
        container = build_cli_container(
            diagnostics=backtest_diagnostics.TerminalBacktestDiagnosticsSink(),
            execution_costs_path=execution_costs_path,
        )
        if args.dry_run:
            from backtest_engine.application.backtests.dry_run_backtest import (
                BacktestDryRunCommand,
            )

            dry_run_result = container.dry_run_backtest(
                BacktestDryRunCommand(
                    requested_by=args.requested_by,
                    correlation_id=args.correlation_id,
                ),
                run_spec=run_spec,
            )
            backtest_rendering.print_dry_run_success(dry_run_result)
            return 0
        from backtest_engine.interfaces.cli.run_portfolio_backtest import (
            PortfolioBacktestCliCommand,
            run_portfolio_backtest_cli,
        )

        portfolio_result = run_portfolio_backtest_cli(
            command=PortfolioBacktestCliCommand(
                run_spec=run_spec,
                requested_by=args.requested_by,
                correlation_id=args.correlation_id,
            ),
            runner=container,
        )
        backtest_rendering.print_portfolio_success(portfolio_result)
        return 0
    except BacktestEngineError as exc:
        backtest_rendering.print_cli_error(exc)
        return 1


def _command_selection_is_valid(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> bool:
    if getattr(args, "command", None) not in {RunKind.SINGLE.value, RunKind.PORTFOLIO.value}:
        parser.print_help()
        return False
    return True


def build_cli_container(**kwargs: Any) -> Any:
    """Build the CLI container after parsing selects an executable command."""

    from backtest_engine.bootstrap.composition_root import build_cli_container as _build

    return _build(**kwargs)


def _require_run_kind(
    run_spec: "BacktestRunSpec",
    expected: RunKind,
    *,
    subcommand: str,
) -> None:
    if run_spec.run_kind is expected:
        return
    raise ApplicationError(
        "backtest CLI subcommand/profile mismatch",
        subcommand=subcommand,
        expected_run_kind=expected.value,
        actual_run_kind=run_spec.run_kind.value,
    )


def _validate_execution_costs_handoff(
    run_spec: "BacktestRunSpec",
    execution_costs_path: Path | None,
) -> Path | None:
    if execution_costs_path is None:
        return None

    actual_hash = _load_execution_costs_hash(
        execution_costs_path,
        run_id=run_spec.run_id,
    )
    if run_spec.execution_policy is None:
        raise ApplicationError(
            "--execution-costs-path requires execution_policy.execution_costs.config_content_hash",
            execution_costs_path=str(execution_costs_path),
            actual_config_content_hash=actual_hash,
            run_profile_snippet=_execution_costs_run_profile_snippet(actual_hash),
            run_id=run_spec.run_id,
        )

    expected_hash = run_spec.execution_policy.execution_costs.config_content_hash
    if expected_hash is None:
        raise ApplicationError(
            "--execution-costs-path requires execution_policy.execution_costs.config_content_hash",
            execution_costs_path=str(execution_costs_path),
            actual_config_content_hash=actual_hash,
            run_profile_snippet=_execution_costs_run_profile_snippet(actual_hash),
            run_id=run_spec.run_id,
        )
    if actual_hash != expected_hash:
        raise ApplicationError(
            "--execution-costs-path hash does not match run profile",
            execution_costs_path=str(execution_costs_path),
            expected_config_content_hash=expected_hash,
            actual_config_content_hash=actual_hash,
            run_profile_snippet=_execution_costs_run_profile_snippet(actual_hash),
            run_id=run_spec.run_id,
        )
    return execution_costs_path


def _load_execution_costs_hash(
    execution_costs_path: Path,
    *,
    run_id: str,
) -> str:
    try:
        loaded_execution_costs = load_execution_costs(execution_costs_path)
    except Exception as exc:
        raise ApplicationError(
            "failed to load --execution-costs-path",
            execution_costs_path=str(execution_costs_path),
            run_id=run_id,
        ) from exc
    return execution_costs_config_hash(loaded_execution_costs)


def _execution_costs_run_profile_snippet(config_content_hash: str) -> dict[str, object]:
    return {
        "execution_policy": {
            "execution_costs": {
                "profile_id": "default_execution_costs",
                "config_content_hash": config_content_hash,
            }
        }
    }


if __name__ == "__main__":
    raise SystemExit(main())
