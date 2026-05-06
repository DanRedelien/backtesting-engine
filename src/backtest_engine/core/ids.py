"""Deterministic identifiers and content hashes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Annotated, TypeAlias

from pydantic import StringConstraints

RunId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^run-[0-9a-f]{12}$")]
DatasetId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^dataset-[0-9a-f]{12}$")]
BundleId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^bundle-[0-9a-f]{12}$")]
StudyId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^study-[0-9a-f]{12}$")]
RecommendationId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^recommendation-[0-9a-f]{12}$"),
]
StrategyId: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def stable_hash(payload: Any) -> str:
    """Return a deterministic hash for a JSON-serializable payload."""

    encoded = json.dumps(
        payload,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_run_id(content_hash: str) -> str:
    """Build a stable run identifier from a content hash."""

    return f"run-{content_hash[:12]}"


def build_dataset_id(content_hash: str) -> str:
    """Build a stable dataset identifier from a content hash."""

    return f"dataset-{content_hash[:12]}"


def build_bundle_id(content_hash: str) -> str:
    """Build a stable result-bundle identifier from a content hash."""

    return f"bundle-{content_hash[:12]}"


def build_study_id(content_hash: str) -> str:
    """Build a stable study identifier from a content hash."""

    return f"study-{content_hash[:12]}"


def build_recommendation_id(content_hash: str) -> str:
    """Build a stable recommendation identifier from a content hash."""

    return f"recommendation-{content_hash[:12]}"


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


__all__ = [
    "BundleId",
    "DatasetId",
    "RecommendationId",
    "RunId",
    "StudyId",
    "StrategyId",
    "build_bundle_id",
    "build_dataset_id",
    "build_recommendation_id",
    "build_run_id",
    "build_study_id",
    "stable_hash",
]
