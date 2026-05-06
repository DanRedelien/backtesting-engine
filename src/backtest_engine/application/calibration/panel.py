"""Build ex-ante EDGE calibration panels from verified normalized OHLCV bars."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from backtest_engine.config.execution_costs import UtcSessionBucketRule
from backtest_engine.application.calibration.contracts import (
    SpreadCalibrationCommand,
    SpreadCalibrationPanelRow,
    SpreadCalibrationResult,
    SpreadCalibrationSymbolSummary,
)
from backtest_engine.application.calibration.edge import (
    estimate_edge_spread,
    first_invalid_ohlc_shape_index,
)
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.ids import stable_hash
from backtest_engine.infrastructure.data.coverage_policy import TIMEFRAME_TO_MINUTES
from backtest_engine.infrastructure.data.market_data_contracts import (
    SourceSliceManifest,
    ValidationManifest,
)
from backtest_engine.infrastructure.data.parquet_normalizer import (
    NormalizedBarArtifact,
    NormalizedBarManifest,
)


_REQUIRED_COLUMNS = ("ts_event_utc", "open", "high", "low", "close", "volume")
_OBSERVED_AT_EPSILON = timedelta(microseconds=1)


@dataclass(frozen=True)
class _VolumeDiagnostics:
    positive_volume_row_count: int
    zero_volume_row_count: int


def build_spread_calibration_panel(
    command: SpreadCalibrationCommand,
) -> SpreadCalibrationResult:
    """Build a Phase-1 EDGE panel without touching Nautilus runtime wiring."""

    dataset = command.materialized_dataset.dataset
    if dataset.timeframe != command.estimator_timeframe:
        raise ApplicationError(
            "spread calibration estimator timeframe must match the materialized dataset",
            dataset_timeframe=dataset.timeframe,
            estimator_timeframe=command.estimator_timeframe,
        )

    panel_rows: list[SpreadCalibrationPanelRow] = []
    summaries: list[SpreadCalibrationSymbolSummary] = []
    source_fingerprints: dict[str, str] = {}
    for artifact in command.materialized_dataset.artifacts:
        if artifact.timeframe != command.estimator_timeframe:
            raise ApplicationError(
                "spread calibration artifact timeframe mismatch",
                symbol=artifact.symbol,
                artifact_timeframe=artifact.timeframe,
                estimator_timeframe=command.estimator_timeframe,
            )
        normalized_manifest = _load_and_validate_normalized_manifest(
            artifact=artifact,
            command=command,
        )
        _assert_fresh_pass_validation(
            artifact=artifact,
            normalized_manifest=normalized_manifest,
            validator_ruleset_version=command.validator_ruleset_version,
        )

        frame, volume_diagnostics = _read_verified_normalized_frame(
            artifact=artifact,
            normalized_manifest=normalized_manifest,
            command=command,
        )
        rows, summary = _build_symbol_panel_rows(
            command=command,
            artifact=artifact,
            frame=frame,
            volume_diagnostics=volume_diagnostics,
        )
        if summary.usable_row_count < command.minimum_usable_rows_per_symbol:
            raise ApplicationError(
                "insufficient usable EDGE calibration rows for symbol",
                symbol=artifact.symbol,
                usable_row_count=summary.usable_row_count,
                minimum_usable_rows_per_symbol=command.minimum_usable_rows_per_symbol,
                invalid_reason_counts=summary.invalid_reason_counts,
            )
        panel_rows.extend(rows)
        summaries.append(summary)
        source_fingerprints[artifact.symbol] = artifact.manifest.source_fingerprint

    if not panel_rows:
        raise ApplicationError(
            "spread calibration produced no usable panel rows",
            dataset_id=dataset.dataset_id,
            artifact_count=len(command.materialized_dataset.artifacts),
        )

    calibration_id = _calibration_id(
        command=command,
        source_fingerprints=source_fingerprints,
        row_count=len(panel_rows),
    )
    return SpreadCalibrationResult(
        calibration_id=calibration_id,
        dataset_id=command.materialized_dataset.dataset.dataset_id,
        estimator_timeframe=command.estimator_timeframe,
        edge_window_bars=command.edge_window_bars,
        volatility_short_window_bars=command.volatility_short_window_bars,
        volatility_baseline_window_bars=command.volatility_baseline_window_bars,
        volatility_floor_price=command.volatility_floor_price,
        volume_baseline_window_bars=command.volume_baseline_window_bars,
        volume_floor=command.volume_floor,
        session_buckets=command.session_buckets,
        price_basis=command.price_basis,
        panel_rows=tuple(panel_rows),
        symbol_summaries=tuple(summaries),
        source_fingerprints=source_fingerprints,
        requested_by=command.requested_by,
        correlation_id=command.correlation_id,
    )


def _load_and_validate_normalized_manifest(
    *,
    artifact: NormalizedBarArtifact,
    command: SpreadCalibrationCommand,
) -> NormalizedBarManifest:
    try:
        persisted_manifest = NormalizedBarManifest.model_validate_json(
            artifact.manifest_path.read_text(encoding="utf-8"),
        )
    except Exception as exc:
        raise ApplicationError(
            "spread calibration requires readable normalized artifact manifest",
            symbol=artifact.symbol,
            manifest_path=str(artifact.manifest_path),
        ) from exc

    dataset = command.materialized_dataset.dataset
    if persisted_manifest != artifact.manifest:
        raise ApplicationError(
            "normalized artifact manifest object does not match persisted manifest",
            symbol=artifact.symbol,
            manifest_path=str(artifact.manifest_path),
        )
    if artifact.symbol != persisted_manifest.raw_symbol:
        raise ApplicationError(
            "normalized artifact symbol does not match manifest",
            symbol=artifact.symbol,
            manifest_symbol=persisted_manifest.raw_symbol,
        )
    if artifact.timeframe != persisted_manifest.timeframe:
        raise ApplicationError(
            "normalized artifact timeframe does not match manifest",
            symbol=artifact.symbol,
            artifact_timeframe=artifact.timeframe,
            manifest_timeframe=persisted_manifest.timeframe,
        )
    if _normalized_path(artifact.data_path) != _normalized_path(
        artifact.manifest_path.parent / "bars.parquet"
    ):
        raise ApplicationError(
            "normalized artifact data path does not match manifest directory",
            symbol=artifact.symbol,
            data_path=str(artifact.data_path),
            manifest_path=str(artifact.manifest_path),
        )
    if persisted_manifest.dataset_id != dataset.dataset_id:
        raise ApplicationError(
            "normalized artifact dataset_id does not match calibration dataset",
            symbol=artifact.symbol,
            manifest_dataset_id=persisted_manifest.dataset_id,
            dataset_id=dataset.dataset_id,
        )
    if persisted_manifest.source_system != dataset.source_system:
        raise ApplicationError(
            "normalized artifact source_system does not match calibration dataset",
            symbol=artifact.symbol,
            manifest_source_system=persisted_manifest.source_system,
            dataset_source_system=dataset.source_system,
        )
    if persisted_manifest.normalization_policy != dataset.normalization_policy:
        raise ApplicationError(
            "normalized artifact normalization_policy does not match calibration dataset",
            symbol=artifact.symbol,
        )
    if persisted_manifest.schema_version != dataset.schema_version:
        raise ApplicationError(
            "normalized artifact schema_version does not match calibration dataset",
            symbol=artifact.symbol,
        )
    if persisted_manifest.timeframe != dataset.timeframe:
        raise ApplicationError(
            "normalized artifact timeframe does not match calibration dataset",
            symbol=artifact.symbol,
            artifact_timeframe=persisted_manifest.timeframe,
            dataset_timeframe=dataset.timeframe,
        )
    if persisted_manifest.raw_symbol not in dataset.symbol_universe:
        raise ApplicationError(
            "normalized artifact symbol is absent from calibration dataset universe",
            symbol=artifact.symbol,
        )
    if not set(_REQUIRED_COLUMNS).issubset(set(persisted_manifest.columns)):
        raise ApplicationError(
            "normalized artifact manifest columns do not include calibration OHLCV columns",
            symbol=artifact.symbol,
            manifest_columns=",".join(persisted_manifest.columns),
        )
    return persisted_manifest


def _assert_fresh_pass_validation(
    *,
    artifact: NormalizedBarArtifact,
    normalized_manifest: NormalizedBarManifest,
    validator_ruleset_version: str,
) -> None:
    if normalized_manifest.source_system not in {DatasetSource.IB, DatasetSource.MT5}:
        raise ApplicationError(
            "spread calibration requires provider-managed verified source data",
            symbol=artifact.symbol,
            source_system=normalized_manifest.source_system,
        )

    source_path = normalized_manifest.source_path
    source_manifest_path = source_path.parent / "source_manifest.json"
    validation_manifest_path = source_path.parent / "validation_manifest.json"
    try:
        current_fingerprint = _compute_file_sha256(source_path)
        source_manifest = SourceSliceManifest.model_validate_json(
            source_manifest_path.read_text(encoding="utf-8"),
        )
        validation_manifest = ValidationManifest.model_validate_json(
            validation_manifest_path.read_text(encoding="utf-8"),
        )
    except Exception as exc:
        raise ApplicationError(
            "spread calibration requires readable source and validation manifests",
            symbol=artifact.symbol,
            source_path=str(source_path),
        ) from exc

    expected_provider_id = normalized_manifest.source_system.value
    if (
        source_manifest.provider_id != expected_provider_id
        or source_manifest.canonical_symbol != normalized_manifest.raw_symbol
        or source_manifest.timeframe != normalized_manifest.timeframe
    ):
        raise ApplicationError(
            "source manifest identity does not match normalized calibration artifact",
            symbol=artifact.symbol,
            source_manifest_path=str(source_manifest_path),
        )
    if _normalized_path(source_manifest.bars_path) != _normalized_path(
        normalized_manifest.source_path
    ):
        raise ApplicationError(
            "source manifest bars_path does not match normalized artifact source_path",
            symbol=artifact.symbol,
            source_manifest_path=str(source_manifest_path),
        )
    if source_manifest.row_count != normalized_manifest.row_count:
        raise ApplicationError(
            "source manifest row_count does not match normalized artifact manifest",
            symbol=artifact.symbol,
            source_manifest_path=str(source_manifest_path),
        )
    if source_manifest.source_fingerprint != current_fingerprint:
        raise ApplicationError(
            "source manifest fingerprint is stale for calibration input",
            symbol=artifact.symbol,
            source_manifest_path=str(source_manifest_path),
        )
    if normalized_manifest.source_fingerprint != current_fingerprint:
        raise ApplicationError(
            "normalized artifact source fingerprint is stale for calibration input",
            symbol=artifact.symbol,
            manifest_path=str(artifact.manifest_path),
        )
    if validation_manifest.verification_verdict != "PASS":
        raise ApplicationError(
            "spread calibration requires PASS market-data verification",
            symbol=artifact.symbol,
            validation_manifest_path=str(validation_manifest_path),
            verification_verdict=validation_manifest.verification_verdict,
        )
    if (
        validation_manifest.provider_id != expected_provider_id
        or validation_manifest.canonical_symbol != normalized_manifest.raw_symbol
        or validation_manifest.timeframe != normalized_manifest.timeframe
    ):
        raise ApplicationError(
            "validation manifest identity does not match normalized calibration artifact",
            symbol=artifact.symbol,
            validation_manifest_path=str(validation_manifest_path),
        )
    if validation_manifest.validator_ruleset_version != validator_ruleset_version:
        raise ApplicationError(
            "validation ruleset version mismatch blocks spread calibration",
            symbol=artifact.symbol,
            validation_manifest_path=str(validation_manifest_path),
            validator_ruleset_version=validation_manifest.validator_ruleset_version,
            expected_validator_ruleset_version=validator_ruleset_version,
        )
    if validation_manifest.source_fingerprint != current_fingerprint:
        raise ApplicationError(
            "validation manifest fingerprint is stale for calibration input",
            symbol=artifact.symbol,
            validation_manifest_path=str(validation_manifest_path),
        )


def _read_verified_normalized_frame(
    *,
    artifact: NormalizedBarArtifact,
    normalized_manifest: NormalizedBarManifest,
    command: SpreadCalibrationCommand,
) -> tuple[pd.DataFrame, _VolumeDiagnostics]:
    try:
        raw = pd.read_parquet(artifact.data_path)
    except Exception as exc:
        raise ApplicationError(
            "failed to read normalized bars for spread calibration",
            symbol=artifact.symbol,
            data_path=str(artifact.data_path),
        ) from exc

    missing_manifest_columns = sorted(set(normalized_manifest.columns).difference(raw.columns))
    if missing_manifest_columns:
        raise ApplicationError(
            "normalized bars are missing columns declared by the artifact manifest",
            symbol=artifact.symbol,
            missing_columns=",".join(missing_manifest_columns),
        )
    missing = sorted(set(_REQUIRED_COLUMNS).difference(raw.columns))
    if missing:
        raise ApplicationError(
            "normalized bars missing spread calibration columns",
            symbol=artifact.symbol,
            missing_columns=",".join(missing),
        )

    frame = raw.loc[:, list(_REQUIRED_COLUMNS)].copy()
    frame["ts_event_utc"] = pd.to_datetime(frame["ts_event_utc"], utc=True)
    volume_diagnostics = _validate_ohlcv_frame(
        frame=frame,
        symbol=artifact.symbol,
        timeframe=command.estimator_timeframe,
        positive_volume_coverage_threshold=command.positive_volume_coverage_threshold,
    )
    _assert_normalized_frame_matches_manifest(
        frame=frame,
        artifact=artifact,
        normalized_manifest=normalized_manifest,
    )
    return frame, volume_diagnostics


def _validate_ohlcv_frame(
    *,
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    positive_volume_coverage_threshold: float,
) -> _VolumeDiagnostics:
    if frame.empty:
        raise ApplicationError("normalized bars are empty for spread calibration", symbol=symbol)

    timestamps = pd.DatetimeIndex(frame["ts_event_utc"])
    if timestamps.hasnans:
        raise ApplicationError(
            "normalized bars contain missing timestamps for spread calibration",
            symbol=symbol,
        )
    if timestamps.has_duplicates:
        raise ApplicationError(
            "normalized bars contain duplicate timestamps for spread calibration",
            symbol=symbol,
        )
    if not timestamps.is_monotonic_increasing:
        raise ApplicationError(
            "normalized bars must be sorted by UTC timestamp for spread calibration",
            symbol=symbol,
        )

    try:
        expected_delta = pd.Timedelta(minutes=TIMEFRAME_TO_MINUTES[timeframe])
    except KeyError as exc:
        raise ApplicationError(
            "unsupported estimator timeframe for spread calibration",
            symbol=symbol,
            timeframe=timeframe,
            supported_timeframes=",".join(sorted(TIMEFRAME_TO_MINUTES)),
        ) from exc

    if len(timestamps) > 1:
        observed_deltas = timestamps.to_series().diff().dropna()
        irregular = observed_deltas[observed_deltas != expected_delta]
        if not irregular.empty:
            raise ApplicationError(
                "normalized bars must be on a regular grid for spread calibration",
                symbol=symbol,
                timeframe=timeframe,
                expected_delta=str(expected_delta),
                first_bad_timestamp=irregular.index[0].isoformat(),
                first_bad_delta=str(irregular.iloc[0]),
            )

    for column_name in ("open", "high", "low", "close", "volume"):
        values = frame[column_name].astype(float)
        if not values.map(math.isfinite).all():
            raise ApplicationError(
                "normalized bars contain non-finite OHLCV values for spread calibration",
                symbol=symbol,
                column=column_name,
            )
    for column_name in ("open", "high", "low", "close"):
        values = frame[column_name].astype(float)
        if (values <= 0.0).any():
            raise ApplicationError(
                "normalized bars contain non-positive OHLC prices for spread calibration",
                symbol=symbol,
                column=column_name,
            )
    open_values = frame["open"].astype(float).tolist()
    high_values = frame["high"].astype(float).tolist()
    low_values = frame["low"].astype(float).tolist()
    close_values = frame["close"].astype(float).tolist()
    invalid_ohlc_index = first_invalid_ohlc_shape_index(
        open_values,
        high_values,
        low_values,
        close_values,
    )
    if invalid_ohlc_index is not None:
        raise ApplicationError(
            "normalized bars contain invalid OHLC shape for spread calibration",
            symbol=symbol,
            row_index=invalid_ohlc_index,
        )
    volume_values = frame["volume"].astype(float)
    if (volume_values < 0.0).any():
        raise ApplicationError(
            "normalized bars contain negative volume for spread calibration",
            symbol=symbol,
        )
    zero_volume_row_count = int((volume_values == 0.0).sum())
    positive_volume_row_count = int((volume_values > 0.0).sum())
    positive_volume_coverage = positive_volume_row_count / len(frame)
    if positive_volume_coverage < positive_volume_coverage_threshold:
        raise ApplicationError(
            "normalized bars positive-volume coverage is below calibration threshold",
            symbol=symbol,
            zero_volume_row_count=zero_volume_row_count,
            positive_volume_row_count=positive_volume_row_count,
            input_bar_count=len(frame),
            positive_volume_coverage=positive_volume_coverage,
            positive_volume_coverage_threshold=positive_volume_coverage_threshold,
        )
    return _VolumeDiagnostics(
        positive_volume_row_count=positive_volume_row_count,
        zero_volume_row_count=zero_volume_row_count,
    )


def _assert_normalized_frame_matches_manifest(
    *,
    frame: pd.DataFrame,
    artifact: NormalizedBarArtifact,
    normalized_manifest: NormalizedBarManifest,
) -> None:
    if len(frame) != normalized_manifest.row_count:
        raise ApplicationError(
            "normalized bars row_count does not match artifact manifest",
            symbol=artifact.symbol,
            row_count=len(frame),
            manifest_row_count=normalized_manifest.row_count,
        )
    first_timestamp = _timestamp_at(frame, 0)
    last_timestamp = _timestamp_at(frame, len(frame) - 1)
    if first_timestamp != normalized_manifest.start_time_utc:
        raise ApplicationError(
            "normalized bars start_time_utc does not match artifact manifest",
            symbol=artifact.symbol,
            first_timestamp_utc=first_timestamp.isoformat(),
            manifest_start_time_utc=normalized_manifest.start_time_utc.isoformat(),
        )
    if last_timestamp != normalized_manifest.end_time_utc:
        raise ApplicationError(
            "normalized bars end_time_utc does not match artifact manifest",
            symbol=artifact.symbol,
            last_timestamp_utc=last_timestamp.isoformat(),
            manifest_end_time_utc=normalized_manifest.end_time_utc.isoformat(),
        )


def _build_symbol_panel_rows(
    *,
    command: SpreadCalibrationCommand,
    artifact: NormalizedBarArtifact,
    frame: pd.DataFrame,
    volume_diagnostics: _VolumeDiagnostics,
) -> tuple[list[SpreadCalibrationPanelRow], SpreadCalibrationSymbolSummary]:
    rows: list[SpreadCalibrationPanelRow] = []
    invalid_reason_counts: Counter[str] = Counter()
    eligible_window_count = 0
    negative_estimate_count = 0
    timeframe_delta = timedelta(minutes=TIMEFRAME_TO_MINUTES[command.estimator_timeframe])
    true_ranges = _true_ranges(frame=frame, symbol=artifact.symbol)
    volumes = frame["volume"].astype(float)
    first_eligible_row_index = _first_eligible_feature_row_index(command)

    for row_index in range(first_eligible_row_index, len(frame)):
        fill_timestamp_utc = _timestamp_at(frame, row_index)
        if (
            command.calibration_start_utc is not None
            and fill_timestamp_utc < command.calibration_start_utc
        ):
            continue
        if (
            command.calibration_end_utc is not None
            and fill_timestamp_utc > command.calibration_end_utc
        ):
            continue

        eligible_window_count += 1
        window = frame.iloc[row_index - command.edge_window_bars : row_index]
        estimate = estimate_edge_spread(
            window["open"].astype(float).tolist(),
            window["high"].astype(float).tolist(),
            window["low"].astype(float).tolist(),
            window["close"].astype(float).tolist(),
            signed=True,
        )
        if not estimate.valid:
            invalid_reason = estimate.invalid_reason or "non_finite_output"
            invalid_reason_counts[invalid_reason] += 1
            continue

        edge_signed = estimate.full_spread_frac
        if edge_signed is None or not math.isfinite(edge_signed):
            invalid_reason_counts["non_finite_output"] += 1
            continue
        negative_edge = edge_signed < 0.0
        if negative_edge:
            negative_estimate_count += 1
        edge_nonnegative = max(0.0, edge_signed)
        reference_price = float(window["close"].iloc[-1])
        half_spread_price = reference_price * edge_nonnegative / 2.0
        last_window_bar_utc = _timestamp_at(window, len(window) - 1)
        target_observed_at_utc = last_window_bar_utc + timeframe_delta - _OBSERVED_AT_EPSILON
        if target_observed_at_utc >= fill_timestamp_utc:
            target_observed_at_utc = fill_timestamp_utc - _OBSERVED_AT_EPSILON
        session_bucket_id = _resolve_session_bucket_id(
            command.session_buckets,
            fill_timestamp_utc,
        )
        volatility_signal = _volatility_stress_signal(
            true_ranges=true_ranges,
            row_index=row_index,
            short_window=command.volatility_short_window_bars,
            baseline_window=command.volatility_baseline_window_bars,
            volatility_floor_price=float(command.volatility_floor_price),
            symbol=artifact.symbol,
        )
        liquidity_signal, liquidity_observed_volume = _liquidity_stress_signal(
            volumes=volumes,
            row_index=row_index,
            baseline_window=command.volume_baseline_window_bars,
            volume_floor=float(command.volume_floor),
            symbol=artifact.symbol,
        )

        rows.append(
            SpreadCalibrationPanelRow(
                symbol=artifact.symbol,
                estimator_timeframe=command.estimator_timeframe,
                fill_timestamp_utc=fill_timestamp_utc,
                target_observed_at_utc=target_observed_at_utc,
                feature_observed_at_utc=target_observed_at_utc,
                edge_window_start_utc=_timestamp_at(window, 0),
                edge_window_end_utc=target_observed_at_utc,
                edge_window_bars=command.edge_window_bars,
                session_bucket_id=session_bucket_id,
                volatility_stress_signal=float(volatility_signal),
                liquidity_stress_signal=float(liquidity_signal),
                liquidity_observed_volume=liquidity_observed_volume,
                edge_full_spread_frac_signed=edge_signed,
                edge_full_spread_frac_nonnegative=edge_nonnegative,
                reference_price=reference_price,
                half_spread_price=half_spread_price,
                price_basis=command.price_basis,
                conversion_method=(
                    "half_spread_price = last_window_close * "
                    "max(0, signed_edge_full_spread_frac) / 2"
                ),
                source_fingerprint=artifact.manifest.source_fingerprint,
                validator_ruleset_version=command.validator_ruleset_version,
                negative_edge_estimate=negative_edge,
            )
        )

    invalid_window_count = sum(invalid_reason_counts.values())
    summary = SpreadCalibrationSymbolSummary(
        symbol=artifact.symbol,
        estimator_timeframe=command.estimator_timeframe,
        source_fingerprint=artifact.manifest.source_fingerprint,
        input_bar_count=len(frame),
        eligible_window_count=eligible_window_count,
        usable_row_count=len(rows),
        invalid_window_count=invalid_window_count,
        negative_estimate_count=negative_estimate_count,
        invalid_reason_counts=dict(invalid_reason_counts),
        positive_volume_row_count=volume_diagnostics.positive_volume_row_count,
        zero_volume_row_count=volume_diagnostics.zero_volume_row_count,
    )
    return rows, summary


def _first_eligible_feature_row_index(command: SpreadCalibrationCommand) -> int:
    return max(
        command.edge_window_bars,
        command.volatility_short_window_bars + 1,
        command.volatility_baseline_window_bars + 1,
        command.volume_baseline_window_bars,
    )


def _true_ranges(*, frame: pd.DataFrame, symbol: str) -> pd.Series:
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
        raise ApplicationError(
            "spread calibration volatility feature produced a non-finite value",
            symbol=symbol,
        )
    return ranges


def _volatility_stress_signal(
    *,
    true_ranges: pd.Series,
    row_index: int,
    short_window: int,
    baseline_window: int,
    volatility_floor_price: float,
    symbol: str,
) -> float:
    short_values = true_ranges.iloc[row_index - short_window : row_index]
    baseline_values = true_ranges.iloc[row_index - baseline_window : row_index]
    if short_values.isna().any() or baseline_values.isna().any():
        raise ApplicationError(
            "spread calibration volatility feature requires prior close history",
            symbol=symbol,
        )
    short_mean = float(short_values.mean())
    baseline_mean = float(baseline_values.mean())
    if not math.isfinite(short_mean) or not math.isfinite(baseline_mean):
        raise ApplicationError(
            "spread calibration volatility feature produced a non-finite value",
            symbol=symbol,
        )
    if volatility_floor_price <= 0.0 or not math.isfinite(volatility_floor_price):
        raise ApplicationError(
            "spread calibration volatility feature requires a positive volatility floor",
            symbol=symbol,
        )
    return math.log(
        max(short_mean, volatility_floor_price) / max(baseline_mean, volatility_floor_price)
    )


def _liquidity_stress_signal(
    *,
    volumes: pd.Series,
    row_index: int,
    baseline_window: int,
    volume_floor: float,
    symbol: str,
) -> tuple[float, float]:
    observed_volume = float(volumes.iloc[row_index - 1])
    baseline_volume = float(volumes.iloc[row_index - baseline_window : row_index].mean())
    if not math.isfinite(observed_volume) or not math.isfinite(baseline_volume):
        raise ApplicationError(
            "spread calibration liquidity feature produced a non-finite value",
            symbol=symbol,
        )
    if volume_floor <= 0.0 or not math.isfinite(volume_floor):
        raise ApplicationError(
            "spread calibration liquidity feature requires a positive volume floor",
            symbol=symbol,
        )
    return (
        math.log(max(baseline_volume, volume_floor) / max(observed_volume, volume_floor)),
        observed_volume,
    )


def _resolve_session_bucket_id(
    session_buckets: tuple[UtcSessionBucketRule, ...],
    fill_timestamp_utc: datetime,
) -> str:
    matches = [
        bucket.session_bucket_id
        for bucket in session_buckets
        if _session_bucket_matches(
            bucket.weekdays,
            bucket.start_time_utc,
            bucket.end_time_utc,
            fill_timestamp_utc,
        )
    ]
    if len(matches) != 1:
        raise ApplicationError(
            "spread calibration fill timestamp must map to exactly one UTC session bucket",
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


def _timestamp_at(frame: pd.DataFrame, row_index: int) -> datetime:
    return pd.Timestamp(frame["ts_event_utc"].iloc[row_index]).to_pydatetime()


def _compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_path(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


def _calibration_id(
    *,
    command: SpreadCalibrationCommand,
    source_fingerprints: dict[str, str],
    row_count: int,
) -> str:
    content_hash = stable_hash(
        {
            "dataset_id": command.materialized_dataset.dataset.dataset_id,
            "estimator_timeframe": command.estimator_timeframe,
            "edge_window_bars": command.edge_window_bars,
            "calibration_start_utc": command.calibration_start_utc,
            "calibration_end_utc": command.calibration_end_utc,
            "validator_ruleset_version": command.validator_ruleset_version,
            "positive_volume_coverage_threshold": command.positive_volume_coverage_threshold,
            "volatility_short_window_bars": command.volatility_short_window_bars,
            "volatility_baseline_window_bars": command.volatility_baseline_window_bars,
            "volatility_floor_price": command.volatility_floor_price,
            "volume_baseline_window_bars": command.volume_baseline_window_bars,
            "volume_floor": command.volume_floor,
            "session_buckets": [
                bucket.model_dump(mode="json") for bucket in command.session_buckets
            ],
            "price_basis": command.price_basis,
            "source_fingerprints": source_fingerprints,
            "row_count": row_count,
        }
    )
    return f"spread-calibration-{content_hash[:12]}"


__all__ = ["build_spread_calibration_panel"]
