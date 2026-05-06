"""Typed error families for the rewrite."""

from __future__ import annotations

from typing import Any


class BacktestEngineError(Exception):
    """Base class for typed application errors."""

    def __init__(self, message: str, **context: Any) -> None:
        self.message = message
        self.context = context
        super().__init__(message)


class DomainError(BacktestEngineError):
    """Raised when a domain invariant is violated."""


class ApplicationError(BacktestEngineError):
    """Raised when a use-case fails or is called incorrectly."""


class InfrastructureError(BacktestEngineError):
    """Raised when a real-world adapter fails."""


__all__ = [
    "ApplicationError",
    "BacktestEngineError",
    "DomainError",
    "InfrastructureError",
]
