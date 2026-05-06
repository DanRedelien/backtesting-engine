"""Build and validate dynamic spread feature artifacts for Nautilus fills."""

from __future__ import annotations

import hashlib
import math
import shutil
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, Mapping, Protocol, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.execution_costs import DynamicSpreadRuntimeProfile
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.execution.spreads import LogLinearDynamicHalfSpread
from backtest_engine.domain.execution.instrument_metadata import ExecutionInstrumentMetadata
from backtest_engine.infrastructure.data.coverage_policy import TIMEFRAME_TO_MINUTES
from backtest_engine.infrastructure.data.parquet_normalizer import (
    MaterializedDataset,
    NormalizedBarArtifact,
)
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem


DYNAMIC_SPREAD_FEATURE_SCHEMA_VERSION = "dynamic_spread_features.v1"
FEATURE_OBSERVED_AT_POLICY = "previous_bar_close_minus_1_microsecond"
_FEATURE_OBSERVED_AT_EPSILON = timedelta(microseconds=1)
_TimestampLike = datetime | pd.Timestamp | str
_FeatureRowValue = _TimestampLike | str
_FeatureRow = dict[str, _FeatureRowValue]


class DynamicSpreadFeatureArtifactManifest(BaseModel):
    """Manifest for one persisted dynamic spread feature table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: NonEmptyStr = DYNAMIC_SPREAD_FEATURE_SCHEMA_VERSION
    dataset_id: NonEmptyStr
    source_fingerprint: NonEmptyStr
    instrument_id: NonEmptyStr
    model_hash: NonEmptyStr
    runtime_config_hash: NonEmptyStr
    volatility_floor_price: Decimal
    volatility_signal_method: Literal["true_range_atr"]
    dynamic_order_types: tuple[Literal["market"], ...]
    feature_table_path: Path
    feature_table_hash: NonEmptyStr
    feature_observed_at_policy: NonEmptyStr = FEATURE_OBSERVED_AT_POLICY
    row_count: int = Field(ge=0)
    first_fill_timestamp_utc: datetime | None = None
    last_fill_timestamp_utc: datetime | None = None


class DynamicSpreadFeatureArtifactRef(BaseModel):
    """Importable fill-model reference to one dynamic spread feature artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: NonEmptyStr
    feature_table_path: Path
    manifest_path: Path
    manifest_hash: NonEmptyStr
    feature_table_hash: NonEmptyStr
    schema_version: NonEmptyStr = DYNAMIC_SPREAD_FEATURE_SCHEMA_VERSION
    model_hash: NonEmptyStr
    runtime_config_hash: NonEmptyStr
    volatility_floor_price: Decimal
    volatility_signal_method: Literal["true_range_atr"]
    dynamic_order_types: tuple[Literal["market"], ...]

    def as_config_payload(self) -> dict[str, JsonValue]:
        """Return a JSON-safe payload for Nautilus importable model configs."""

        return cast(dict[str, JsonValue], self.model_dump(mode="json"))


class _ResolvedProfileLike(Protocol):
    @property
    def spread_model(self) -> object: ...


class _ExecutionPolicyInstrumentProfileLike(Protocol):
    @property
    def profile(self) -> _ResolvedProfileLike: ...

    @property
    def metadata(self) -> ExecutionInstrumentMetadata: ...


def build_dynamic_spread_feature_artifacts(
    *,
    materialized_dataset: MaterializedDataset,
    catalog_items: tuple[CatalogItem, ...],
    execution_start_utc: datetime,
    execution_end_utc: datetime,
    runtime_root: Path,
    instrument_profiles: Mapping[str, _ExecutionPolicyInstrumentProfileLike],
    runtime_profiles: Mapping[str, DynamicSpreadRuntimeProfile],
) -> dict[str, DynamicSpreadFeatureArtifactRef]:
    """Build strict-lagged OHLCV feature tables for dynamic spread instruments."""

    artifact_by_symbol = {
        artifact.symbol.strip().upper(): artifact for artifact in materialized_dataset.artifacts
    }
    feature_refs: dict[str, DynamicSpreadFeatureArtifactRef] = {}
    for item in catalog_items:
        instrument_profile = instrument_profiles[item.instrument_id]
        spread_model = instrument_profile.profile.spread_model
        if not isinstance(spread_model, LogLinearDynamicHalfSpread):
            continue

        try:
            normalized_artifact = artifact_by_symbol[item.symbol.strip().upper()]
        except KeyError as exc:
            raise InfrastructureError(
                "missing normalized bars for dynamic spread instrument",
                symbol=item.symbol,
                instrument_id=item.instrument_id,
            ) from exc

        runtime_profile = runtime_profiles.get(item.instrument_id)
        if runtime_profile is None:
            raise InfrastructureError(
                "missing dynamic spread runtime config for instrument",
                symbol=item.symbol,
                instrument_id=item.instrument_id,
            )

        feature_refs[item.instrument_id] = _build_feature_artifact(
            materialized_dataset=materialized_dataset,
            artifact=normalized_artifact,
            item=item,
            spread_model=spread_model,
            runtime_profile=runtime_profile,
            execution_start_utc=execution_start_utc,
            execution_end_utc=execution_end_utc,
            runtime_root=runtime_root,
        )
    return feature_refs


def compute_file_sha256(path: Path) -> str:
    """Return a SHA-256 fingerprint for an artifact file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _build_feature_artifact(
    *,
    materialized_dataset: MaterializedDataset,
    artifact: NormalizedBarArtifact,
    item: CatalogItem,
    spread_model: LogLinearDynamicHalfSpread,
    runtime_profile: DynamicSpreadRuntimeProfile,
    execution_start_utc: datetime,
    execution_end_utc: datetime,
    runtime_root: Path,
) -> DynamicSpreadFeatureArtifactRef:
    frame = _read_normalized_bars(artifact.data_path, item.instrument_id)
    required_history_bars = runtime_profile.required_history_bars
    if len(frame) <= required_history_bars:
        raise InfrastructureError(
            "insufficient normalized bars for dynamic spread feature warmup",
            instrument_id=item.instrument_id,
            required_history_bars=required_history_bars,
            available_bars=len(frame),
        )

    first_eligible_fill_timestamp = _to_utc_datetime(
        frame["ts_event_utc"].iloc[required_history_bars],
    )
    if execution_start_utc < first_eligible_fill_timestamp:
        raise InfrastructureError(
            "execution window starts before first eligible dynamic spread feature row",
            instrument_id=item.instrument_id,
            execution_start_utc=execution_start_utc.isoformat(),
            first_eligible_fill_timestamp_utc=first_eligible_fill_timestamp.isoformat(),
            required_history_bars=required_history_bars,
        )

    rows = _build_feature_rows(
        frame=frame,
        item=item,
        spread_model=spread_model,
        runtime_profile=runtime_profile,
        execution_start_utc=execution_start_utc,
        execution_end_utc=execution_end_utc,
    )

    artifact_root = (
        runtime_root / "dynamic_spread_features" / _artifact_path_part(item.instrument_id)
    )
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    feature_table_path = artifact_root / "features.parquet"
    manifest_path = artifact_root / "manifest.json"
    pd.DataFrame(rows).to_parquet(feature_table_path, index=False)
    feature_table_hash = compute_file_sha256(feature_table_path)

    manifest = DynamicSpreadFeatureArtifactManifest(
        dataset_id=materialized_dataset.dataset.dataset_id,
        source_fingerprint=artifact.manifest.source_fingerprint,
        instrument_id=item.instrument_id,
        model_hash=_stable_model_hash(spread_model),
        runtime_config_hash=_stable_model_hash(runtime_profile),
        volatility_floor_price=runtime_profile.volatility_floor_price,
        volatility_signal_method=runtime_profile.volatility_signal_method,
        dynamic_order_types=runtime_profile.dynamic_order_types,
        feature_table_path=Path("features.parquet"),
        feature_table_hash=feature_table_hash,
        row_count=len(rows),
        first_fill_timestamp_utc=(
            _to_utc_datetime(rows[0]["fill_timestamp_utc"]) if rows else None
        ),
        last_fill_timestamp_utc=(
            _to_utc_datetime(rows[-1]["fill_timestamp_utc"]) if rows else None
        ),
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return DynamicSpreadFeatureArtifactRef(
        instrument_id=item.instrument_id,
        feature_table_path=feature_table_path,
        manifest_path=manifest_path,
        manifest_hash=compute_file_sha256(manifest_path),
        feature_table_hash=feature_table_hash,
        model_hash=manifest.model_hash,
        runtime_config_hash=manifest.runtime_config_hash,
        volatility_floor_price=manifest.volatility_floor_price,
        volatility_signal_method=manifest.volatility_signal_method,
        dynamic_order_types=manifest.dynamic_order_types,
    )


def _read_normalized_bars(path: Path, instrument_id: str) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise InfrastructureError(
            "failed to read normalized bars for dynamic spread features",
            instrument_id=instrument_id,
            path=str(path),
        ) from exc
    required_columns = {"ts_event_utc", "high", "low", "close", "volume"}
    missing_columns = sorted(required_columns.difference(frame.columns))
    if missing_columns:
        raise InfrastructureError(
            "normalized bars missing dynamic spread feature columns",
            instrument_id=instrument_id,
            missing_columns=",".join(missing_columns),
        )
    working = frame.copy()
    working["ts_event_utc"] = pd.to_datetime(working["ts_event_utc"], utc=True)
    working = working.sort_values("ts_event_utc").reset_index(drop=True)
    if working["ts_event_utc"].duplicated().any():
        raise InfrastructureError(
            "normalized bars contain duplicate timestamps for dynamic spread features",
            instrument_id=instrument_id,
        )
    _validate_ohlcv_frame(working, instrument_id)
    return working


def _validate_ohlcv_frame(frame: pd.DataFrame, instrument_id: str) -> None:
    numeric_columns = ("high", "low", "close", "volume")
    for column_name in numeric_columns:
        values = frame[column_name].astype(float)
        if not values.map(math.isfinite).all():
            raise InfrastructureError(
                "normalized bars contain non-finite OHLCV values for dynamic spread features",
                instrument_id=instrument_id,
                column=column_name,
            )
    if (frame["high"].astype(float) < frame["low"].astype(float)).any():
        raise InfrastructureError(
            "normalized bars contain high values below low values for dynamic spread features",
            instrument_id=instrument_id,
        )
    if (
        (frame["close"].astype(float) < frame["low"].astype(float))
        | (frame["close"].astype(float) > frame["high"].astype(float))
    ).any():
        raise InfrastructureError(
            "normalized bars contain close values outside high-low range for dynamic spread features",
            instrument_id=instrument_id,
        )
    if (frame["volume"].astype(float) < 0).any():
        raise InfrastructureError(
            "normalized bars contain negative volume for dynamic spread features",
            instrument_id=instrument_id,
        )


def _build_feature_rows(
    *,
    frame: pd.DataFrame,
    item: CatalogItem,
    spread_model: LogLinearDynamicHalfSpread,
    runtime_profile: DynamicSpreadRuntimeProfile,
    execution_start_utc: datetime,
    execution_end_utc: datetime,
) -> list[_FeatureRow]:
    valid_model_buckets = {bucket.session_bucket_id for bucket in spread_model.session_buckets}
    rows: list[_FeatureRow] = []
    required_history_bars = runtime_profile.required_history_bars
    timeframe_delta = _timeframe_delta(item.timeframe)
    true_ranges = _true_ranges(frame, item.instrument_id)
    volumes = frame["volume"].astype(float)

    for row_index in range(required_history_bars, len(frame)):
        fill_timestamp_utc = _to_utc_datetime(frame["ts_event_utc"].iloc[row_index])
        if fill_timestamp_utc < execution_start_utc or fill_timestamp_utc > execution_end_utc:
            continue
        feature_observed_at_utc = _feature_observed_at_utc(
            previous_bar_open_utc=_to_utc_datetime(frame["ts_event_utc"].iloc[row_index - 1]),
            fill_timestamp_utc=fill_timestamp_utc,
            timeframe_delta=timeframe_delta,
        )
        if feature_observed_at_utc >= fill_timestamp_utc:
            raise InfrastructureError(
                "dynamic spread feature observation timestamp is not strictly before fill timestamp",
                instrument_id=item.instrument_id,
                fill_timestamp_utc=fill_timestamp_utc.isoformat(),
                feature_observed_at_utc=feature_observed_at_utc.isoformat(),
            )

        session_bucket_id = _resolve_session_bucket_id(runtime_profile, fill_timestamp_utc)
        if session_bucket_id not in valid_model_buckets:
            raise InfrastructureError(
                "dynamic spread runtime session bucket is absent from spread model",
                instrument_id=item.instrument_id,
                session_bucket_id=session_bucket_id,
            )

        volatility_signal = _volatility_stress_signal(
            true_ranges=true_ranges,
            row_index=row_index,
            short_window=runtime_profile.volatility_short_window_bars,
            baseline_window=runtime_profile.volatility_baseline_window_bars,
            volatility_floor_price=float(runtime_profile.volatility_floor_price),
            instrument_id=item.instrument_id,
        )
        liquidity_signal, observed_volume = _liquidity_stress_signal(
            volumes=volumes,
            row_index=row_index,
            baseline_window=runtime_profile.volume_baseline_window_bars,
            volume_floor=float(runtime_profile.volume_floor),
            liquidity_required=spread_model.liquidity_weight > Decimal("0"),
            instrument_id=item.instrument_id,
        )
        feature_row: _FeatureRow = {
            "fill_timestamp_utc": fill_timestamp_utc,
            "feature_observed_at_utc": feature_observed_at_utc,
            "session_bucket_id": session_bucket_id,
            "volatility_stress_signal": str(volatility_signal),
            "liquidity_stress_signal": str(liquidity_signal),
            "liquidity_observed_volume": str(Decimal(str(observed_volume))),
        }
        rows.append(feature_row)

    if not rows:
        raise InfrastructureError(
            "dynamic spread feature build produced no rows for execution window",
            instrument_id=item.instrument_id,
            execution_start_utc=execution_start_utc.isoformat(),
            execution_end_utc=execution_end_utc.isoformat(),
        )
    return rows


def _true_ranges(frame: pd.DataFrame, instrument_id: str) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    ranges.iloc[0] = float("nan")
    if not ranges.iloc[1:].map(math.isfinite).all():
        raise InfrastructureError(
            "dynamic spread true-range volatility feature produced a non-finite value",
            instrument_id=instrument_id,
        )
    return ranges


def _volatility_stress_signal(
    *,
    true_ranges: pd.Series,
    row_index: int,
    short_window: int,
    baseline_window: int,
    volatility_floor_price: float,
    instrument_id: str,
) -> Decimal:
    short_values = true_ranges.iloc[row_index - short_window : row_index]
    baseline_values = true_ranges.iloc[row_index - baseline_window : row_index]
    if short_values.isna().any() or baseline_values.isna().any():
        raise InfrastructureError(
            "dynamic spread true-range volatility feature requires prior close history",
            instrument_id=instrument_id,
        )
    short_mean = float(short_values.mean())
    baseline_mean = float(baseline_values.mean())
    if not math.isfinite(short_mean) or not math.isfinite(baseline_mean):
        raise InfrastructureError(
            "dynamic spread volatility feature produced a non-finite value",
            instrument_id=instrument_id,
        )
    if volatility_floor_price <= 0 or not math.isfinite(volatility_floor_price):
        raise InfrastructureError(
            "dynamic spread volatility feature requires a positive volatility floor",
            instrument_id=instrument_id,
        )
    floored_short_mean = max(short_mean, volatility_floor_price)
    floored_baseline_mean = max(baseline_mean, volatility_floor_price)
    return Decimal(str(math.log(floored_short_mean / floored_baseline_mean)))


def _liquidity_stress_signal(
    *,
    volumes: pd.Series,
    row_index: int,
    baseline_window: int,
    volume_floor: float,
    liquidity_required: bool,
    instrument_id: str,
) -> tuple[Decimal, float]:
    observed_volume = float(volumes.iloc[row_index - 1])
    baseline_volume = float(volumes.iloc[row_index - baseline_window : row_index].mean())
    if not math.isfinite(observed_volume) or not math.isfinite(baseline_volume):
        raise InfrastructureError(
            "dynamic spread liquidity feature produced a non-finite value",
            instrument_id=instrument_id,
        )
    if liquidity_required and observed_volume <= 0:
        raise InfrastructureError(
            "dynamic spread liquidity feature requires positive observed volume",
            instrument_id=instrument_id,
        )
    return (
        Decimal(
            str(math.log(max(baseline_volume, volume_floor) / max(observed_volume, volume_floor)))
        ),
        observed_volume,
    )


def _resolve_session_bucket_id(
    runtime_profile: DynamicSpreadRuntimeProfile,
    fill_timestamp_utc: datetime,
) -> str:
    matches = [
        bucket.session_bucket_id
        for bucket in runtime_profile.session_buckets
        if _session_bucket_matches(
            bucket.weekdays,
            bucket.start_time_utc,
            bucket.end_time_utc,
            fill_timestamp_utc,
        )
    ]
    if len(matches) != 1:
        raise InfrastructureError(
            "dynamic spread fill timestamp must map to exactly one UTC session bucket",
            fill_timestamp_utc=fill_timestamp_utc.isoformat(),
            matched_bucket_count=len(matches),
            matched_bucket_ids=",".join(matches),
        )
    return matches[0]


def _session_bucket_matches(
    weekdays: tuple[int, ...],
    start_time_utc: time,
    end_time_utc: time,
    timestamp_utc: datetime,
) -> bool:
    timestamp_time = timestamp_utc.timetz().replace(tzinfo=None)
    weekday = timestamp_utc.weekday()
    if start_time_utc == end_time_utc:
        return weekday in weekdays
    if start_time_utc < end_time_utc:
        return weekday in weekdays and start_time_utc <= timestamp_time < end_time_utc
    previous_weekday = (weekday - 1) % 7
    return (weekday in weekdays and timestamp_time >= start_time_utc) or (
        previous_weekday in weekdays and timestamp_time < end_time_utc
    )


def _stable_model_hash(model: BaseModel) -> str:
    payload = model.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _feature_observed_at_utc(
    *,
    previous_bar_open_utc: datetime,
    fill_timestamp_utc: datetime,
    timeframe_delta: timedelta,
) -> datetime:
    previous_bar_close_utc = previous_bar_open_utc + timeframe_delta
    if previous_bar_close_utc > fill_timestamp_utc:
        raise InfrastructureError(
            "dynamic spread previous bar closes after fill timestamp",
            previous_bar_close_utc=previous_bar_close_utc.isoformat(),
            fill_timestamp_utc=fill_timestamp_utc.isoformat(),
        )
    observed_at_utc = previous_bar_close_utc - _FEATURE_OBSERVED_AT_EPSILON
    if observed_at_utc >= fill_timestamp_utc:
        observed_at_utc = fill_timestamp_utc - _FEATURE_OBSERVED_AT_EPSILON
    return observed_at_utc


def _timeframe_delta(timeframe: str) -> timedelta:
    normalized_timeframe = timeframe.strip().lower()
    try:
        timeframe_minutes = TIMEFRAME_TO_MINUTES[normalized_timeframe]
    except KeyError as exc:
        raise InfrastructureError(
            "unsupported timeframe for dynamic spread feature availability",
            timeframe=timeframe,
            supported_timeframes=",".join(sorted(TIMEFRAME_TO_MINUTES)),
        ) from exc
    return timedelta(minutes=timeframe_minutes)


def _artifact_path_part(value: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_" for character in value
    )
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{sanitized}_{digest}"


def _to_utc_datetime(value: _TimestampLike) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


__all__ = [
    "DYNAMIC_SPREAD_FEATURE_SCHEMA_VERSION",
    "DynamicSpreadFeatureArtifactManifest",
    "DynamicSpreadFeatureArtifactRef",
    "FEATURE_OBSERVED_AT_POLICY",
    "build_dynamic_spread_feature_artifacts",
    "compute_file_sha256",
]
