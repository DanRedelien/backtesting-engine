"""Load operator run profiles into canonical backtest run specs."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backtest_engine.config.runtime import (
    BacktestExecutionPolicy,
    BacktestRunSpec,
    ExecutionWindow,
    PortfolioExecutionPolicy,
)
from backtest_engine.core.enums import DatasetSource, RunKind, RuntimeBoundary
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.ids import StrategyId
from backtest_engine.core.money import Money
from backtest_engine.core.types import JsonValue, NonEmptyStr, Symbol, Timeframe
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)


PROFILE_SIZE_LIMIT_BYTES = 1024 * 1024
SUPPORTED_PROFILE_SUFFIXES = frozenset({".toml", ".yaml", ".yml"})
IMPLEMENTATION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
RUNNABLE_PROFILE_RUN_KINDS = frozenset({RunKind.SINGLE, RunKind.PORTFOLIO})


class RunProfileExecutionWindow(BaseModel):
    """Operator-facing execution window for a run profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_utc: datetime
    end_utc: datetime

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _reject_naive_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run-profile datetimes must be timezone-aware")
        return value


class RunProfileDataset(BaseModel):
    """Operator-facing dataset identity for a run profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: DatasetSource
    normalization_policy: NonEmptyStr
    schema_version: NonEmptyStr
    symbol_universe: tuple[Symbol, ...] = Field(min_length=1)
    timeframe: Timeframe
    dataset_version: NonEmptyStr

    @model_validator(mode="after")
    def _validate_symbol_universe(self) -> "RunProfileDataset":
        _reject_duplicates(self.symbol_universe, field_name="dataset.symbol_universe")
        return self


class RunProfileStrategySlot(BaseModel):
    """One operator-facing strategy slot in a run profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: NonEmptyStr
    weight_frac: float = Field(ge=0.0, le=1.0)
    strategy_id: StrategyId
    implementation_id: NonEmptyStr
    policy_version: NonEmptyStr = "v1"
    legs: tuple[Symbol, ...] = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("implementation_id")
    @classmethod
    def _validate_implementation_id(cls, value: str) -> str:
        if IMPLEMENTATION_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "implementation_id must match ^[a-z][a-z0-9_]*$",
            )
        return value

    @field_validator("parameters", mode="before")
    @classmethod
    def _validate_parameter_payload(cls, value: object) -> object:
        _validate_json_value(value, field_path="parameters")
        return value

    @model_validator(mode="after")
    def _validate_legs(self) -> "RunProfileStrategySlot":
        _reject_duplicates(self.legs, field_name="strategies.legs")
        return self


class RunProfile(BaseModel):
    """Operator-facing launch profile translated into ``BacktestRunSpec``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_kind: RunKind
    execution_window: RunProfileExecutionWindow
    dataset: RunProfileDataset
    capital_base: Money
    strategies: tuple[RunProfileStrategySlot, ...] = Field(min_length=1)
    portfolio_policy: PortfolioExecutionPolicy | None = None
    execution_policy: BacktestExecutionPolicy | None = None
    runtime_boundary: RuntimeBoundary = RuntimeBoundary.NAUTILUS
    semantic_policy_version: NonEmptyStr = "v1"
    tags: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @field_validator("run_kind")
    @classmethod
    def _validate_runnable_run_kind(cls, value: RunKind) -> RunKind:
        if value not in RUNNABLE_PROFILE_RUN_KINDS:
            raise ValueError("run profiles support only single and portfolio run_kind values")
        return value

    @model_validator(mode="after")
    def _validate_unique_profile_fields(self) -> "RunProfile":
        _reject_duplicates(
            tuple(strategy.slot_id for strategy in self.strategies),
            field_name="strategies.slot_id",
        )
        _reject_duplicates(self.tags, field_name="tags")
        return self


def load_run_profile(path: Path | str) -> RunProfile:
    """Load and validate a YAML or TOML run profile."""

    profile_path = Path(path)
    raw_profile = _load_profile_mapping(profile_path)
    try:
        return RunProfile.model_validate(raw_profile)
    except ValidationError as exc:
        raise _application_error_from_validation(
            exc,
            profile_path=profile_path,
            message="run-profile validation failed",
        ) from exc


def load_run_profile_spec(path: Path | str) -> BacktestRunSpec:
    """Load a YAML or TOML run profile into the canonical run spec."""

    profile_path = Path(path)
    profile = load_run_profile(profile_path)
    return _run_profile_to_spec(profile, profile_path=profile_path)


def run_profile_to_spec(profile: RunProfile) -> BacktestRunSpec:
    """Translate a validated run profile into the canonical run spec."""

    return _run_profile_to_spec(profile, profile_path=None)


def _run_profile_to_spec(
    profile: RunProfile,
    *,
    profile_path: Path | None,
) -> BacktestRunSpec:
    try:
        return BacktestRunSpec(
            run_kind=profile.run_kind,
            runtime_boundary=profile.runtime_boundary,
            execution_window=ExecutionWindow(
                start_utc=profile.execution_window.start_utc,
                end_utc=profile.execution_window.end_utc,
            ),
            dataset=DatasetSpec(
                source_system=profile.dataset.source_system,
                normalization_policy=profile.dataset.normalization_policy,
                schema_version=profile.dataset.schema_version,
                symbol_universe=profile.dataset.symbol_universe,
                timeframe=profile.dataset.timeframe,
                dataset_version=profile.dataset.dataset_version,
            ),
            strategies=tuple(_strategy_slot_to_spec(slot) for slot in profile.strategies),
            capital_base=profile.capital_base,
            portfolio_policy=profile.portfolio_policy,
            execution_policy=profile.execution_policy,
            semantic_policy_version=profile.semantic_policy_version,
            tags=profile.tags,
        )
    except ValidationError as exc:
        raise _application_error_from_validation(
            exc,
            profile_path=profile_path,
            message="run-profile canonical validation failed",
        ) from exc
    except ValueError as exc:
        raise _profile_error(
            "run-profile canonical validation failed",
            profile_path=profile_path,
            field_path="<root>",
            error_type=type(exc).__name__,
            detail=str(exc),
        ) from exc


def _strategy_slot_to_spec(slot: RunProfileStrategySlot) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id=slot.slot_id,
        weight_frac=slot.weight_frac,
        strategy=StrategySpec(
            strategy_id=slot.strategy_id,
            implementation_id=slot.implementation_id,
            policy_version=slot.policy_version,
            parameters=slot.parameters,
        ),
        legs=tuple(StrategyLegSpec(symbol=symbol) for symbol in slot.legs),
    )


def _load_profile_mapping(profile_path: Path) -> dict[str, Any]:
    suffix = profile_path.suffix.lower()
    if suffix not in SUPPORTED_PROFILE_SUFFIXES:
        raise _profile_error(
            "unsupported run-profile file extension",
            profile_path=profile_path,
            field_path="<path>",
            error_type="unsupported_suffix",
            detail=f"supported suffixes: {', '.join(sorted(SUPPORTED_PROFILE_SUFFIXES))}",
        )

    text = _read_profile_text(profile_path)
    if suffix == ".toml":
        payload = _parse_toml_profile(text, profile_path=profile_path)
    else:
        payload = _parse_yaml_profile(text, profile_path=profile_path)

    if not isinstance(payload, Mapping):
        raise _profile_error(
            "run-profile document must be a top-level mapping",
            profile_path=profile_path,
            field_path="<root>",
            error_type="non_mapping_document",
            detail=f"got {type(payload).__name__}",
        )
    if not payload:
        raise _profile_error(
            "run-profile document must not be empty",
            profile_path=profile_path,
            field_path="<root>",
            error_type="empty_document",
            detail="empty mapping",
        )
    return dict(payload)


def _read_profile_text(profile_path: Path) -> str:
    try:
        raw_bytes = profile_path.read_bytes()
    except OSError as exc:
        raise _profile_error(
            "run-profile file could not be read",
            profile_path=profile_path,
            field_path="<path>",
            error_type=type(exc).__name__,
            detail=str(exc),
        ) from exc
    if len(raw_bytes) > PROFILE_SIZE_LIMIT_BYTES:
        raise _profile_error(
            "run-profile file is too large",
            profile_path=profile_path,
            field_path="<path>",
            error_type="profile_too_large",
            detail=f"limit is {PROFILE_SIZE_LIMIT_BYTES} bytes",
        )
    if not raw_bytes.strip():
        raise _profile_error(
            "run-profile document must not be empty",
            profile_path=profile_path,
            field_path="<root>",
            error_type="empty_document",
            detail="file is empty or whitespace only",
        )
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _profile_error(
            "run-profile file must be UTF-8",
            profile_path=profile_path,
            field_path="<path>",
            error_type=type(exc).__name__,
            detail=str(exc),
        ) from exc


def _parse_yaml_profile(text: str, *, profile_path: Path) -> object:
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise _profile_error(
            "run-profile YAML could not be parsed",
            profile_path=profile_path,
            field_path="<root>",
            error_type=type(exc).__name__,
            detail=str(exc),
        ) from exc

    if len(documents) != 1:
        raise _profile_error(
            "run-profile YAML must contain exactly one document",
            profile_path=profile_path,
            field_path="<root>",
            error_type="yaml_document_count",
            detail=f"got {len(documents)} documents",
        )
    return documents[0]


def _parse_toml_profile(text: str, *, profile_path: Path) -> object:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _profile_error(
            "run-profile TOML could not be parsed",
            profile_path=profile_path,
            field_path="<root>",
            error_type=type(exc).__name__,
            detail=str(exc),
        ) from exc


def _validate_json_value(value: object, *, field_path: str) -> None:
    if value is None or type(value) in {bool, str, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field_path} must not contain NaN or infinity")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_json_value(item, field_path=f"{field_path}.{index}")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{field_path} keys must be strings")
            _validate_json_value(item, field_path=f"{field_path}.{key}")
        return
    raise ValueError(f"{field_path} contains non-JSON value {type(value).__name__}")


def _reject_duplicates(values: tuple[str, ...], *, field_name: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        joined = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"{field_name} values must be unique: {joined}")


def _application_error_from_validation(
    exc: ValidationError,
    *,
    profile_path: Path | None,
    message: str,
) -> ApplicationError:
    first_error = exc.errors()[0]
    field_path = _format_field_path(first_error.get("loc", ()))
    detail = str(first_error.get("msg", exc))
    error_type = str(first_error.get("type", type(exc).__name__))
    return _profile_error(
        message,
        profile_path=profile_path,
        field_path=field_path,
        error_type=error_type,
        detail=detail,
    )


def _format_field_path(location: object) -> str:
    if not isinstance(location, tuple) or not location:
        return "<root>"
    return ".".join(str(part) for part in location)


def _profile_error(
    message: str,
    *,
    profile_path: Path | None,
    field_path: str,
    error_type: str,
    detail: str,
) -> ApplicationError:
    return ApplicationError(
        f"{message}: {detail}",
        profile_path=None if profile_path is None else str(profile_path),
        field_path=field_path,
        error_type=error_type,
        detail=detail,
    )


__all__ = [
    "RunProfile",
    "RunProfileDataset",
    "RunProfileExecutionWindow",
    "RunProfileStrategySlot",
    "load_run_profile",
    "load_run_profile_spec",
    "run_profile_to_spec",
]
