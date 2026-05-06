"""Numerical fitting helpers for spread calibration publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backtest_engine.application.calibration.contracts import (
    SpreadCalibrationPublicationCommand,
)


@dataclass(frozen=True)
class PreparedCalibrationRow:
    """One row prepared for log-linear calibration fitting."""

    symbol: str
    fill_timestamp_utc: datetime
    target_half_spread_price: float
    log_target_half_spread: float
    volatility_signal: float
    liquidity_signal: float
    session_bucket_id: str


@dataclass(frozen=True)
class CalibrationFitParameters:
    """Fitted non-negative log-linear calibration parameters."""

    symbol_log_base: dict[str, float]
    volatility_weight: float
    liquidity_weight: float
    session_adjustments_log: dict[str, float]
    iterations: int
    converged: bool


def fit_non_negative_log_linear(
    *,
    rows: tuple[PreparedCalibrationRow, ...],
    session_bucket_ids: tuple[str, ...],
    log_floor_by_symbol: dict[str, float],
    liquidity_enabled: bool,
    fit_tolerance: float,
    max_fit_iterations: int,
) -> CalibrationFitParameters:
    """Fit the widen-only runtime spread surface with coordinate descent."""

    symbols = tuple(sorted({row.symbol for row in rows}))
    baseline_session_id = session_bucket_ids[0]
    symbol_log_base = {
        symbol: max(
            _mean(row.log_target_half_spread for row in rows if row.symbol == symbol),
            log_floor_by_symbol[symbol],
        )
        for symbol in symbols
    }
    volatility_weight = 0.0
    liquidity_weight = 0.0
    session_adjustments = {session_id: 0.0 for session_id in session_bucket_ids}

    for iteration in range(1, max_fit_iterations + 1):
        previous_values = (
            tuple(symbol_log_base.items()),
            volatility_weight,
            liquidity_weight,
            tuple(session_adjustments.items()),
        )

        for symbol in symbols:
            symbol_rows = tuple(row for row in rows if row.symbol == symbol)
            symbol_log_base[symbol] = max(
                _mean(
                    row.log_target_half_spread
                    - volatility_weight * row.volatility_signal
                    - liquidity_weight * row.liquidity_signal
                    - session_adjustments[row.session_bucket_id]
                    for row in symbol_rows
                ),
                log_floor_by_symbol[symbol],
            )

        volatility_weight = _fit_non_negative_scalar(
            values=(row.volatility_signal for row in rows),
            residuals=(
                row.log_target_half_spread
                - symbol_log_base[row.symbol]
                - liquidity_weight * row.liquidity_signal
                - session_adjustments[row.session_bucket_id]
                for row in rows
            ),
        )
        if liquidity_enabled:
            liquidity_weight = _fit_non_negative_scalar(
                values=(row.liquidity_signal for row in rows),
                residuals=(
                    row.log_target_half_spread
                    - symbol_log_base[row.symbol]
                    - volatility_weight * row.volatility_signal
                    - session_adjustments[row.session_bucket_id]
                    for row in rows
                ),
            )
        else:
            liquidity_weight = 0.0

        for session_id in session_bucket_ids:
            if session_id == baseline_session_id:
                session_adjustments[session_id] = 0.0
                continue
            session_rows = tuple(row for row in rows if row.session_bucket_id == session_id)
            if not session_rows:
                session_adjustments[session_id] = 0.0
                continue
            session_adjustments[session_id] = max(
                0.0,
                _mean(
                    row.log_target_half_spread
                    - symbol_log_base[row.symbol]
                    - volatility_weight * row.volatility_signal
                    - liquidity_weight * row.liquidity_signal
                    for row in session_rows
                ),
            )

        current_values = (
            tuple(symbol_log_base.items()),
            volatility_weight,
            liquidity_weight,
            tuple(session_adjustments.items()),
        )
        if _max_parameter_delta(previous_values, current_values) < fit_tolerance:
            return CalibrationFitParameters(
                symbol_log_base=symbol_log_base,
                volatility_weight=volatility_weight,
                liquidity_weight=liquidity_weight,
                session_adjustments_log=session_adjustments,
                iterations=iteration,
                converged=True,
            )

    return CalibrationFitParameters(
        symbol_log_base=symbol_log_base,
        volatility_weight=volatility_weight,
        liquidity_weight=liquidity_weight,
        session_adjustments_log=session_adjustments,
        iterations=max_fit_iterations,
        converged=False,
    )


def project_fit_for_publication(
    *,
    command: SpreadCalibrationPublicationCommand,
    fitted_fit: CalibrationFitParameters,
    train_rows: tuple[PreparedCalibrationRow, ...],
    session_bucket_ids: tuple[str, ...],
    log_floor_by_symbol: dict[str, float],
) -> tuple[CalibrationFitParameters, str]:
    """Return runtime-compatible parameters for the requested target timeframe."""

    result = command.calibration_result
    if (
        command.target_timeframe == result.estimator_timeframe
        or command.allow_cross_timeframe_dynamic_weights
    ):
        return fitted_fit, "dynamic_weights_reused_for_compatible_or_explicitly_allowed_timeframe"

    symbols = tuple(sorted({row.symbol for row in train_rows}))
    symbol_log_base = {
        symbol: max(
            _mean(row.log_target_half_spread for row in train_rows if row.symbol == symbol),
            log_floor_by_symbol[symbol],
        )
        for symbol in symbols
    }
    return (
        CalibrationFitParameters(
            symbol_log_base=symbol_log_base,
            volatility_weight=0.0,
            liquidity_weight=0.0,
            session_adjustments_log={session_id: 0.0 for session_id in session_bucket_ids},
            iterations=0,
            converged=True,
        ),
        "dynamic_weights_disabled_for_cross_timeframe_feature_projection",
    )


def predict_log(row: PreparedCalibrationRow, fit: CalibrationFitParameters) -> float:
    """Predict one row's log half-spread from fitted parameters."""

    return (
        fit.symbol_log_base[row.symbol]
        + fit.volatility_weight * row.volatility_signal
        + fit.liquidity_weight * row.liquidity_signal
        + fit.session_adjustments_log[row.session_bucket_id]
    )


def _fit_non_negative_scalar(*, values: Any, residuals: Any) -> float:
    value_list = tuple(float(value) for value in values)
    residual_list = tuple(float(residual) for residual in residuals)
    denominator = sum(value * value for value in value_list)
    if denominator <= 0.0:
        return 0.0
    numerator = sum(value * residual for value, residual in zip(value_list, residual_list))
    return max(0.0, numerator / denominator)


def _mean(values: Any) -> float:
    value_list = tuple(float(value) for value in values)
    if not value_list:
        return 0.0
    return sum(value_list) / len(value_list)


def _max_parameter_delta(previous_values: Any, current_values: Any) -> float:
    previous_flat = _flatten_numeric(previous_values)
    current_flat = _flatten_numeric(current_values)
    return max(
        (abs(current - previous) for previous, current in zip(previous_flat, current_flat)),
        default=0.0,
    )


def _flatten_numeric(value: Any) -> tuple[float, ...]:
    if isinstance(value, float):
        return (value,)
    if isinstance(value, int):
        return (float(value),)
    if isinstance(value, tuple):
        flattened: list[float] = []
        for item in value:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], float):
                flattened.append(item[1])
            else:
                flattened.extend(_flatten_numeric(item))
        return tuple(flattened)
    return ()


__all__ = [
    "CalibrationFitParameters",
    "PreparedCalibrationRow",
    "fit_non_negative_log_linear",
    "predict_log",
    "project_fit_for_publication",
]
