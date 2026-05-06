"""Argument parsing and request builders for the market-data CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
from typing import NoReturn

from backtest_engine.application.market_data import (
    HistoricalMarketDataRequest,
    MarketDataVerificationRequest,
)
from backtest_engine.core.errors import ApplicationError


SUPPORTED_PROVIDER_IDS: tuple[str, ...] = ("ib", "mt5")


class ParserUsageError(ApplicationError):
    """Raised when market-data CLI arguments are invalid."""


class MarketDataArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports usage through typed application errors."""

    def error(self, message: str) -> NoReturn:
        raise ParserUsageError(
            "invalid market-data CLI arguments",
            usage=self.format_usage().strip(),
            argparse_message=message,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = MarketDataArgumentParser(prog="python -m backtest_engine.interfaces.cli.market_data")
    action_parsers = parser.add_subparsers(dest="action")

    download = action_parsers.add_parser("download")
    download_subparsers = download.add_subparsers(dest="download_target")
    historical = download_subparsers.add_parser("historical-market-data")
    _add_common_download_args(historical)

    verify = action_parsers.add_parser("verify")
    verify_subparsers = verify.add_subparsers(dest="verify_target")
    market_data = verify_subparsers.add_parser("market-data")
    _add_common_verify_args(market_data)
    return parser


def build_download_request(args: argparse.Namespace) -> HistoricalMarketDataRequest:
    if (args.start is None) != (args.end is None):
        raise ApplicationError(
            "historical market-data download requires either both --start/--end or neither",
            provider_id=args.provider,
        )
    start_utc = None if args.start is None else parse_edge_datetime(args.start, edge="start")
    end_utc = None if args.end is None else parse_edge_datetime(args.end, edge="end")
    if args.provider == "ib" and end_utc is not None and end_utc > datetime.now(timezone.utc):
        raise ApplicationError(
            "IB historical downloads require --end to be no later than the current UTC time",
            provider_id=args.provider,
            end_utc=end_utc.isoformat(),
        )
    return HistoricalMarketDataRequest(
        provider_id=args.provider,
        symbol_universe=tuple(args.symbols),
        timeframes=tuple(args.timeframes),
        start_utc=start_utc,
        end_utc=end_utc,
        dry_run=args.dry_run,
        force=args.force,
    )


def build_verification_request(args: argparse.Namespace) -> MarketDataVerificationRequest:
    return MarketDataVerificationRequest(
        provider_id=args.provider,
        symbol_universe=tuple(args.symbols),
        timeframes=tuple(args.timeframes),
    )


def parse_edge_datetime(raw_value: str, *, edge: str) -> datetime:
    if "T" in raw_value:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    parsed_date = datetime.fromisoformat(raw_value).date()
    if edge == "start":
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    return datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)


def _add_common_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", required=True, choices=SUPPORTED_PROVIDER_IDS)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--timeframes", nargs="+", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")


def _add_common_verify_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", required=True, choices=SUPPORTED_PROVIDER_IDS)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--timeframes", nargs="+", required=True)
    parser.add_argument("--detailed", action="store_true")


__all__ = [
    "ParserUsageError",
    "build_download_request",
    "build_parser",
    "build_verification_request",
]
