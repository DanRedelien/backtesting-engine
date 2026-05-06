"""Shared type aliases used across bounded contexts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, TypeAlias

from pydantic import StringConstraints
from typing_extensions import TypeAliasType

NonEmptyStr: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ContentHash: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=12, max_length=64),
]
CurrencyCode: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=3, max_length=3),
]
Symbol: TypeAlias = NonEmptyStr
Timeframe: TypeAlias = NonEmptyStr
SemanticVersion: TypeAlias = NonEmptyStr
UtcDateTime: TypeAlias = datetime
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue = TypeAliasType(
    "JsonValue",
    "JsonScalar | list[JsonValue] | dict[str, JsonValue]",
)
JsonArray = TypeAliasType("JsonArray", "list[JsonValue]")
JsonObject = TypeAliasType("JsonObject", "dict[str, JsonValue]")

__all__ = [
    "JsonArray",
    "JsonObject",
    "ContentHash",
    "CurrencyCode",
    "JsonScalar",
    "JsonValue",
    "NonEmptyStr",
    "SemanticVersion",
    "Symbol",
    "Timeframe",
    "UtcDateTime",
]
