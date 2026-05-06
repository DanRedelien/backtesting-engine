"""Artifact identity and persistence helpers for calibration publication."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest_engine.application.calibration.contracts import (
    SpreadCalibrationPanelRow,
    SpreadCalibrationPublicationCommand,
)
from backtest_engine.application.calibration.publication_helpers import (
    artifact_path_part,
    canonical_symbol,
    isoformat_utc,
)
from backtest_engine.application.calibration.publication_types import SplitRows
from backtest_engine.config.execution_costs import (
    default_execution_costs_path,
    execution_costs_config_hash,
    load_execution_costs,
)
from backtest_engine.core.ids import stable_hash
from backtest_engine.infrastructure.nautilus.symbol_map import (
    default_symbol_map_path,
    load_symbol_map,
)


def publication_id(command: SpreadCalibrationPublicationCommand) -> str:
    """Return a deterministic output identity for a generated target publication."""

    result = command.calibration_result
    content_hash = stable_hash(
        {
            "calibration_id": result.calibration_id,
            "target_timeframe": command.target_timeframe,
            "train_fraction": command.train_fraction,
            "minimum_train_rows_per_symbol": command.minimum_train_rows_per_symbol,
            "minimum_holdout_rows_per_symbol": command.minimum_holdout_rows_per_symbol,
            "max_half_spread_train_quantile": command.max_half_spread_train_quantile,
            "min_half_spread_tick_fraction": command.min_half_spread_tick_fraction,
            "allow_liquidity_weight": command.allow_liquidity_weight,
            "allow_cross_timeframe_dynamic_weights": (
                command.allow_cross_timeframe_dynamic_weights
            ),
            "liquidity_coverage_threshold": command.liquidity_coverage_threshold,
            "volume_semantics": command.volume_semantics.value,
            "allow_mixed_asset_classes": command.allow_mixed_asset_classes,
            "fit_tolerance": command.fit_tolerance,
            "max_fit_iterations": command.max_fit_iterations,
            "source_fingerprints": result.source_fingerprints,
            "base_execution_costs": _base_execution_costs_identity(
                command.base_execution_costs_path
            ),
            "symbol_map": _symbol_map_identity(command.symbol_map_path),
        }
    )
    return f"target-{artifact_path_part(command.target_timeframe)}-{content_hash[:12]}"


def write_panel_artifact(
    path: Path,
    rows: tuple[SpreadCalibrationPanelRow, ...],
    split: SplitRows,
) -> None:
    """Persist the calibration panel with train/holdout/purged sample labels."""

    sample_roles = {
        **{_row_key(row): "train" for row in split.train},
        **{_row_key(row): "holdout" for row in split.holdout},
        **{_row_key(row): "purged" for row in split.purged},
    }
    payload_rows = []
    for row in sorted(rows, key=_row_sort_key):
        payload = row.model_dump(mode="json")
        payload["sample_role"] = sample_roles[_row_key(row)]
        payload_rows.append(payload)
    pd.DataFrame(payload_rows).to_parquet(path, index=False)


def _base_execution_costs_identity(path: Path | None) -> dict[str, str]:
    config = load_execution_costs(path)
    resolved_path = Path(path) if path is not None else default_execution_costs_path()
    return {
        "path": _path_identity(resolved_path),
        "config_content_hash": execution_costs_config_hash(config),
    }


def _symbol_map_identity(path: Path | None) -> dict[str, str]:
    symbol_map = load_symbol_map(path)
    resolved_path = Path(path) if path is not None else default_symbol_map_path()
    return {
        "path": _path_identity(resolved_path),
        "content_hash": stable_hash(symbol_map.model_dump(mode="json")),
    }


def _path_identity(path: Path) -> str:
    return str(path.resolve(strict=False))


def _row_key(row: SpreadCalibrationPanelRow) -> tuple[str, str]:
    return (canonical_symbol(row.symbol), isoformat_utc(row.fill_timestamp_utc))


def _row_sort_key(row: SpreadCalibrationPanelRow) -> tuple[str, str]:
    return _row_key(row)


__all__ = ["publication_id", "write_panel_artifact"]
