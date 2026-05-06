"""Argument parsing for the runnable backtest CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NoReturn

from backtest_engine.core.errors import ApplicationError


class ParserUsageError(ApplicationError):
    """Raised when backtest CLI arguments are invalid."""


class BacktestArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports usage through typed application errors."""

    def error(self, message: str) -> NoReturn:
        raise ParserUsageError(
            "invalid backtest CLI arguments",
            usage=self.format_usage().strip(),
            argparse_message=message,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the runnable backtest CLI parser."""

    parser = BacktestArgumentParser(prog="python -m backtest_engine.interfaces.cli.backtest")
    subparsers = parser.add_subparsers(dest="command")

    single = subparsers.add_parser("single")
    _add_common_run_arguments(single)
    single.add_argument("--bundle-label")

    portfolio = subparsers.add_parser("portfolio")
    _add_common_run_arguments(portfolio)
    return parser


def _add_common_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--execution-costs-path", type=Path)
    parser.add_argument("--requested-by", default="cli")
    parser.add_argument("--correlation-id")
    parser.add_argument("--dry-run", action="store_true")


__all__ = [
    "ParserUsageError",
    "build_parser",
]
