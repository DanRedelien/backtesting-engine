"""Argument parsing for the runnable calibration CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NoReturn

from backtest_engine.core.errors import ApplicationError


class ParserUsageError(ApplicationError):
    """Raised when calibration CLI arguments are invalid."""


class CalibrationArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports usage through typed application errors."""

    def error(self, message: str) -> NoReturn:
        raise ParserUsageError(
            "invalid calibration CLI arguments",
            usage=self.format_usage().strip(),
            argparse_message=message,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the runnable calibration CLI parser."""

    parser = CalibrationArgumentParser(
        prog="python -m backtest_engine.interfaces.cli.calibration"
    )
    subparsers = parser.add_subparsers(dest="command")

    spread = subparsers.add_parser("spread")
    spread.add_argument("--spec", required=True, type=Path)
    spread.add_argument("--estimator-timeframe", default="1m")
    spread.add_argument("--output-root", default=Path("var/runtime/calibration"), type=Path)
    spread.add_argument("--requested-by", default="cli")
    spread.add_argument("--correlation-id")
    return parser


__all__ = [
    "ParserUsageError",
    "build_parser",
]
