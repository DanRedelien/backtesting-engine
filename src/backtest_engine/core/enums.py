"""Project-wide enums shared across bounded contexts."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Base enum with string serialization."""


class RunKind(StrEnum):
    SINGLE = "single"
    PORTFOLIO = "portfolio"
    BATCH = "batch"
    WALK_FORWARD = "walk_forward"
    SCENARIO = "scenario"
    BASELINE = "baseline"


class RuntimeBoundary(StrEnum):
    NAUTILUS = "nautilus"


class DatasetSource(StrEnum):
    IB = "ib"
    MT5 = "mt5"
    PARQUET = "parquet"
    SYNTHETIC = "synthetic"


class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class WarmupPolicy(StrEnum):
    HOLD_FLAT_UNTIL_LOOKBACK = "hold_flat_until_lookback"


class StudyVerdict(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class RecommendationStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    ADVISORY = "ADVISORY"
    BLOCKED = "BLOCKED"


__all__ = [
    "DatasetSource",
    "OrderSide",
    "OrderType",
    "RecommendationStatus",
    "RunKind",
    "RuntimeBoundary",
    "SignalDirection",
    "StudyVerdict",
    "WarmupPolicy",
]
