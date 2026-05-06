"""Unified CLI surface for historical market data."""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Import the executable entrypoint lazily to avoid `python -m` warnings."""

    from backtest_engine.interfaces.cli.market_data.__main__ import main as _main

    return _main(argv)

__all__ = ["main"]
