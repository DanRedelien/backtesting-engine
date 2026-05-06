"""Small shared protocols used at package boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """A UTC clock injected into use-cases."""

    def now_utc(self) -> datetime:
        """Return the current UTC timestamp."""
        ...


__all__ = ["Clock"]
