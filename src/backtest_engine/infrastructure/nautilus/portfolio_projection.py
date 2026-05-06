"""Project stable portfolio truth from persisted runtime reports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts


class PortfolioProjection(BaseModel):
    """A stable portfolio projection derived from runtime artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    position_count: int = 0
    summary: dict[str, JsonValue] = Field(default_factory=dict)
    artifact_locations: dict[str, NonEmptyStr] = Field(default_factory=dict)


class PortfolioProjector(Protocol):
    """Project portfolio truth from Nautilus runtime artifacts."""

    def project(
        self,
        run_spec: BacktestRunSpec,
        artifacts: NautilusRunArtifacts,
    ) -> PortfolioProjection:
        """Return a normalized portfolio projection."""
        ...


@dataclass(frozen=True)
class FilesystemPortfolioProjector:
    """Build a stable portfolio projection from persisted runtime reports."""

    projection_filename: str = "portfolio_projection.json"

    def project(
        self,
        run_spec: BacktestRunSpec,
        artifacts: NautilusRunArtifacts,
    ) -> PortfolioProjection:
        positions_report = _load_required_report(artifacts, "positions_report")
        account_report = _load_optional_report(artifacts, "account_report")
        is_snapshot = _snapshot_mask(positions_report)
        closed_mask = positions_report["ts_closed"].notna() if "ts_closed" in positions_report.columns else pd.Series(
            [],
            dtype=bool,
        )
        open_positions = positions_report[~is_snapshot & ~closed_mask] if not positions_report.empty else pd.DataFrame()
        closed_positions = positions_report[~is_snapshot & closed_mask] if not positions_report.empty else pd.DataFrame()

        position_count = int(len(open_positions) + len(closed_positions))
        summary = {
            "open_position_count": len(open_positions),
            "closed_position_count": len(closed_positions),
            "realized_pnl": _sum_money_column(closed_positions, "realized_pnl"),
            "commission_paid": _sum_money_column(positions_report, "commissions"),
        }
        ending_balance = _extract_ending_balance(account_report)
        if ending_balance is not None:
            summary["ending_balance"] = ending_balance

        projection_path = Path(artifacts.runtime_root) / self.projection_filename
        projection_payload = {
            "run_id": run_spec.run_id,
            "position_count": position_count,
            "summary": summary,
        }
        projection_path.write_text(json.dumps(projection_payload, indent=2), encoding="utf-8")
        return PortfolioProjection(
            run_id=run_spec.run_id,
            position_count=position_count,
            summary=summary,
            artifact_locations={"portfolio_projection": projection_path.as_posix()},
        )


def _load_required_report(artifacts: NautilusRunArtifacts, name: str) -> pd.DataFrame:
    location = artifacts.report_locations.get(name)
    if location is None:
        raise InfrastructureError(
            "runtime artifact missing required report",
            run_id=artifacts.run_id,
            report_name=name,
        )
    try:
        return pd.read_parquet(location)
    except Exception as exc:
        raise InfrastructureError(
            "failed to load runtime parquet report",
            run_id=artifacts.run_id,
            report_name=name,
            location=location,
        ) from exc


def _load_optional_report(artifacts: NautilusRunArtifacts, name: str) -> pd.DataFrame | None:
    location = artifacts.report_locations.get(name)
    if location is None:
        return None
    try:
        return pd.read_parquet(location)
    except Exception:
        return None


def _snapshot_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series([], dtype=bool)
    if "is_snapshot" not in frame.columns:
        return pd.Series([False] * len(frame), index=frame.index, dtype=bool)
    return frame["is_snapshot"].fillna(False).astype(bool)


def _sum_money_column(frame: pd.DataFrame, column_name: str) -> float:
    if frame.empty or column_name not in frame.columns:
        return 0.0
    return float(sum(_parse_money_value(value) for value in frame[column_name]))


def _parse_money_value(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _parse_money_string(value)
    if isinstance(value, (list, tuple, set)):
        return sum(_parse_money_value(item) for item in value)
    return _parse_money_string(str(value))


def _parse_money_string(value: str) -> float:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", value)
    if match is None:
        return 0.0
    return float(match.group(0).replace(",", ""))


def _extract_ending_balance(account_report: pd.DataFrame | None) -> float | None:
    if account_report is None or account_report.empty:
        return None
    candidate_columns = ("balance", "balance_total", "free", "equity", "total")
    last_row = account_report.iloc[-1]
    for column_name in candidate_columns:
        if column_name in account_report.columns:
            return _parse_money_value(last_row[column_name])
    return None


__all__ = ["FilesystemPortfolioProjector", "PortfolioProjection", "PortfolioProjector"]
