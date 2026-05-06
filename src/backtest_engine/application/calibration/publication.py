"""Fit and publish offline EDGE spread calibration bundles."""

from __future__ import annotations

import json
import math
from decimal import Decimal

import yaml

from backtest_engine.application.calibration.contracts import (
    PublishedCalibrationSymbol,
    SpreadCalibrationPanelRow,
    SpreadCalibrationPublicationCommand,
    SpreadCalibrationPublicationResult,
    SpreadCalibrationSymbolSummary,
)
from backtest_engine.application.calibration.publication_artifacts import (
    publication_id as _publication_id,
    write_panel_artifact as _write_panel_artifact,
)
from backtest_engine.application.calibration.diagnostics import (
    build_calibration_diagnostics as _build_calibration_diagnostics,
)
from backtest_engine.application.calibration.fitting import (
    CalibrationFitParameters as _FitParameters,
    PreparedCalibrationRow as _PreparedCalibrationRow,
    fit_non_negative_log_linear as _fit_non_negative_log_linear,
    predict_log as _predict_log,
    project_fit_for_publication as _fit_for_publication,
)
from backtest_engine.application.calibration.publication_helpers import (
    canonical_symbol as _canonical_symbol,
    decimal_string as _decimal_string,
    timeframe_delta as _timeframe_delta,
)
from backtest_engine.application.calibration.publication_payloads import (
    build_execution_costs_payload as _build_execution_costs_payload,
    validate_published_profiles as _validate_published_profiles,
)
from backtest_engine.application.calibration.publication_reporting import (
    calibration_report as _calibration_report,
)
from backtest_engine.application.calibration.publication_types import (
    PreparedPublication as _PreparedPublication,
    SplitRows as _SplitRows,
    SymbolBounds as _SymbolBounds,
)
from backtest_engine.config.execution_costs import (
    execution_costs_config_hash,
    load_execution_costs,
)
from backtest_engine.core.errors import ApplicationError
from backtest_engine.domain.execution.instrument_metadata import ExecutionAssetClass
from backtest_engine.infrastructure.nautilus.symbol_map import (
    SymbolMapping,
    load_symbol_map,
)


def publish_spread_calibration(
    command: SpreadCalibrationPublicationCommand,
) -> SpreadCalibrationPublicationResult:
    """Fit Phase-2 dynamic spread parameters and write generated artifacts.

    The publisher consumes an existing Phase-1 panel. It does not run EDGE and
    does not read any strategy or portfolio performance data.
    """

    result = command.calibration_result
    split = _split_panel_rows(command)
    prepared = _prepare_publication(command)
    publication_identifier = _publication_id(command)
    _validate_sample_counts(command, split)

    train_rows = _prepare_rows(
        split.train,
        prepared.min_half_spread_by_symbol,
        prepared.canonical_symbol_by_input_symbol,
    )
    holdout_rows = _prepare_rows(
        split.holdout,
        prepared.min_half_spread_by_symbol,
        prepared.canonical_symbol_by_input_symbol,
    )
    purged_rows = _prepare_rows(
        split.purged,
        prepared.min_half_spread_by_symbol,
        prepared.canonical_symbol_by_input_symbol,
    )
    liquidity_enabled, liquidity_reason = _resolve_liquidity_fit_policy(command)
    session_bucket_ids = tuple(bucket.session_bucket_id for bucket in result.session_buckets)
    fitted_fit = _fit_non_negative_log_linear(
        rows=train_rows,
        session_bucket_ids=session_bucket_ids,
        log_floor_by_symbol={
            symbol: math.log(floor) for symbol, floor in prepared.min_half_spread_by_symbol.items()
        },
        liquidity_enabled=liquidity_enabled,
        fit_tolerance=command.fit_tolerance,
        max_fit_iterations=command.max_fit_iterations,
    )
    if not fitted_fit.converged:
        raise ApplicationError(
            "spread calibration fit did not converge",
            calibration_id=result.calibration_id,
            max_fit_iterations=command.max_fit_iterations,
            fit_tolerance=command.fit_tolerance,
        )
    published_fit, dynamic_projection_reason = _fit_for_publication(
        command=command,
        fitted_fit=fitted_fit,
        train_rows=train_rows,
        session_bucket_ids=session_bucket_ids,
        log_floor_by_symbol={
            symbol: math.log(floor) for symbol, floor in prepared.min_half_spread_by_symbol.items()
        },
    )

    bounds_by_symbol = _symbol_bounds(
        command=command,
        fit=published_fit,
        train_rows=train_rows,
        min_half_spread_by_symbol=prepared.min_half_spread_by_symbol,
    )
    train_metrics = _metrics_by_symbol(train_rows, published_fit, bounds_by_symbol)
    holdout_metrics = _metrics_by_symbol(holdout_rows, published_fit, bounds_by_symbol)
    published_symbols = _published_symbols(
        symbols=tuple(sorted(prepared.mappings_by_symbol)),
        fit=published_fit,
        bounds_by_symbol=bounds_by_symbol,
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
    )

    output_dir = command.output_root / result.calibration_id / publication_identifier
    output_dir.mkdir(parents=True, exist_ok=True)
    execution_costs_path = output_dir / "execution_costs.yaml"
    report_path = output_dir / "calibration_report.json"
    panel_path = output_dir / "calibration_panel.parquet"

    config_payload = _build_execution_costs_payload(
        command=command,
        fit=published_fit,
        bounds_by_symbol=bounds_by_symbol,
        mappings_by_symbol=prepared.mappings_by_symbol,
        train_rows=train_rows,
    )
    execution_costs_path.write_text(
        yaml.safe_dump(config_payload, sort_keys=False),
        encoding="utf-8",
    )
    loaded_config = load_execution_costs(execution_costs_path)
    config_hash = execution_costs_config_hash(loaded_config)
    _validate_published_profiles(
        command=command,
        loaded_config_path=execution_costs_path,
        mappings=tuple(prepared.mappings_by_symbol.values()),
    )

    _write_panel_artifact(panel_path, result.panel_rows, split)
    diagnostics_publication = _build_calibration_diagnostics(
        command=command,
        split=split,
        prepared=prepared,
        fit=published_fit,
        bounds_by_symbol=bounds_by_symbol,
        output_dir=output_dir,
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        purged_rows=purged_rows,
    )
    report = _calibration_report(
        command=command,
        split=split,
        liquidity_enabled=liquidity_enabled,
        liquidity_reason=liquidity_reason,
        fitted_fit=fitted_fit,
        published_fit=published_fit,
        dynamic_projection_reason=dynamic_projection_reason,
        prepared=prepared,
        bounds_by_symbol=bounds_by_symbol,
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
        published_symbols=published_symbols,
        execution_costs_path=execution_costs_path,
        panel_path=panel_path,
        profile_id=loaded_config.profile_id,
        config_hash=config_hash,
        diagnostics=diagnostics_publication.diagnostics,
        diagnostic_artifacts=diagnostics_publication.diagnostic_artifacts,
        flags=diagnostics_publication.flags,
    )
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    return SpreadCalibrationPublicationResult(
        calibration_id=result.calibration_id,
        profile_id=loaded_config.profile_id,
        estimator_timeframe=result.estimator_timeframe,
        target_timeframe=command.target_timeframe,
        output_dir=output_dir,
        execution_costs_path=execution_costs_path,
        calibration_report_path=report_path,
        calibration_panel_path=panel_path,
        diagnostic_artifact_paths=diagnostics_publication.artifact_paths,
        execution_costs_config_hash=config_hash,
        published_symbols=published_symbols,
        train_row_count=len(split.train),
        holdout_row_count=len(split.holdout),
        purged_row_count=len(split.purged),
    )


def _split_panel_rows(command: SpreadCalibrationPublicationCommand) -> _SplitRows:
    result = command.calibration_result
    rows = tuple(
        sorted(
            result.panel_rows,
            key=lambda row: (row.fill_timestamp_utc, row.symbol),
        )
    )
    fill_timestamps = tuple(sorted({row.fill_timestamp_utc for row in rows}))
    if len(fill_timestamps) < 2:
        raise ApplicationError(
            "spread calibration publication requires at least two fill timestamps",
            calibration_id=result.calibration_id,
        )

    split_index = int(len(fill_timestamps) * command.train_fraction)
    split_index = max(1, min(split_index, len(fill_timestamps) - 1))
    split_timestamp = fill_timestamps[split_index - 1]
    purged_gap = _timeframe_delta(result.estimator_timeframe) * result.edge_window_bars
    holdout_start = split_timestamp + purged_gap

    train = tuple(row for row in rows if row.fill_timestamp_utc <= split_timestamp)
    holdout = tuple(row for row in rows if row.fill_timestamp_utc > holdout_start)
    purged = tuple(row for row in rows if row not in train and row not in holdout)
    if not train or not holdout:
        raise ApplicationError(
            "spread calibration publication split produced an empty train or holdout sample",
            calibration_id=result.calibration_id,
            train_row_count=len(train),
            holdout_row_count=len(holdout),
            purged_row_count=len(purged),
            train_fraction=command.train_fraction,
            purged_gap_seconds=purged_gap.total_seconds(),
        )
    return _SplitRows(
        train=train,
        holdout=holdout,
        purged=purged,
        split_timestamp_utc=split_timestamp,
        holdout_start_utc=holdout_start,
        purged_gap=purged_gap,
    )


def _prepare_publication(
    command: SpreadCalibrationPublicationCommand,
) -> _PreparedPublication:
    _validate_bundle_symbol_sets(command)
    symbol_map = load_symbol_map(command.symbol_map_path)
    symbols = tuple(sorted({row.symbol for row in command.calibration_result.panel_rows}))
    mappings_by_symbol: dict[str, SymbolMapping] = {}
    tick_size_by_symbol: dict[str, Decimal] = {}
    min_half_spread_by_symbol: dict[str, float] = {}
    canonical_symbol_by_input_symbol: dict[str, str] = {}
    input_symbol_by_canonical_symbol: dict[str, str] = {}
    asset_classes: set[ExecutionAssetClass] = set()
    for symbol in symbols:
        try:
            mapping = symbol_map.resolve(symbol)
        except KeyError as exc:
            raise ApplicationError(
                "spread calibration publication requires symbol-map metadata",
                symbol=symbol,
            ) from exc
        if mapping.asset_class is None:
            raise ApplicationError(
                "spread calibration publication requires asset_class metadata",
                symbol=symbol,
            )
        asset_class = ExecutionAssetClass(mapping.asset_class)
        asset_classes.add(asset_class)
        canonical_symbol = mapping.mt5_symbol
        normalized_input_symbol = _canonical_symbol(symbol)
        normalized_canonical_symbol = _canonical_symbol(canonical_symbol)
        existing_input_symbol = input_symbol_by_canonical_symbol.get(normalized_canonical_symbol)
        if existing_input_symbol is not None and existing_input_symbol != normalized_input_symbol:
            raise ApplicationError(
                "spread calibration publication resolves multiple input symbols "
                "to one canonical symbol",
                canonical_symbol=canonical_symbol,
                input_symbols=",".join(sorted((existing_input_symbol, normalized_input_symbol))),
            )
        input_symbol_by_canonical_symbol[normalized_canonical_symbol] = normalized_input_symbol
        canonical_symbol_by_input_symbol[normalized_input_symbol] = canonical_symbol
        mappings_by_symbol[canonical_symbol] = mapping
        tick_size_by_symbol[canonical_symbol] = mapping.tick_size
        min_half_spread_by_symbol[canonical_symbol] = float(
            mapping.tick_size * command.min_half_spread_tick_fraction
        )

    if len(asset_classes) > 1 and not command.allow_mixed_asset_classes:
        raise ApplicationError(
            "spread calibration publication requires one homogeneous asset-class panel",
            asset_classes=",".join(sorted(asset_class.value for asset_class in asset_classes)),
        )
    return _PreparedPublication(
        mappings_by_symbol=mappings_by_symbol,
        tick_size_by_symbol=tick_size_by_symbol,
        min_half_spread_by_symbol=min_half_spread_by_symbol,
        canonical_symbol_by_input_symbol=canonical_symbol_by_input_symbol,
        asset_classes=asset_classes,
    )


def _validate_bundle_symbol_sets(command: SpreadCalibrationPublicationCommand) -> None:
    result = command.calibration_result
    panel_symbols = {_canonical_symbol(row.symbol) for row in result.panel_rows}
    summary_symbols = {_canonical_symbol(summary.symbol) for summary in result.symbol_summaries}
    fingerprint_symbols = {_canonical_symbol(symbol) for symbol in result.source_fingerprints}
    if panel_symbols != summary_symbols or panel_symbols != fingerprint_symbols:
        raise ApplicationError(
            "spread calibration bundle symbol sets must match before publication",
            panel_symbols=",".join(sorted(panel_symbols)),
            summary_symbols=",".join(sorted(summary_symbols)),
            fingerprint_symbols=",".join(sorted(fingerprint_symbols)),
        )

    panel_counts: dict[str, int] = {}
    row_keys: set[tuple[str, str]] = set()
    for row in result.panel_rows:
        normalized_symbol = _canonical_symbol(row.symbol)
        panel_counts[normalized_symbol] = panel_counts.get(normalized_symbol, 0) + 1
        row_key = (normalized_symbol, row.fill_timestamp_utc.isoformat())
        if row_key in row_keys:
            raise ApplicationError(
                "spread calibration bundle contains duplicate panel row identities",
                symbol=row.symbol,
                fill_timestamp_utc=row.fill_timestamp_utc.isoformat(),
            )
        row_keys.add(row_key)

    fingerprints_by_symbol = {
        _canonical_symbol(symbol): fingerprint
        for symbol, fingerprint in result.source_fingerprints.items()
    }
    summaries_by_symbol: dict[str, SpreadCalibrationSymbolSummary] = {}
    for summary in result.symbol_summaries:
        normalized_symbol = _canonical_symbol(summary.symbol)
        if normalized_symbol in summaries_by_symbol:
            raise ApplicationError(
                "spread calibration bundle contains duplicate symbol summaries",
                symbol=summary.symbol,
            )
        summaries_by_symbol[normalized_symbol] = summary
        panel_count = panel_counts[normalized_symbol]
        if summary.usable_row_count != panel_count:
            raise ApplicationError(
                "spread calibration summary usable_row_count does not match panel rows",
                symbol=summary.symbol,
                summary_usable_row_count=summary.usable_row_count,
                panel_row_count=panel_count,
            )

    for row in result.panel_rows:
        normalized_symbol = _canonical_symbol(row.symbol)
        expected_fingerprint = fingerprints_by_symbol[normalized_symbol]
        if row.source_fingerprint != expected_fingerprint:
            raise ApplicationError(
                "spread calibration row source_fingerprint does not match bundle provenance",
                symbol=row.symbol,
                row_source_fingerprint=row.source_fingerprint,
                expected_source_fingerprint=expected_fingerprint,
            )
    for normalized_symbol, summary in summaries_by_symbol.items():
        expected_fingerprint = fingerprints_by_symbol[normalized_symbol]
        if summary.source_fingerprint != expected_fingerprint:
            raise ApplicationError(
                "spread calibration summary source_fingerprint does not match bundle provenance",
                symbol=summary.symbol,
                summary_source_fingerprint=summary.source_fingerprint,
                expected_source_fingerprint=expected_fingerprint,
            )


def _validate_sample_counts(
    command: SpreadCalibrationPublicationCommand,
    split: _SplitRows,
) -> None:
    train_counts = _counts_by_symbol(split.train)
    holdout_counts = _counts_by_symbol(split.holdout)
    symbols = sorted({row.symbol for row in command.calibration_result.panel_rows})
    for symbol in symbols:
        train_count = train_counts.get(symbol, 0)
        holdout_count = holdout_counts.get(symbol, 0)
        if train_count < command.minimum_train_rows_per_symbol:
            raise ApplicationError(
                "insufficient train rows for spread calibration publication",
                symbol=symbol,
                train_row_count=train_count,
                minimum_train_rows_per_symbol=command.minimum_train_rows_per_symbol,
            )
        if holdout_count < command.minimum_holdout_rows_per_symbol:
            raise ApplicationError(
                "insufficient holdout rows for spread calibration publication",
                symbol=symbol,
                holdout_row_count=holdout_count,
                minimum_holdout_rows_per_symbol=command.minimum_holdout_rows_per_symbol,
            )


def _counts_by_symbol(rows: tuple[SpreadCalibrationPanelRow, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.symbol] = counts.get(row.symbol, 0) + 1
    return counts


def _prepare_rows(
    rows: tuple[SpreadCalibrationPanelRow, ...],
    min_half_spread_by_symbol: dict[str, float],
    canonical_symbol_by_input_symbol: dict[str, str],
) -> tuple[_PreparedCalibrationRow, ...]:
    prepared: list[_PreparedCalibrationRow] = []
    for row in rows:
        canonical_symbol = canonical_symbol_by_input_symbol[_canonical_symbol(row.symbol)]
        min_half_spread = min_half_spread_by_symbol[canonical_symbol]
        target_half_spread = max(float(row.half_spread_price), min_half_spread)
        if target_half_spread <= 0.0 or not math.isfinite(target_half_spread):
            raise ApplicationError(
                "spread calibration publication produced non-positive fit target",
                symbol=row.symbol,
                fill_timestamp_utc=row.fill_timestamp_utc.isoformat(),
            )
        prepared.append(
            _PreparedCalibrationRow(
                symbol=canonical_symbol,
                fill_timestamp_utc=row.fill_timestamp_utc,
                target_half_spread_price=target_half_spread,
                log_target_half_spread=math.log(target_half_spread),
                volatility_signal=max(0.0, float(row.volatility_stress_signal)),
                liquidity_signal=max(0.0, float(row.liquidity_stress_signal)),
                session_bucket_id=row.session_bucket_id,
            )
        )
    return tuple(prepared)


def _resolve_liquidity_fit_policy(
    command: SpreadCalibrationPublicationCommand,
) -> tuple[bool, str]:
    if not command.allow_liquidity_weight:
        return False, "disabled_until_provider_volume_semantics_are_explicitly_allowed"
    if not command.liquidity_eligibility_policy.allows(command.volume_semantics):
        raise ApplicationError(
            "liquidity weight requires trusted volume semantics",
            volume_semantics=command.volume_semantics.value,
            allowed_volume_semantics=",".join(
                semantics.value
                for semantics in command.liquidity_eligibility_policy.allowed_volume_semantics
            ),
        )

    below_threshold = [
        summary.symbol
        for summary in command.calibration_result.symbol_summaries
        if summary.positive_volume_coverage < command.liquidity_coverage_threshold
    ]
    if below_threshold:
        raise ApplicationError(
            "liquidity weight requires positive-volume coverage above threshold",
            symbols=",".join(sorted(below_threshold)),
            liquidity_coverage_threshold=command.liquidity_coverage_threshold,
        )
    return True, "enabled_by_command_volume_semantics_and_positive_volume_coverage"


def _symbol_bounds(
    *,
    command: SpreadCalibrationPublicationCommand,
    fit: _FitParameters,
    train_rows: tuple[_PreparedCalibrationRow, ...],
    min_half_spread_by_symbol: dict[str, float],
) -> dict[str, _SymbolBounds]:
    bounds: dict[str, _SymbolBounds] = {}
    for symbol, log_base in fit.symbol_log_base.items():
        min_half_spread = min_half_spread_by_symbol[symbol]
        base_half_spread = max(math.exp(log_base), min_half_spread)
        symbol_targets = [
            row.target_half_spread_price for row in train_rows if row.symbol == symbol
        ]
        max_half_spread = max(
            _quantile(symbol_targets, command.max_half_spread_train_quantile),
            base_half_spread,
            min_half_spread,
        )
        bounds[symbol] = _SymbolBounds(
            base_half_spread_price=base_half_spread,
            min_half_spread_price=min_half_spread,
            max_half_spread_price=max_half_spread,
        )
    return bounds


def _metrics_by_symbol(
    rows: tuple[_PreparedCalibrationRow, ...],
    fit: _FitParameters,
    bounds_by_symbol: dict[str, _SymbolBounds],
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for symbol in sorted({row.symbol for row in rows}):
        symbol_rows = tuple(row for row in rows if row.symbol == symbol)
        errors: list[float] = []
        clipped_count = 0
        for row in symbol_rows:
            raw_price = math.exp(_predict_log(row, fit))
            bounds = bounds_by_symbol[symbol]
            if raw_price > bounds.max_half_spread_price:
                clipped_count += 1
            clipped_price = min(
                max(raw_price, bounds.min_half_spread_price),
                bounds.max_half_spread_price,
            )
            errors.append(math.log(clipped_price) - row.log_target_half_spread)

        metrics[symbol] = {
            "row_count": float(len(symbol_rows)),
            "rmse_log": _rmse(errors),
            "mae_log": _mae(errors),
            "max_clip_rate": clipped_count / len(symbol_rows) if symbol_rows else 0.0,
        }
    return metrics


def _published_symbols(
    *,
    symbols: tuple[str, ...],
    fit: _FitParameters,
    bounds_by_symbol: dict[str, _SymbolBounds],
    train_metrics: dict[str, dict[str, float]],
    holdout_metrics: dict[str, dict[str, float]],
) -> tuple[PublishedCalibrationSymbol, ...]:
    published: list[PublishedCalibrationSymbol] = []
    for symbol in symbols:
        bounds = bounds_by_symbol[symbol]
        published.append(
            PublishedCalibrationSymbol(
                symbol=symbol,
                base_half_spread_price=Decimal(_decimal_string(bounds.base_half_spread_price)),
                min_half_spread_price=Decimal(_decimal_string(bounds.min_half_spread_price)),
                max_half_spread_price=Decimal(_decimal_string(bounds.max_half_spread_price)),
                volatility_weight=Decimal(_decimal_string(fit.volatility_weight)),
                liquidity_weight=Decimal(_decimal_string(fit.liquidity_weight)),
                train_row_count=int(train_metrics[symbol]["row_count"]),
                holdout_row_count=int(holdout_metrics[symbol]["row_count"]),
                train_max_clip_rate=train_metrics[symbol]["max_clip_rate"],
                holdout_max_clip_rate=holdout_metrics[symbol]["max_clip_rate"],
            )
        )
    return tuple(published)


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        raise ApplicationError("cannot calculate calibration quantile for an empty sample")
    ordered = sorted(values)
    index = int(math.ceil((len(ordered) - 1) * quantile))
    return ordered[index]


def _rmse(errors: list[float]) -> float:
    if not errors:
        return 0.0
    return math.sqrt(sum(error * error for error in errors) / len(errors))


def _mae(errors: list[float]) -> float:
    if not errors:
        return 0.0
    return sum(abs(error) for error in errors) / len(errors)


__all__ = ["publish_spread_calibration"]
