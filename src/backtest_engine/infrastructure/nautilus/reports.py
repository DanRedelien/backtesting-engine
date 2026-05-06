"""Persist and normalize runtime reports emitted by Nautilus."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from pydantic import BaseModel, ConfigDict

from backtest_engine.core.annualization import resolve_annualization_factor
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.infrastructure.nautilus.run_spec_compiler import NautilusRunSpec
from backtest_engine.infrastructure.nautilus.synthetic_fill_diagnostics import (
    SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY,
    SYNTHETIC_FILL_DIAGNOSTICS_FILENAME,
    build_synthetic_fill_diagnostics,
)

if TYPE_CHECKING:
    from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts


class RuntimeReportReference(BaseModel):
    """A named report artifact emitted by the runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_name: NonEmptyStr
    location: NonEmptyStr


@dataclass(frozen=True)
class NautilusReportWriter:
    """Normalize and persist the canonical runtime report set."""

    def persist(
        self,
        compiled_spec: NautilusRunSpec,
        run_result: object,
        engine: object,
        runtime_sec: float,
        *,
        run_spec_path: Path | None = None,
    ) -> NautilusRunArtifacts:
        """Write runtime reports and return the normalized artifact contract."""

        from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts

        artifact_root = compiled_spec.artifact_root
        artifact_root.mkdir(parents=True, exist_ok=True)
        account_report = _prepare_report_for_artifact(self._build_account_report(compiled_spec, engine))
        positions_report = _prepare_report_for_artifact(engine.trader.generate_positions_report())
        orders_report = _prepare_report_for_artifact(engine.trader.generate_orders_report())
        fills_report = _prepare_report_for_artifact(engine.trader.generate_order_fills_report())
        returns_report = _build_returns_report(engine.portfolio.analyzer.returns())

        account_report_path = artifact_root / "account_report.parquet"
        positions_report_path = artifact_root / "positions_report.parquet"
        orders_report_path = artifact_root / "orders_report.parquet"
        fills_report_path = artifact_root / "fills_report.parquet"
        fills_report_csv_path = artifact_root / "fills_report.csv"
        returns_report_path = artifact_root / "returns_report.parquet"
        synthetic_fill_diagnostics_path = artifact_root / SYNTHETIC_FILL_DIAGNOSTICS_FILENAME
        summary_path = artifact_root / "summary.json"

        account_report.to_parquet(account_report_path)
        positions_report.to_parquet(positions_report_path)
        orders_report.to_parquet(orders_report_path)
        fills_report.to_parquet(fills_report_path)
        fills_report.to_csv(fills_report_csv_path, index=False)
        returns_report.to_parquet(returns_report_path)

        annualization_factor = resolve_annualization_factor(compiled_spec.annualization_policy)
        position_count = _position_count(positions_report)
        closed_position_count = _closed_position_count(positions_report)
        metrics = {
            "runtime_sec": float(runtime_sec),
            "total_orders": float(getattr(run_result, "total_orders", 0)),
            "total_positions": float(getattr(run_result, "total_positions", 0)),
            "total_events": float(getattr(run_result, "total_events", 0)),
            "fill_count": float(len(fills_report)),
            "order_count": float(len(orders_report)),
            "position_count": float(position_count),
            "closed_position_count": float(closed_position_count),
            "total_trades": float(closed_position_count),
            "trade_count": float(closed_position_count),
            "total_pnl": float(_extract_total_pnl(run_result)),
            "returns_count": float(len(returns_report)),
            "returns_has_nan": float(bool(returns_report["return_after_costs"].isna().any())),
            "net_return": _compute_net_return(returns_report),
            "sharpe_after_costs": _compute_sharpe_after_costs(
                returns_report,
                annualization_factor=annualization_factor,
            ),
            "max_drawdown": _compute_max_drawdown(returns_report),
            "account_report_rows": float(len(account_report)),
            "positions_report_rows": float(len(positions_report)),
        }
        summary_payload = {
            "run_id": compiled_spec.run_id,
            "dataset_id": compiled_spec.dataset_id,
            "runtime_sec": float(runtime_sec),
            "metrics": metrics,
            "strategy_ids": list(compiled_spec.strategy_ids),
            "instrument_ids": [item.instrument_id for item in compiled_spec.catalog.items],
            "annualization_policy": compiled_spec.annualization_policy,
        }
        summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

        report_locations = {
            "account_report": account_report_path.as_posix(),
            "positions_report": positions_report_path.as_posix(),
            "orders_report": orders_report_path.as_posix(),
            "fills_report": fills_report_path.as_posix(),
            "fills_report_csv": fills_report_csv_path.as_posix(),
            "returns_report": returns_report_path.as_posix(),
            "summary": summary_path.as_posix(),
        }
        if run_spec_path is not None:
            report_locations["compiled_run_spec"] = run_spec_path.as_posix()
        diagnostics = build_synthetic_fill_diagnostics(
            compiled_spec=compiled_spec,
            fills_report=fills_report,
            orders_report=orders_report,
            report_locations=report_locations,
        )
        synthetic_fill_diagnostics_path.write_text(
            diagnostics.model_dump_json(indent=2),
            encoding="utf-8",
        )
        report_locations[SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY] = (
            synthetic_fill_diagnostics_path.as_posix()
        )
        return NautilusRunArtifacts(
            run_id=compiled_spec.run_id,
            runtime_root=compiled_spec.runtime_root.as_posix(),
            report_locations=report_locations,
            metrics=metrics,
        )

    def _build_account_report(self, compiled_spec: NautilusRunSpec, engine: object) -> pd.DataFrame:
        from nautilus_trader.model.identifiers import Venue

        reports: list[pd.DataFrame] = []
        for venue_spec in compiled_spec.venues:
            report = engine.trader.generate_account_report(Venue(venue_spec.name))
            report = report.copy()
            if not report.empty:
                report["venue"] = venue_spec.name
            reports.append(report)
        if not reports:
            return pd.DataFrame()
        return pd.concat(reports).sort_index()


def _prepare_report_for_artifact(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    normalized = frame.copy()
    object_columns = list(normalized.select_dtypes(include=["object"]).columns)
    for column_name in object_columns:
        series = normalized[column_name]
        if not series.map(_requires_object_stringify).any():
            continue
        normalized[column_name] = series.map(_stringify_object_value)
    return normalized


def _requires_object_stringify(value: object) -> bool:
    return isinstance(value, (dict, list, tuple, set))


def _stringify_object_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=True, allow_nan=False, default=str)
    return value


def _position_count(positions_report: pd.DataFrame) -> int:
    if positions_report.empty:
        return 0
    return int((~_snapshot_mask(positions_report)).sum())


def _closed_position_count(positions_report: pd.DataFrame) -> int:
    if positions_report.empty or "ts_closed" not in positions_report.columns:
        return 0
    closed_mask = positions_report["ts_closed"].notna()
    return int((~_snapshot_mask(positions_report) & closed_mask).sum())


def _snapshot_mask(frame: pd.DataFrame) -> pd.Series:
    if "is_snapshot" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame["is_snapshot"].map(_truthy_position_flag)


def _truthy_position_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _extract_total_pnl(run_result: object) -> float:
    stats_pnls = getattr(run_result, "stats_pnls", {}) or {}
    if not stats_pnls:
        return 0.0
    first_currency = next(iter(stats_pnls.values()))
    if not isinstance(first_currency, dict):
        return 0.0
    return float(first_currency.get("PnL (total)", 0.0))


def _build_returns_report(returns: object) -> pd.DataFrame:
    series = pd.Series(returns, dtype="float64")
    if series.empty:
        return pd.DataFrame({"return_after_costs": pd.Series(dtype="float64")})
    normalized = series.rename("return_after_costs").to_frame()
    normalized.index.name = "timestamp_utc"
    return normalized.reset_index()


def _compute_net_return(returns_report: pd.DataFrame) -> float:
    returns = _returns_series(returns_report)
    if returns.empty:
        return 0.0
    cumulative = (1.0 + returns).cumprod()
    return float(cumulative.iloc[-1] - 1.0)


def _compute_sharpe_after_costs(
    returns_report: pd.DataFrame,
    *,
    annualization_factor: float,
) -> float:
    returns = _returns_series(returns_report)
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=0))
    if std <= 0.0:
        return 0.0
    mean = float(returns.mean())
    return float((mean / std) * (annualization_factor ** 0.5))


def _compute_max_drawdown(returns_report: pd.DataFrame) -> float:
    returns = _returns_series(returns_report)
    if returns.empty:
        return 0.0
    equity_curve = (1.0 + returns).cumprod()
    running_peak = equity_curve.cummax()
    drawdown = (equity_curve / running_peak) - 1.0
    return float(abs(drawdown.min()))


def _returns_series(returns_report: pd.DataFrame) -> pd.Series:
    if "return_after_costs" not in returns_report.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(returns_report["return_after_costs"], errors="coerce").dropna()


__all__ = ["NautilusReportWriter", "RuntimeReportReference"]
