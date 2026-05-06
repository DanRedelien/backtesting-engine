"""Command-line entrypoint for historical market-data workflows."""

from __future__ import annotations

import argparse
from typing import Protocol, Sequence

from backtest_engine.application.market_data import (
    HistoricalMarketDataBatchResult,
    HistoricalMarketDataRequest,
    MarketDataVerificationBatchResult,
    MarketDataVerificationRequest,
    PartialBatchFailureError,
)
from backtest_engine.bootstrap import build_market_data_service
from backtest_engine.config.settings import load_settings
from backtest_engine.core.errors import BacktestEngineError
from backtest_engine.interfaces.cli.market_data import diagnostics as market_data_diagnostics
from backtest_engine.interfaces.cli.market_data import parsing as market_data_parsing
from backtest_engine.interfaces.cli.market_data import rendering as market_data_rendering


class MarketDataCliService(Protocol):
    """Service contract used by the market-data CLI adapter."""

    def download(self, request: HistoricalMarketDataRequest) -> HistoricalMarketDataBatchResult:
        """Run one historical-data download request."""
        ...

    def verify(self, request: MarketDataVerificationRequest) -> MarketDataVerificationBatchResult:
        """Run one market-data verification request."""
        ...


def main(argv: Sequence[str] | None = None) -> int:
    parser = market_data_parsing.build_parser()
    try:
        args = parser.parse_args(argv)
    except market_data_parsing.ParserUsageError as exc:
        market_data_rendering.print_cli_error(exc)
        return 2
    if not _command_selection_is_valid(args, parser):
        return 2

    settings = load_settings()
    service = build_market_data_service(
        settings,
        diagnostics=market_data_diagnostics.TerminalMarketDataDiagnosticsSink(),
    )

    try:
        if args.action == "download":
            download_result = service.download(market_data_parsing.build_download_request(args))
            market_data_rendering.print_batch_slices(download_result.slice_results)
            if args.dry_run:
                market_data_rendering.print_dry_run_details(download_result)
            return 0

        verification_result = service.verify(market_data_parsing.build_verification_request(args))
        market_data_rendering.print_verification_results(
            verification_result.slice_results,
            detailed=args.detailed,
        )
        return 0
    except PartialBatchFailureError as exc:
        if isinstance(exc.batch_result, MarketDataVerificationBatchResult):
            market_data_rendering.print_verification_results(
                exc.batch_result.slice_results,
                detailed=bool(getattr(args, "detailed", False)),
            )
        else:
            market_data_rendering.print_batch_slices(exc.batch_result.slice_results)
        if getattr(args, "dry_run", False):
            market_data_rendering.print_dry_run_details(exc.batch_result)
        return 1
    except BacktestEngineError as exc:
        market_data_rendering.print_cli_error(exc)
        return 1


def _command_selection_is_valid(args: argparse.Namespace, parser: argparse.ArgumentParser) -> bool:
    if not getattr(args, "action", None):
        parser.print_help()
        return False
    if args.action == "download" and getattr(args, "download_target", None) != "historical-market-data":
        parser.print_help()
        return False
    if args.action == "verify" and getattr(args, "verify_target", None) != "market-data":
        parser.print_help()
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
