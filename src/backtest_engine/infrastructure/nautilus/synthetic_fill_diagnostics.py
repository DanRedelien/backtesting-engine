"""Build auditable synthetic-fill diagnostics from persisted runtime reports."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Mapping, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.infrastructure.nautilus.run_spec_compiler import NautilusRunSpec


SYNTHETIC_FILL_DIAGNOSTICS_SCHEMA_VERSION = "synthetic_fill_diagnostics.v1"
SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY = "synthetic_fill_diagnostics"
SYNTHETIC_FILL_DIAGNOSTICS_FILENAME = "synthetic_fill_diagnostics.json"
_EPSILON_PRICE_TOLERANCE = Decimal("1e-12")
_OUTSIDE_EXAMPLE_LIMIT = 10
_FILL_INSTRUMENT_COLUMNS = ("instrument_id", "instrument")
_FILL_ORDER_TYPE_COLUMNS = ("order_type", "type")
_FILL_PRICE_COLUMNS = ("last_px", "avg_px", "price", "fill_price")
_FILL_TIMESTAMP_COLUMNS = ("ts_event", "ts_filled", "timestamp", "ts_init")
_BAR_REQUIRED_COLUMNS = ("ts_event_utc", "open", "high", "low", "close")


class ClassificationRate(BaseModel):
    """A rate with its explicit numerator and denominator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None


class SyntheticFillDiagnostics(BaseModel):
    """Versioned JSON artifact for synthetic fill auditability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: NonEmptyStr = SYNTHETIC_FILL_DIAGNOSTICS_SCHEMA_VERSION
    run_id: NonEmptyStr
    generated_at_utc: datetime
    policy_mode: Literal["no_policy", "static_policy", "dynamic_spread_policy"]
    diagnostics_status: Literal["not_applicable", "available", "partial", "unavailable"]
    reason: str | None
    source_report_artifacts: dict[str, JsonValue]
    missing_required_columns: tuple[str, ...]
    row_count_total: int = Field(ge=0)
    row_count_classified: int = Field(ge=0)
    classification_counts: dict[str, dict[str, int]]
    classification_rates: dict[str, ClassificationRate]
    outside_ohlc_examples_sample: tuple[dict[str, JsonValue], ...]
    feature_coverage_summary: dict[str, JsonValue]


def build_synthetic_fill_diagnostics(
    *,
    compiled_spec: NautilusRunSpec,
    fills_report: pd.DataFrame,
    orders_report: pd.DataFrame,
    report_locations: Mapping[str, str],
    generated_at_utc: datetime | None = None,
) -> SyntheticFillDiagnostics:
    """Build the stable diagnostics payload from explicit reports and run DTOs."""

    del orders_report
    generated_at = generated_at_utc or datetime.now(UTC)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    else:
        generated_at = generated_at.astimezone(UTC)

    policy_context = _policy_context(compiled_spec)
    source_report_artifacts = _source_report_artifacts(compiled_spec, report_locations)
    missing_fill_columns = _missing_fill_columns(fills_report)
    row_count_total = int(len(fills_report))

    if policy_context.policy_mode == "no_policy":
        return _not_applicable_payload(
            compiled_spec=compiled_spec,
            generated_at_utc=generated_at,
            policy_mode=policy_context.policy_mode,
            reason="no_execution_policy",
            source_report_artifacts=source_report_artifacts,
            row_count_total=row_count_total,
        )
    if policy_context.policy_mode == "static_policy":
        return _not_applicable_payload(
            compiled_spec=compiled_spec,
            generated_at_utc=generated_at,
            policy_mode=policy_context.policy_mode,
            reason="no_dynamic_spread_profile",
            source_report_artifacts=source_report_artifacts,
            row_count_total=row_count_total,
        )

    feature_coverage = _feature_coverage_summary(
        dynamic_instrument_ids=policy_context.dynamic_instrument_ids,
        dynamic_feature_refs=policy_context.dynamic_feature_refs,
    )
    if _classification_blocked(missing_fill_columns):
        return SyntheticFillDiagnostics(
            run_id=compiled_spec.run_id,
            generated_at_utc=generated_at,
            policy_mode=policy_context.policy_mode,
            diagnostics_status="unavailable",
            reason="missing_required_fill_columns",
            source_report_artifacts=source_report_artifacts,
            missing_required_columns=tuple(missing_fill_columns),
            row_count_total=row_count_total,
            row_count_classified=0,
            classification_counts=_empty_classification_counts(),
            classification_rates=_empty_classification_rates(0),
            outside_ohlc_examples_sample=(),
            feature_coverage_summary=feature_coverage,
        )

    bars_by_instrument_id, missing_bar_columns = _load_bar_reports(compiled_spec)
    records = _classify_fills(
        fills_report=fills_report,
        dynamic_instrument_ids=policy_context.dynamic_instrument_ids,
        bars_by_instrument_id=bars_by_instrument_id,
        tick_sizes_by_instrument_id=policy_context.tick_sizes_by_instrument_id,
        feature_fill_timestamps_by_instrument_id=_feature_timestamps_by_instrument_id(
            feature_coverage,
        ),
    )
    counts = _classification_counts(records)
    row_count_classified = sum(counts["primary"].values()) - counts["primary"].get(
        "unclassified",
        0,
    )
    missing_required_columns = tuple(sorted(set(missing_fill_columns + missing_bar_columns)))
    feature_coverage = _attach_feature_fill_counts(feature_coverage, records)
    status, reason = _dynamic_status(
        missing_required_columns=missing_required_columns,
        counts=counts,
        feature_coverage=feature_coverage,
        row_count_total=row_count_total,
        row_count_classified=row_count_classified,
    )

    return SyntheticFillDiagnostics(
        run_id=compiled_spec.run_id,
        generated_at_utc=generated_at,
        policy_mode=policy_context.policy_mode,
        diagnostics_status=status,
        reason=reason,
        source_report_artifacts=source_report_artifacts,
        missing_required_columns=missing_required_columns,
        row_count_total=row_count_total,
        row_count_classified=row_count_classified,
        classification_counts=counts,
        classification_rates=_classification_rates(
            counts,
            row_count_total=row_count_total,
            row_count_classified=row_count_classified,
        ),
        outside_ohlc_examples_sample=tuple(
            record.outside_ohlc_example
            for record in records
            if record.outside_ohlc_example is not None
        )[:_OUTSIDE_EXAMPLE_LIMIT],
        feature_coverage_summary=feature_coverage,
    )


class _PolicyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_mode: Literal["no_policy", "static_policy", "dynamic_spread_policy"]
    dynamic_instrument_ids: frozenset[str] = frozenset()
    dynamic_feature_refs: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    tick_sizes_by_instrument_id: dict[str, Decimal] = Field(default_factory=dict)


class _FillClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str | None
    fill_timestamp_utc: datetime | None
    primary_class: str
    flags: tuple[str, ...]
    outside_ohlc_example: dict[str, JsonValue] | None = None


def _not_applicable_payload(
    *,
    compiled_spec: NautilusRunSpec,
    generated_at_utc: datetime,
    policy_mode: Literal["no_policy", "static_policy", "dynamic_spread_policy"],
    reason: str,
    source_report_artifacts: dict[str, JsonValue],
    row_count_total: int,
) -> SyntheticFillDiagnostics:
    return SyntheticFillDiagnostics(
        run_id=compiled_spec.run_id,
        generated_at_utc=generated_at_utc,
        policy_mode=policy_mode,
        diagnostics_status="not_applicable",
        reason=reason,
        source_report_artifacts=source_report_artifacts,
        missing_required_columns=(),
        row_count_total=row_count_total,
        row_count_classified=0,
        classification_counts=_empty_classification_counts(),
        classification_rates=_empty_classification_rates(0),
        outside_ohlc_examples_sample=(),
        feature_coverage_summary={},
    )


def _policy_context(compiled_spec: NautilusRunSpec) -> _PolicyContext:
    has_policy_model = False
    dynamic_instrument_ids: set[str] = set()
    dynamic_feature_refs: dict[str, dict[str, JsonValue]] = {}
    tick_sizes_by_instrument_id: dict[str, Decimal] = {}
    for venue in compiled_spec.venues:
        model = venue.fill_model or venue.fee_model
        if model is None:
            continue
        has_policy_model = True
        instrument_profiles = cast(
            dict[str, Any],
            model.config.get("instrument_profiles", {}),
        )
        for instrument_id, payload in instrument_profiles.items():
            metadata = cast(dict[str, Any], payload.get("metadata", {}))
            tick_size = _to_decimal(metadata.get("tick_size"))
            if tick_size is not None:
                tick_sizes_by_instrument_id[instrument_id] = tick_size
            profile = cast(dict[str, Any], payload.get("profile", {}))
            spread_model = cast(dict[str, Any], profile.get("spread_model", {}))
            if spread_model.get("model") == "log_linear_dynamic_half_spread":
                dynamic_instrument_ids.add(instrument_id)
        dynamic_features = cast(dict[str, dict[str, JsonValue]], model.config.get("dynamic_spread_features", {}))
        dynamic_feature_refs.update(dynamic_features)

    if dynamic_instrument_ids:
        return _PolicyContext(
            policy_mode="dynamic_spread_policy",
            dynamic_instrument_ids=frozenset(dynamic_instrument_ids),
            dynamic_feature_refs=dynamic_feature_refs,
            tick_sizes_by_instrument_id=tick_sizes_by_instrument_id,
        )
    if has_policy_model:
        return _PolicyContext(
            policy_mode="static_policy",
            tick_sizes_by_instrument_id=tick_sizes_by_instrument_id,
        )
    return _PolicyContext(policy_mode="no_policy")


def _source_report_artifacts(
    compiled_spec: NautilusRunSpec,
    report_locations: Mapping[str, str],
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = dict(sorted(report_locations.items()))
    normalized_bar_data_paths = {
        data.instrument_id: data.normalized_bar_data_path.as_posix()
        for data in compiled_spec.data
        if data.normalized_bar_data_path is not None
    }
    if normalized_bar_data_paths:
        payload["normalized_bar_data"] = cast(JsonValue, normalized_bar_data_paths)
    return payload


def _missing_fill_columns(fills_report: pd.DataFrame) -> list[str]:
    missing: list[str] = []
    if _first_present_column(fills_report, _FILL_INSTRUMENT_COLUMNS) is None:
        missing.append("fills_report.instrument_id")
    if _first_present_column(fills_report, _FILL_ORDER_TYPE_COLUMNS) is None:
        missing.append("fills_report.order_type")
    if _first_present_column(fills_report, _FILL_PRICE_COLUMNS) is None:
        missing.append("fills_report.fill_price")
    if _first_present_column(fills_report, _FILL_TIMESTAMP_COLUMNS) is None:
        missing.append("fills_report.fill_timestamp_utc")
    return missing


def _classification_blocked(missing_columns: list[str]) -> bool:
    return any(
        column_name in {"fills_report.instrument_id", "fills_report.order_type"}
        for column_name in missing_columns
    )


def _load_bar_reports(compiled_spec: NautilusRunSpec) -> tuple[dict[str, pd.DataFrame], list[str]]:
    bars_by_instrument_id: dict[str, pd.DataFrame] = {}
    missing_columns: list[str] = []
    for data in compiled_spec.data:
        if data.normalized_bar_data_path is None:
            missing_columns.append(f"normalized_bar_data.{data.instrument_id}.path")
            continue
        try:
            frame = pd.read_parquet(data.normalized_bar_data_path)
        except Exception:
            missing_columns.append(f"normalized_bar_data.{data.instrument_id}.readable")
            continue
        frame_missing = [
            column_name for column_name in _BAR_REQUIRED_COLUMNS if column_name not in frame.columns
        ]
        if frame_missing:
            missing_columns.extend(
                f"normalized_bar_data.{data.instrument_id}.{column_name}"
                for column_name in frame_missing
            )
            continue
        working = frame.loc[:, list(_BAR_REQUIRED_COLUMNS)].copy()
        working["ts_event_utc"] = pd.to_datetime(working["ts_event_utc"], utc=True)
        bars_by_instrument_id[data.instrument_id] = working
    return bars_by_instrument_id, missing_columns


def _classify_fills(
    *,
    fills_report: pd.DataFrame,
    dynamic_instrument_ids: frozenset[str],
    bars_by_instrument_id: Mapping[str, pd.DataFrame],
    tick_sizes_by_instrument_id: Mapping[str, Decimal],
    feature_fill_timestamps_by_instrument_id: Mapping[str, frozenset[datetime]],
) -> tuple[_FillClassification, ...]:
    instrument_column = _first_present_column(fills_report, _FILL_INSTRUMENT_COLUMNS)
    order_type_column = _first_present_column(fills_report, _FILL_ORDER_TYPE_COLUMNS)
    price_column = _first_present_column(fills_report, _FILL_PRICE_COLUMNS)
    timestamp_column = _first_present_column(fills_report, _FILL_TIMESTAMP_COLUMNS)
    records: list[_FillClassification] = []
    for _, row in fills_report.iterrows():
        instrument_id = _string_or_none(row.get(instrument_column)) if instrument_column else None
        order_type = _normalize_order_type(row.get(order_type_column)) if order_type_column else None
        fill_price = _to_decimal(row.get(price_column)) if price_column else None
        fill_timestamp_utc = _to_utc_datetime(row.get(timestamp_column)) if timestamp_column else None
        primary_class = _primary_class(instrument_id, order_type, dynamic_instrument_ids)
        flags: list[str] = []
        outside_example: dict[str, JsonValue] | None = None
        if primary_class == "unclassified":
            records.append(
                _FillClassification(
                    instrument_id=instrument_id,
                    fill_timestamp_utc=fill_timestamp_utc,
                    primary_class=primary_class,
                    flags=(),
                ),
            )
            continue
        if primary_class == "dynamic_spread_fill":
            feature_timestamps = feature_fill_timestamps_by_instrument_id.get(
                instrument_id or "",
                frozenset(),
            )
            if fill_timestamp_utc is not None and fill_timestamp_utc in feature_timestamps:
                flags.append("dynamic_feature_covered")
            else:
                flags.append("dynamic_feature_missing")
        ohlc_result = _outside_ohlc_result(
            instrument_id=instrument_id,
            fill_timestamp_utc=fill_timestamp_utc,
            fill_price=fill_price,
            bars_by_instrument_id=bars_by_instrument_id,
            tick_sizes_by_instrument_id=tick_sizes_by_instrument_id,
        )
        if ohlc_result == "missing":
            flags.append("missing_ohlc")
        elif ohlc_result is not None:
            flags.append("outside_ohlc")
            outside_example = ohlc_result
        records.append(
            _FillClassification(
                instrument_id=instrument_id,
                fill_timestamp_utc=fill_timestamp_utc,
                primary_class=primary_class,
                flags=tuple(sorted(flags)),
                outside_ohlc_example=outside_example,
            ),
        )
    return tuple(records)


def _primary_class(
    instrument_id: str | None,
    order_type: str | None,
    dynamic_instrument_ids: frozenset[str],
) -> str:
    if instrument_id is None or order_type is None:
        return "unclassified"
    if instrument_id in dynamic_instrument_ids:
        if order_type == "market":
            return "dynamic_spread_fill"
        return "default_path_fill"
    return "static_policy_fill"


def _outside_ohlc_result(
    *,
    instrument_id: str | None,
    fill_timestamp_utc: datetime | None,
    fill_price: Decimal | None,
    bars_by_instrument_id: Mapping[str, pd.DataFrame],
    tick_sizes_by_instrument_id: Mapping[str, Decimal],
) -> Literal["missing"] | dict[str, JsonValue] | None:
    if instrument_id is None or fill_timestamp_utc is None or fill_price is None:
        return "missing"
    bars = bars_by_instrument_id.get(instrument_id)
    if bars is None:
        return "missing"
    matches = bars.loc[bars["ts_event_utc"] == pd.Timestamp(fill_timestamp_utc)]
    if matches.empty:
        return "missing"
    bar = matches.iloc[0]
    low = _to_decimal(bar["low"])
    high = _to_decimal(bar["high"])
    if low is None or high is None:
        return "missing"
    tolerance = tick_sizes_by_instrument_id.get(instrument_id, _EPSILON_PRICE_TOLERANCE)
    tolerance_source = "tick_size" if instrument_id in tick_sizes_by_instrument_id else "epsilon"
    if low - tolerance <= fill_price <= high + tolerance:
        return None
    return {
        "instrument_id": instrument_id,
        "fill_timestamp_utc": fill_timestamp_utc.isoformat(),
        "fill_price": str(fill_price),
        "bar_low": str(low),
        "bar_high": str(high),
        "tolerance_price": str(tolerance),
        "tolerance_source": tolerance_source,
    }


def _feature_coverage_summary(
    *,
    dynamic_instrument_ids: frozenset[str],
    dynamic_feature_refs: Mapping[str, Mapping[str, JsonValue]],
) -> dict[str, JsonValue]:
    summary: dict[str, JsonValue] = {}
    for instrument_id in sorted(dynamic_instrument_ids):
        ref = dynamic_feature_refs.get(instrument_id)
        if ref is None:
            summary[instrument_id] = {
                "feature_artifact_status": "missing",
                "row_count": None,
                "first_fill_timestamp_utc": None,
                "last_fill_timestamp_utc": None,
                "covered_dynamic_fill_count": None,
                "missing_dynamic_fill_count": None,
            }
            continue
        feature_table_path = Path(str(ref.get("feature_table_path", "")))
        if not feature_table_path.is_file():
            summary[instrument_id] = {
                "feature_artifact_status": "unavailable",
                "feature_table_path": feature_table_path.as_posix(),
                "row_count": None,
                "first_fill_timestamp_utc": None,
                "last_fill_timestamp_utc": None,
                "covered_dynamic_fill_count": None,
                "missing_dynamic_fill_count": None,
            }
            continue
        try:
            frame = pd.read_parquet(feature_table_path, columns=["fill_timestamp_utc"])
            timestamps = pd.to_datetime(frame["fill_timestamp_utc"], utc=True)
        except Exception:
            summary[instrument_id] = {
                "feature_artifact_status": "unavailable",
                "feature_table_path": feature_table_path.as_posix(),
                "row_count": None,
                "first_fill_timestamp_utc": None,
                "last_fill_timestamp_utc": None,
                "covered_dynamic_fill_count": None,
                "missing_dynamic_fill_count": None,
            }
            continue
        summary[instrument_id] = {
            "feature_artifact_status": "available",
            "feature_table_path": feature_table_path.as_posix(),
            "row_count": int(len(timestamps)),
            "first_fill_timestamp_utc": (
                timestamps.iloc[0].isoformat() if len(timestamps) else None
            ),
            "last_fill_timestamp_utc": (
                timestamps.iloc[-1].isoformat() if len(timestamps) else None
            ),
            "feature_fill_timestamps_utc": [
                timestamp.to_pydatetime().isoformat() for timestamp in timestamps
            ],
            "covered_dynamic_fill_count": 0,
            "missing_dynamic_fill_count": 0,
        }
    return summary


def _feature_timestamps_by_instrument_id(
    feature_coverage: Mapping[str, JsonValue],
) -> dict[str, frozenset[datetime]]:
    timestamps_by_instrument_id: dict[str, frozenset[datetime]] = {}
    for instrument_id, payload in feature_coverage.items():
        if not isinstance(payload, dict):
            continue
        raw_timestamps = payload.get("feature_fill_timestamps_utc")
        if not isinstance(raw_timestamps, list):
            continue
        timestamps_by_instrument_id[instrument_id] = frozenset(
            timestamp
            for value in raw_timestamps
            if (timestamp := _to_utc_datetime(value)) is not None
        )
    return timestamps_by_instrument_id


def _attach_feature_fill_counts(
    feature_coverage: dict[str, JsonValue],
    records: tuple[_FillClassification, ...],
) -> dict[str, JsonValue]:
    updated = dict(feature_coverage)
    for instrument_id, payload in list(updated.items()):
        if not isinstance(payload, dict):
            continue
        dynamic_records = [
            record
            for record in records
            if record.instrument_id == instrument_id and record.primary_class == "dynamic_spread_fill"
        ]
        payload = dict(payload)
        payload["covered_dynamic_fill_count"] = sum(
            "dynamic_feature_covered" in record.flags for record in dynamic_records
        )
        payload["missing_dynamic_fill_count"] = sum(
            "dynamic_feature_missing" in record.flags for record in dynamic_records
        )
        payload.pop("feature_fill_timestamps_utc", None)
        updated[instrument_id] = cast(JsonValue, payload)
    return updated


def _classification_counts(records: tuple[_FillClassification, ...]) -> dict[str, dict[str, int]]:
    primary_counts = {
        "dynamic_spread_fill": 0,
        "static_policy_fill": 0,
        "default_path_fill": 0,
        "unclassified": 0,
    }
    flag_counts = {
        "outside_ohlc": 0,
        "missing_ohlc": 0,
        "dynamic_feature_covered": 0,
        "dynamic_feature_missing": 0,
    }
    for record in records:
        primary_counts[record.primary_class] = primary_counts.get(record.primary_class, 0) + 1
        for flag in record.flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    return {"primary": primary_counts, "flags": flag_counts}


def _classification_rates(
    counts: Mapping[str, Mapping[str, int]],
    *,
    row_count_total: int,
    row_count_classified: int,
) -> dict[str, ClassificationRate]:
    primary = counts.get("primary", {})
    flags = counts.get("flags", {})
    dynamic_fill_count = primary.get("dynamic_spread_fill", 0)
    rates: dict[str, ClassificationRate] = {}
    for name, count in primary.items():
        rates[name] = _rate(count, row_count_total)
    flag_denominators = {
        "outside_ohlc": row_count_classified,
        "missing_ohlc": row_count_classified,
        "dynamic_feature_covered": dynamic_fill_count,
        "dynamic_feature_missing": dynamic_fill_count,
    }
    for name, count in flags.items():
        rates[name] = _rate(count, flag_denominators.get(name, row_count_classified))
    return rates


def _empty_classification_counts() -> dict[str, dict[str, int]]:
    return _classification_counts(())


def _empty_classification_rates(denominator: int) -> dict[str, ClassificationRate]:
    return {
        name: _rate(0, denominator)
        for name in (
            "dynamic_spread_fill",
            "static_policy_fill",
            "default_path_fill",
            "unclassified",
            "outside_ohlc",
            "missing_ohlc",
            "dynamic_feature_covered",
            "dynamic_feature_missing",
        )
    }


def _rate(numerator: int, denominator: int) -> ClassificationRate:
    return ClassificationRate(
        numerator=numerator,
        denominator=denominator,
        rate=(float(numerator / denominator) if denominator else None),
    )


def _dynamic_status(
    *,
    missing_required_columns: tuple[str, ...],
    counts: Mapping[str, Mapping[str, int]],
    feature_coverage: Mapping[str, JsonValue],
    row_count_total: int,
    row_count_classified: int,
) -> tuple[
    Literal["available", "partial", "unavailable"],
    str | None,
]:
    primary_counts = counts.get("primary", {})
    flag_counts = counts.get("flags", {})
    dynamic_fill_count = primary_counts.get("dynamic_spread_fill", 0)
    if row_count_total == 0:
        return "unavailable", "no_fill_rows"
    if row_count_classified == 0:
        return "unavailable", "no_classifiable_fill_rows"
    if (
        dynamic_fill_count > 0
        and flag_counts.get("dynamic_feature_missing", 0) >= dynamic_fill_count
    ):
        return "unavailable", "all_dynamic_fills_missing_feature_coverage"
    if dynamic_fill_count > 0 and flag_counts.get("missing_ohlc", 0) >= dynamic_fill_count:
        return "unavailable", "all_dynamic_fills_missing_ohlc"
    if missing_required_columns:
        return "partial", "missing_optional_ohlc_or_price_inputs"
    if (
        primary_counts.get("unclassified", 0) > 0
        or flag_counts.get("missing_ohlc", 0) > 0
        or flag_counts.get("dynamic_feature_missing", 0) > 0
        or _feature_artifact_status_incomplete(feature_coverage)
    ):
        return "partial", "row_level_diagnostics_inputs_missing"
    return "available", None


def _feature_artifact_status_incomplete(feature_coverage: Mapping[str, JsonValue]) -> bool:
    for payload in feature_coverage.values():
        if not isinstance(payload, dict):
            return True
        if payload.get("feature_artifact_status") != "available":
            return True
    return False


def _first_present_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _string_or_none(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_order_type(value: object) -> str | None:
    text = _string_or_none(value)
    if text is None:
        return None
    normalized = text.strip().lower().replace(" ", "_")
    if normalized in {"1", "market", "ordertype.market"}:
        return "market"
    if normalized in {"stop", "stop_market", "ordertype.stop_market"}:
        return "stop"
    return normalized


def _to_decimal(value: object) -> Decimal | None:
    if _is_missing(value):
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text.split()[0])
    except (InvalidOperation, ValueError):
        return None


def _to_utc_datetime(value: object) -> datetime | None:
    if _is_missing(value):
        return None
    try:
        if isinstance(value, int):
            timestamp = pd.Timestamp(value, unit="ns", tz=UTC)
        else:
            timestamp = pd.Timestamp(cast(Any, value))
    except Exception:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(cast(Any, value))
    except Exception:
        return False
    return result if isinstance(result, bool) else False


__all__ = [
    "SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY",
    "SYNTHETIC_FILL_DIAGNOSTICS_FILENAME",
    "SYNTHETIC_FILL_DIAGNOSTICS_SCHEMA_VERSION",
    "SyntheticFillDiagnostics",
    "build_synthetic_fill_diagnostics",
]
