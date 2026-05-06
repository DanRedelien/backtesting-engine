"""Dashboard read models derived from persisted bundle artifacts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal, SupportsFloat, SupportsIndex, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import JsonScalar, NonEmptyStr
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.artifacts.bundle_loader import BundleLoader


DashboardPanelStatus = Literal["available", "empty", "error"]
HeatmapMetricKind = Literal["unavailable", "realized_return", "realized_pnl_proxy"]
TradeSide = Literal["long", "short"]

_MAX_CHART_POINTS = 720
_HEATMAP_MIN_OVERLAP = 3
_STRATEGY_COLUMNS = ("strategy_id", "strategy", "slot_id")
_TIMESTAMP_COLUMNS = ("timestamp_utc", "ts_closed", "timestamp", "time")
_REALIZED_RETURN_COLUMNS = ("realized_return", "realized_return_after_costs")
_REALIZED_PNL_COLUMNS = ("realized_pnl", "pnl", "realized_pnl_amount")
_ENTRY_COLUMNS = ("entry", "entry_side", "side")
_INSTRUMENT_COLUMNS = ("instrument_id", "instrument", "symbol")


class DashboardStat(BaseModel):
    """One fixed-order dashboard statistic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: NonEmptyStr
    label: NonEmptyStr
    value: JsonScalar = None
    display_value: str = "n/a"
    empty_reason: str = ""


class DashboardStatsPanel(BaseModel):
    """Stats panel payload with stable ordering and optional artifact-backed rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DashboardPanelStatus
    reason: str = ""
    items: tuple[DashboardStat, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class DashboardSeriesPoint(BaseModel):
    """One JSON-safe SVG chart point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_utc: NonEmptyStr
    value: float


class DashboardNamedSeries(BaseModel):
    """One labeled chart series inside a dashboard series panel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: NonEmptyStr
    label: NonEmptyStr
    points: tuple[DashboardSeriesPoint, ...] = Field(default_factory=tuple)
    full_point_count: int = 0
    displayed_point_count: int = 0


class DashboardSeriesPanel(BaseModel):
    """A downsampled time-series panel with explicit empty/error state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DashboardPanelStatus
    reason: str = ""
    points: tuple[DashboardSeriesPoint, ...] = Field(default_factory=tuple)
    full_point_count: int = 0
    displayed_point_count: int = 0
    series: tuple[DashboardNamedSeries, ...] = Field(default_factory=tuple)


class DashboardHeatmapCell(BaseModel):
    """One strategy-correlation matrix cell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    row_strategy_id: NonEmptyStr
    column_strategy_id: NonEmptyStr
    value: float
    overlap_count: int


class DashboardHeatmapPanel(BaseModel):
    """Strategy-level correlation payload with honest availability labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DashboardPanelStatus
    metric_kind: HeatmapMetricKind
    metric_label: NonEmptyStr
    reason: str = ""
    min_overlap: int = _HEATMAP_MIN_OVERLAP
    strategy_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    cells: tuple[DashboardHeatmapCell, ...] = Field(default_factory=tuple)


class BundleDashboardReadModel(BaseModel):
    """Read-only dashboard payload for one saved bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: NonEmptyStr
    generated_at_utc: datetime
    stats: DashboardStatsPanel
    equity: DashboardSeriesPanel
    drawdown: DashboardSeriesPanel
    heatmap: DashboardHeatmapPanel


@dataclass(frozen=True)
class _ParquetArtifact:
    frame: pd.DataFrame | None
    status: DashboardPanelStatus
    reason: str
    path: Path | None = None


@dataclass(frozen=True)
class _ClosedPositionTrade:
    timestamp_utc: pd.Timestamp
    realized_return: float
    side: TradeSide | None


@dataclass(frozen=True)
class _TradeAnalytics:
    status: DashboardPanelStatus
    reason: str
    equity_points: tuple[DashboardSeriesPoint, ...] = ()
    long_equity_points: tuple[DashboardSeriesPoint, ...] = ()
    short_equity_points: tuple[DashboardSeriesPoint, ...] = ()
    drawdown_points: tuple[DashboardSeriesPoint, ...] = ()
    net_return: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    trade_count: int | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    profit_factor_unbounded: bool = False
    avg_win: float | None = None
    avg_loss: float | None = None
    expectancy: float | None = None


@dataclass(frozen=True)
class _TradeMetricSummary:
    trade_count: int
    win_rate: float | None
    profit_factor: float | None
    profit_factor_unbounded: bool
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None


def load_bundle_dashboard_read_model(
    *,
    bundle_path: Path,
    loader: BundleLoader,
) -> BundleDashboardReadModel:
    """Load one persisted bundle and build its dashboard read model."""

    return build_bundle_dashboard_read_model(loader.load_bundle(bundle_path))


def build_bundle_dashboard_read_model(bundle: ResultBundle) -> BundleDashboardReadModel:
    """Build the dashboard payload from saved bundle artifacts only."""

    positions_artifact = _read_parquet_artifact(bundle, "positions_report")
    trade_analytics = _build_trade_analytics(bundle, positions_artifact)

    return BundleDashboardReadModel(
        bundle_id=bundle.bundle_id,
        generated_at_utc=datetime.now(timezone.utc),
        stats=_build_stats_panel(trade_analytics),
        equity=_build_series_panel(
            status=trade_analytics.status,
            reason=trade_analytics.reason,
            points=trade_analytics.equity_points,
            series=(
                ("combined", "Combined", trade_analytics.equity_points),
                ("long", "Long", trade_analytics.long_equity_points),
                ("short", "Short", trade_analytics.short_equity_points),
            ),
        ),
        drawdown=_build_series_panel(
            status=trade_analytics.status,
            reason=trade_analytics.reason,
            points=trade_analytics.drawdown_points,
        ),
        heatmap=_build_heatmap_panel(positions_artifact),
    )


def _read_parquet_artifact(bundle: ResultBundle, artifact_name: str) -> _ParquetArtifact:
    location = bundle.artifact_locations.get(artifact_name)
    if not location:
        return _ParquetArtifact(
            frame=None,
            status="empty",
            reason=f"{artifact_name} artifact location is not present",
        )

    artifact_path = Path(str(location))
    if not artifact_path.is_file():
        return _ParquetArtifact(
            frame=None,
            status="empty",
            reason=f"{artifact_name} artifact file was not found",
            path=artifact_path,
        )

    try:
        frame = pd.read_parquet(artifact_path)
    except Exception as exc:
        return _ParquetArtifact(
            frame=None,
            status="error",
            reason=f"failed to read {artifact_name} parquet artifact: {type(exc).__name__}",
            path=artifact_path,
        )

    return _ParquetArtifact(
        frame=frame,
        status="available",
        reason="",
        path=artifact_path,
    )


def _build_trade_analytics(bundle: ResultBundle, artifact: _ParquetArtifact) -> _TradeAnalytics:
    if artifact.status != "available" or artifact.frame is None:
        return _TradeAnalytics(status=artifact.status, reason=artifact.reason)

    frame = artifact.frame
    if frame.empty:
        return _TradeAnalytics(
            status="empty",
            reason="positions_report contains no rows",
            trade_count=0,
        )

    missing_columns = [
        column_name
        for column_name in ("is_snapshot", "ts_closed")
        if column_name not in frame.columns
    ]
    value_column = _first_existing_column(frame, _REALIZED_RETURN_COLUMNS)
    if value_column is None:
        missing_columns.append("realized_return")
    if missing_columns:
        return _TradeAnalytics(
            status="error",
            reason=f"positions_report is missing required columns: {', '.join(missing_columns)}",
        )

    timestamps = pd.to_datetime(
        frame["ts_closed"],
        utc=True,
        errors="coerce",
        format="ISO8601",
    )
    realized_returns = pd.to_numeric(frame[cast(str, value_column)], errors="coerce")
    snapshot_mask = frame["is_snapshot"].map(_truthy_position_flag)
    valid_mask = (
        ~snapshot_mask
        & timestamps.notna()
        & realized_returns.map(_is_finite_number)
    )
    valid = frame[valid_mask].copy()
    if valid.empty:
        return _TradeAnalytics(
            status="empty",
            reason="positions_report contains no closed non-snapshot positions with finite realized_return",
            trade_count=0,
        )

    trades = tuple(
        _ClosedPositionTrade(
            timestamp_utc=timestamp,
            realized_return=float(realized_return),
            side=_classify_position_side(bundle, row),
        )
        for (_, row), timestamp, realized_return in zip(
            valid.iterrows(),
            timestamps[valid_mask],
            realized_returns[valid_mask],
        )
    )
    if not trades:
        return _TradeAnalytics(
            status="empty",
            reason="positions_report produced no closed position trade observations",
            trade_count=0,
        )

    trade_metrics = _compute_trade_metrics(trades)
    capital_base = _safe_float(bundle.manifest.capital_base.amount)
    if capital_base is None or capital_base <= 0.0:
        return _TradeAnalytics(
            status="error",
            reason="capital base must be a finite positive number",
            trade_count=trade_metrics.trade_count,
            win_rate=trade_metrics.win_rate,
            profit_factor=trade_metrics.profit_factor,
            profit_factor_unbounded=trade_metrics.profit_factor_unbounded,
            avg_win=trade_metrics.avg_win,
            avg_loss=trade_metrics.avg_loss,
            expectancy=trade_metrics.expectancy,
        )

    period_returns = _period_returns_for_trades(trades)
    equity_points, drawdown_points, net_return, max_drawdown = _equity_and_drawdown_points(
        period_returns,
        capital_base=capital_base,
    )
    if not equity_points:
        return _TradeAnalytics(
            status="empty",
            reason="closed positions produced no finite equity points",
            trade_count=trade_metrics.trade_count,
            win_rate=trade_metrics.win_rate,
            profit_factor=trade_metrics.profit_factor,
            profit_factor_unbounded=trade_metrics.profit_factor_unbounded,
            avg_win=trade_metrics.avg_win,
            avg_loss=trade_metrics.avg_loss,
            expectancy=trade_metrics.expectancy,
        )

    long_returns = _side_period_returns_for_trades(trades, side="long", timestamps=tuple(period_returns.keys()))
    short_returns = _side_period_returns_for_trades(trades, side="short", timestamps=tuple(period_returns.keys()))
    long_equity_points = _equity_points_from_period_returns(long_returns, capital_base=capital_base)
    short_equity_points = _equity_points_from_period_returns(short_returns, capital_base=capital_base)

    return _TradeAnalytics(
        status="available",
        reason="",
        equity_points=tuple(equity_points),
        long_equity_points=tuple(long_equity_points),
        short_equity_points=tuple(short_equity_points),
        drawdown_points=tuple(drawdown_points),
        net_return=net_return,
        max_drawdown=max_drawdown,
        sharpe=_compute_sharpe(tuple(period_returns.values())),
        trade_count=trade_metrics.trade_count,
        win_rate=trade_metrics.win_rate,
        profit_factor=trade_metrics.profit_factor,
        profit_factor_unbounded=trade_metrics.profit_factor_unbounded,
        avg_win=trade_metrics.avg_win,
        avg_loss=trade_metrics.avg_loss,
        expectancy=trade_metrics.expectancy,
    )


def _compute_trade_metrics(trades: tuple[_ClosedPositionTrade, ...]) -> _TradeMetricSummary:
    returns = [trade.realized_return for trade in trades if _is_finite_number(trade.realized_return)]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    win_loss_count = len(wins) + len(losses)
    win_rate = (len(wins) / win_loss_count) if win_loss_count else None
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = abs(sum(losses) / len(losses)) if losses else None
    profit_factor: float | None = None
    profit_factor_unbounded = False
    if losses:
        profit_factor = sum(wins) / abs(sum(losses))
    elif wins:
        profit_factor_unbounded = True
    expectancy: float | None = None
    if win_rate is not None:
        expectancy = (win_rate * (avg_win or 0.0)) - ((1.0 - win_rate) * (avg_loss or 0.0))
    return _TradeMetricSummary(
        trade_count=len(trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        profit_factor_unbounded=profit_factor_unbounded,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
    )


def _period_returns_for_trades(trades: tuple[_ClosedPositionTrade, ...]) -> dict[pd.Timestamp, float]:
    grouped: dict[pd.Timestamp, float] = {}
    for trade in sorted(trades, key=lambda item: item.timestamp_utc):
        grouped[trade.timestamp_utc] = grouped.get(trade.timestamp_utc, 0.0) + trade.realized_return
    return grouped


def _side_period_returns_for_trades(
    trades: tuple[_ClosedPositionTrade, ...],
    *,
    side: TradeSide,
    timestamps: tuple[pd.Timestamp, ...],
) -> dict[pd.Timestamp, float]:
    grouped = {timestamp: 0.0 for timestamp in timestamps}
    for trade in trades:
        if trade.side != side:
            continue
        grouped[trade.timestamp_utc] = grouped.get(trade.timestamp_utc, 0.0) + trade.realized_return
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def _equity_and_drawdown_points(
    period_returns: dict[pd.Timestamp, float],
    *,
    capital_base: float,
) -> tuple[list[DashboardSeriesPoint], list[DashboardSeriesPoint], float | None, float | None]:
    equity_value = capital_base
    running_peak = capital_base
    equity_points: list[DashboardSeriesPoint] = []
    drawdown_points: list[DashboardSeriesPoint] = []
    max_drawdown = 0.0

    for timestamp_utc, period_return in period_returns.items():
        next_equity_value = equity_value * (1.0 + period_return)
        if not _is_finite_number(next_equity_value):
            continue
        equity_value = next_equity_value
        running_peak = max(running_peak, equity_value)
        drawdown = (equity_value / running_peak) - 1.0 if running_peak > 0.0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        timestamp = _format_timestamp(timestamp_utc)
        equity_points.append(DashboardSeriesPoint(timestamp_utc=timestamp, value=equity_value))
        drawdown_points.append(DashboardSeriesPoint(timestamp_utc=timestamp, value=drawdown))

    if not equity_points:
        return [], [], None, None
    net_return = (equity_points[-1].value / capital_base) - 1.0
    return (
        equity_points,
        drawdown_points,
        net_return if _is_finite_number(net_return) else None,
        abs(max_drawdown) if _is_finite_number(max_drawdown) else None,
    )


def _equity_points_from_period_returns(
    period_returns: dict[pd.Timestamp, float],
    *,
    capital_base: float,
) -> list[DashboardSeriesPoint]:
    equity_value = capital_base
    points: list[DashboardSeriesPoint] = []
    for timestamp_utc, period_return in period_returns.items():
        next_equity_value = equity_value * (1.0 + period_return)
        if not _is_finite_number(next_equity_value):
            continue
        equity_value = next_equity_value
        points.append(DashboardSeriesPoint(timestamp_utc=_format_timestamp(timestamp_utc), value=equity_value))
    return points


def _compute_sharpe(period_returns: tuple[float, ...]) -> float | None:
    returns = [value for value in period_returns if _is_finite_number(value)]
    if len(returns) < 2:
        return None
    mean = sum(returns) / float(len(returns))
    try:
        variance = sum((value - mean) ** 2 for value in returns) / float(len(returns))
    except OverflowError:
        return None
    if not _is_finite_number(variance):
        return None
    std = math.sqrt(variance)
    if std <= 0.0:
        return None
    sharpe = (mean / std) * math.sqrt(float(len(returns)))
    return sharpe if _is_finite_number(sharpe) else None


def _classify_position_side(bundle: ResultBundle, row: pd.Series) -> TradeSide | None:
    entry_direction = _entry_direction(_first_row_value(row, _ENTRY_COLUMNS))
    if entry_direction is None:
        return None

    spread_weight = _spread_weight_for_position(bundle, row)
    if spread_weight is not None:
        if spread_weight == 0.0:
            return None
        return "long" if entry_direction * spread_weight > 0.0 else "short"

    return "long" if entry_direction > 0.0 else "short"


def _spread_weight_for_position(bundle: ResultBundle, row: pd.Series) -> float | None:
    instrument_id = _clean_identifier(_first_row_value(row, _INSTRUMENT_COLUMNS))
    if not instrument_id:
        return None
    strategy_id = _clean_identifier(_first_row_value(row, _STRATEGY_COLUMNS))

    for strategy_spec in bundle.run_spec.strategies:
        if strategy_spec.strategy.implementation_id != "statarb_weighted_spread":
            continue
        if strategy_id and strategy_id not in {
            str(strategy_spec.strategy.strategy_id),
            str(strategy_spec.slot_id),
        }:
            continue
        weights = strategy_spec.strategy.parameters.get("spread_weights")
        if not isinstance(weights, list | tuple):
            continue
        for leg, raw_weight in zip(strategy_spec.legs, weights):
            weight = _safe_float(raw_weight)
            if weight is None:
                continue
            if _instrument_matches_symbol(instrument_id, str(leg.symbol)):
                return weight
    return None


def _first_row_value(row: pd.Series, candidates: tuple[str, ...]) -> object:
    for column_name in candidates:
        if column_name in row.index:
            return row[column_name]
    return None


def _entry_direction(value: object) -> float | None:
    normalized = _clean_identifier(value).upper()
    if normalized in {"BUY", "BOUGHT", "LONG"}:
        return 1.0
    if normalized in {"SELL", "SOLD", "SHORT"}:
        return -1.0
    return None


def _instrument_matches_symbol(instrument_id: str, symbol: str) -> bool:
    instrument_key = _normalize_instrument_match_key(instrument_id)
    symbol_key = _normalize_instrument_match_key(symbol)
    if not instrument_key or not symbol_key:
        return False
    return instrument_key == symbol_key or instrument_key.startswith(symbol_key)


def _normalize_instrument_match_key(value: str) -> str:
    core = str(value).split(".", maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]", "", core.lower())


def _truthy_position_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "t", "yes", "y"}


def _build_series_panel(
    *,
    status: DashboardPanelStatus,
    reason: str,
    points: tuple[DashboardSeriesPoint, ...],
    series: tuple[tuple[str, str, tuple[DashboardSeriesPoint, ...]], ...] = (),
) -> DashboardSeriesPanel:
    if status != "available":
        return DashboardSeriesPanel(status=status, reason=reason)
    displayed_points = _downsample_points(points, max_points=_MAX_CHART_POINTS)
    named_series: list[DashboardNamedSeries] = []
    for key, label, series_points in series:
        displayed_series_points = _downsample_points(series_points, max_points=_MAX_CHART_POINTS)
        named_series.append(
            DashboardNamedSeries(
                key=key,
                label=label,
                points=displayed_series_points,
                full_point_count=len(series_points),
                displayed_point_count=len(displayed_series_points),
            )
        )
    return DashboardSeriesPanel(
        status="available",
        reason="",
        points=displayed_points,
        full_point_count=len(points),
        displayed_point_count=len(displayed_points),
        series=tuple(named_series),
    )


def _build_stats_panel(trade_analytics: _TradeAnalytics) -> DashboardStatsPanel:
    items: tuple[DashboardStat, ...] = (
        _number_stat("net_return", "Net Return", trade_analytics.net_return, formatter=_format_percent),
        _number_stat("max_drawdown", "Max Drawdown", trade_analytics.max_drawdown, formatter=_format_percent),
        _number_stat("sharpe", "Sharpe", trade_analytics.sharpe),
        _number_stat("trade_count", "Trade Count", trade_analytics.trade_count, formatter=_format_count),
        _number_stat("win_rate", "Win Rate", trade_analytics.win_rate, formatter=_format_percent),
        _profit_factor_stat(trade_analytics),
        _avg_win_loss_stat(trade_analytics),
        _number_stat(
            "expectancy",
            "Expectancy",
            trade_analytics.expectancy,
            formatter=_format_expectancy_percent,
        ),
    )
    warnings = (trade_analytics.reason,) if trade_analytics.status == "error" else ()
    return DashboardStatsPanel(status="available", items=items, warnings=warnings)


def _build_heatmap_panel(artifact: _ParquetArtifact) -> DashboardHeatmapPanel:
    if artifact.status != "available" or artifact.frame is None:
        return _unavailable_heatmap(artifact.reason)

    frame = artifact.frame
    if frame.empty:
        return _unavailable_heatmap("positions_report contains no rows")

    strategy_column = _first_existing_column(frame, _STRATEGY_COLUMNS)
    timestamp_column = _first_existing_column(frame, _TIMESTAMP_COLUMNS)
    value_column = _first_existing_column(frame, _REALIZED_RETURN_COLUMNS)
    metric_kind: HeatmapMetricKind = "realized_return"
    metric_label = "Realized return correlation"
    if value_column is None:
        value_column = _first_existing_column(frame, _REALIZED_PNL_COLUMNS)
        metric_kind = "realized_pnl_proxy"
        metric_label = "Realized PnL proxy correlation"

    if strategy_column is None or timestamp_column is None or value_column is None:
        return _unavailable_heatmap(
            "positions_report does not expose stable strategy, timestamp, and realized return/PnL columns",
        )

    normalized = pd.DataFrame(
        {
            "strategy_id": frame[strategy_column].map(_clean_identifier),
            "timestamp_utc": pd.to_datetime(
                frame[timestamp_column],
                utc=True,
                errors="coerce",
                format="ISO8601",
            ),
            "value": frame[value_column].map(_parse_money_value)
            if metric_kind == "realized_pnl_proxy"
            else pd.to_numeric(frame[value_column], errors="coerce"),
        }
    )
    valid = normalized[
        normalized["strategy_id"].ne("")
        & normalized["timestamp_utc"].notna()
        & normalized["value"].map(_is_finite_number)
    ].copy()
    if valid.empty:
        return _heatmap_empty(
            metric_kind=metric_kind,
            metric_label=metric_label,
            reason="positions_report contains no finite per-strategy observations",
        )

    grouped = _group_strategy_observations(valid, metric_kind=metric_kind)
    pivot = grouped.pivot(index="timestamp_utc", columns="strategy_id", values="value").sort_index()
    candidate_strategy_ids = [
        str(strategy_id)
        for strategy_id in pivot.columns
        if _series_is_eligible(pivot[strategy_id], min_overlap=_HEATMAP_MIN_OVERLAP)
    ]
    eligible_strategy_ids = _strategy_ids_with_overlap(
        pivot=pivot,
        strategy_ids=candidate_strategy_ids,
        min_overlap=_HEATMAP_MIN_OVERLAP,
    )
    if len(eligible_strategy_ids) < 2:
        return _heatmap_empty(
            metric_kind=metric_kind,
            metric_label=metric_label,
            reason="requires at least two non-constant strategy series with sufficient overlap",
        )

    cells: list[DashboardHeatmapCell] = []
    for row_strategy_id in eligible_strategy_ids:
        for column_strategy_id in eligible_strategy_ids:
            if row_strategy_id == column_strategy_id:
                series = pivot[row_strategy_id].dropna()
                cells.append(
                    DashboardHeatmapCell(
                        row_strategy_id=row_strategy_id,
                        column_strategy_id=column_strategy_id,
                        value=1.0,
                        overlap_count=int(len(series)),
                    )
                )
                continue
            pair = pivot[[row_strategy_id, column_strategy_id]].dropna()
            overlap_count = int(len(pair))
            if overlap_count < _HEATMAP_MIN_OVERLAP:
                continue
            correlation = _safe_float(pair[row_strategy_id].corr(pair[column_strategy_id]))
            if correlation is None:
                continue
            cells.append(
                DashboardHeatmapCell(
                    row_strategy_id=row_strategy_id,
                    column_strategy_id=column_strategy_id,
                    value=correlation,
                    overlap_count=overlap_count,
                )
            )

    if not cells:
        return _heatmap_empty(
            metric_kind=metric_kind,
            metric_label=metric_label,
            reason="strategy observations did not produce finite correlations",
        )

    return DashboardHeatmapPanel(
        status="available",
        metric_kind=metric_kind,
        metric_label=metric_label,
        strategy_ids=tuple(eligible_strategy_ids),
        cells=tuple(cells),
    )


def _unavailable_heatmap(reason: str) -> DashboardHeatmapPanel:
    return _heatmap_empty(
        metric_kind="unavailable",
        metric_label="Unavailable",
        reason=reason,
    )


def _heatmap_empty(
    *,
    metric_kind: HeatmapMetricKind,
    metric_label: str,
    reason: str,
) -> DashboardHeatmapPanel:
    return DashboardHeatmapPanel(
        status="empty",
        metric_kind=metric_kind,
        metric_label=metric_label,
        reason=reason,
    )


def _group_strategy_observations(
    frame: pd.DataFrame,
    *,
    metric_kind: HeatmapMetricKind,
) -> pd.DataFrame:
    if metric_kind == "realized_return":
        grouped = frame.groupby(["timestamp_utc", "strategy_id"], sort=True)["value"].apply(
            _compound_return_values,
        )
    else:
        grouped = frame.groupby(["timestamp_utc", "strategy_id"], sort=True)["value"].sum()
    return grouped.reset_index(name="value")


def _series_is_eligible(series: pd.Series, *, min_overlap: int) -> bool:
    valid = series.dropna()
    if int(len(valid)) < min_overlap:
        return False
    return int(valid.nunique(dropna=True)) > 1


def _strategy_ids_with_overlap(
    *,
    pivot: pd.DataFrame,
    strategy_ids: list[str],
    min_overlap: int,
) -> list[str]:
    eligible: list[str] = []
    for strategy_id in strategy_ids:
        has_overlap = False
        for other_strategy_id in strategy_ids:
            if strategy_id == other_strategy_id:
                continue
            pair = pivot[[strategy_id, other_strategy_id]].dropna()
            if int(len(pair)) >= min_overlap:
                has_overlap = True
                break
        if has_overlap:
            eligible.append(strategy_id)
    return eligible


def _downsample_points(
    points: tuple[DashboardSeriesPoint, ...],
    *,
    max_points: int,
) -> tuple[DashboardSeriesPoint, ...]:
    if len(points) <= max_points:
        return points
    if max_points < 4:
        return (points[0], points[-1])

    interior = points[1:-1]
    bucket_count = max(1, (max_points - 2) // 2)
    selected_indexes: set[int] = {0, len(points) - 1}
    for bucket_index in range(bucket_count):
        start = (bucket_index * len(interior)) // bucket_count
        end = ((bucket_index + 1) * len(interior)) // bucket_count
        bucket = interior[start:end]
        if not bucket:
            continue
        min_offset = min(range(len(bucket)), key=lambda index: bucket[index].value)
        max_offset = max(range(len(bucket)), key=lambda index: bucket[index].value)
        selected_indexes.add(start + 1 + min_offset)
        selected_indexes.add(start + 1 + max_offset)
    return tuple(points[index] for index in sorted(selected_indexes))


def _compound_return_values(values: pd.Series) -> float:
    compounded = 1.0
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        compounded *= 1.0 + number
    return compounded - 1.0


def _profit_factor_stat(trade_analytics: _TradeAnalytics) -> DashboardStat:
    if trade_analytics.profit_factor_unbounded:
        return DashboardStat(
            key="profit_factor",
            label="Profit Factor",
            value=None,
            display_value="unbounded",
        )
    return _number_stat("profit_factor", "Profit Factor", trade_analytics.profit_factor)


def _avg_win_loss_stat(trade_analytics: _TradeAnalytics) -> DashboardStat:
    avg_win = _format_percent(trade_analytics.avg_win) if trade_analytics.avg_win is not None else "n/a"
    avg_loss = _format_percent(trade_analytics.avg_loss) if trade_analytics.avg_loss is not None else "n/a"
    if avg_win == "n/a" and avg_loss == "n/a":
        return DashboardStat(
            key="avg_win_avg_loss",
            label="Avg Win / Avg Loss",
            value=None,
            display_value="n/a",
            empty_reason="Avg Win / Avg Loss is unavailable",
        )
    display_value = f"{avg_win} / {avg_loss}"
    return DashboardStat(
        key="avg_win_avg_loss",
        label="Avg Win / Avg Loss",
        value=display_value,
        display_value=display_value,
    )


def _number_stat(
    key: str,
    label: str,
    value: float | int | None,
    *,
    formatter: Callable[[float], str] | None = None,
) -> DashboardStat:
    safe_value = _safe_float(value)
    if safe_value is None:
        return DashboardStat(
            key=key,
            label=label,
            value=None,
            display_value="n/a",
            empty_reason=f"{label} is unavailable",
        )
    display_value = formatter(safe_value) if formatter is not None else _format_number(safe_value)
    return DashboardStat(key=key, label=label, value=safe_value, display_value=display_value)


def _first_existing_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column_name in candidates:
        if column_name in frame.columns:
            return column_name
    return None


def _clean_identifier(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(cast(Any, value))):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    try:
        number = float(cast(str | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _is_finite_number(value: object) -> bool:
    return _safe_float(value) is not None


def _parse_money_value(value: object) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    if isinstance(value, int | float | Decimal):
        return float(value)
    if isinstance(value, str):
        return _parse_money_string(value)
    if isinstance(value, list | tuple | set):
        return float(sum(_parse_money_value(item) for item in value))
    return _parse_money_string(str(value))


def _parse_money_string(value: str) -> float:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", value)
    if match is None:
        return math.nan
    return float(match.group(0).replace(",", ""))


def _format_timestamp(timestamp: pd.Timestamp) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone.utc)
    else:
        timestamp = timestamp.tz_convert(timezone.utc)
    return timestamp.isoformat().replace("+00:00", "Z")


def _format_number(value: float) -> str:
    return f"{value:,.4f}"


def _format_percent(value: float) -> str:
    return f"{value * 100.0:,.2f}%"


def _format_expectancy_percent(value: float) -> str:
    percent = value * 100.0
    if percent == 0.0:
        return "0.00%"
    if abs(percent) < 0.01:
        return f"{percent:,.4f}%"
    return f"{percent:,.2f}%"


def _format_count(value: float) -> str:
    return f"{int(round(value)):,}"


__all__ = [
    "BundleDashboardReadModel",
    "DashboardHeatmapCell",
    "DashboardHeatmapPanel",
    "DashboardNamedSeries",
    "DashboardSeriesPanel",
    "DashboardSeriesPoint",
    "DashboardStatsPanel",
    "DashboardStat",
    "build_bundle_dashboard_read_model",
    "load_bundle_dashboard_read_model",
]
