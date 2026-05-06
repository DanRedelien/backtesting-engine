"""Typed diagnostics contracts for infrastructure-owned observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from backtest_engine.core.types import JsonObject, NonEmptyStr

DiagnosticStatus = Literal["started", "succeeded", "failed"]


@dataclass(frozen=True)
class StageDiagnosticEvent:
    """One structured stage event emitted by infrastructure adapters."""

    stage: NonEmptyStr
    status: DiagnosticStatus
    message: NonEmptyStr
    requested_by: NonEmptyStr
    run_id: NonEmptyStr | None = None
    correlation_id: NonEmptyStr | None = None
    run_kind: NonEmptyStr | None = None
    details: JsonObject = field(default_factory=dict)


class DiagnosticsSink(Protocol):
    """Record stage-aware diagnostics for later inspection or logging."""

    def emit(self, event: StageDiagnosticEvent) -> None:
        """Persist or log one structured stage event."""
        ...


@dataclass
class InMemoryDiagnosticsSink:
    """Collect diagnostics in memory for tests and local inspection."""

    events: list[StageDiagnosticEvent] = field(default_factory=list)

    def emit(self, event: StageDiagnosticEvent) -> None:
        self.events.append(event)


class NullDiagnosticsSink:
    """Ignore diagnostics when a caller does not want to observe them."""

    def emit(self, event: StageDiagnosticEvent) -> None:
        return None


__all__ = [
    "DiagnosticStatus",
    "DiagnosticsSink",
    "InMemoryDiagnosticsSink",
    "NullDiagnosticsSink",
    "StageDiagnosticEvent",
]
