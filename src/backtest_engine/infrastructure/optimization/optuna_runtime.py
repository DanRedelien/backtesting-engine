"""Optional Optuna dependency helpers for optimization workflows."""

from __future__ import annotations

from contextlib import contextmanager
from importlib import import_module
from typing import Any, Iterator, cast

from backtest_engine.core.errors import InfrastructureError


try:
    _OPTUNA = import_module("optuna")
except ImportError:
    _OPTUNA = cast(Any, None)


def optuna_is_available() -> bool:
    """Return whether the optional Optuna dependency is installed."""

    return _OPTUNA is not None


def require_optuna() -> Any:
    """Return the imported Optuna module or raise a typed install error."""

    if _OPTUNA is None:
        raise InfrastructureError(
            "Optuna is required for Optuna-backed optimization workflows. "
            "Install it with: pip install backtesting-engine-v2[optuna]",
        )
    return _OPTUNA


@contextmanager
def silence_optuna_logs() -> Iterator[None]:
    """Temporarily reduce Optuna's own chatter during optimization runs."""

    if _OPTUNA is None:
        yield
        return

    _OPTUNA.logging.set_verbosity(_OPTUNA.logging.WARNING)
    try:
        yield
    finally:
        _OPTUNA.logging.set_verbosity(_OPTUNA.logging.INFO)


__all__ = ["optuna_is_available", "require_optuna", "silence_optuna_logs"]
