"""Pure causal portfolio sizing contracts shared by study workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.runtime import PortfolioExecutionPolicy
from backtest_engine.core.annualization import resolve_annualization_factor
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr


_SLEEVE_ANALYTICS_COLUMNS = (
    "timestamp_utc",
    "unit_return_after_costs",
    "unit_turnover",
    "is_active",
    "has_valid_history",
    "gross_exposure",
    "costs",
)


@dataclass(frozen=True)
class SleeveAnalyticsFrame:
    """One normalized sleeve analytics frame on the portfolio rebalance clock."""

    slot_id: str
    frame: pd.DataFrame


class PortfolioSizingSnapshot(BaseModel):
    """One causal sizing decision and realized return at a rebalance timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_utc: datetime
    target_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    effective_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    eligible_slots: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    portfolio_scalar: float = Field(ge=0.0, le=1.0)
    cash_weight: float = Field(ge=0.0, le=1.0)
    estimated_vol: float = Field(ge=0.0)
    effective_return: float = 0.0


class PortfolioSizingRun(BaseModel):
    """One evaluated portfolio-return stream produced by the shared sizing engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshots: tuple[PortfolioSizingSnapshot, ...] = Field(default_factory=tuple)
    effective_bar_count: int = Field(ge=0, default=0)
    effective_start_utc: datetime | None = None
    effective_end_utc: datetime | None = None
    net_return: float = 0.0
    sharpe_after_costs: float = 0.0
    max_drawdown: float = 0.0


def build_sleeve_analytics_frame(slot_id: str, frame: pd.DataFrame) -> SleeveAnalyticsFrame:
    """Normalize a raw sleeve analytics frame into the shared contract."""

    normalized = frame.copy()
    missing_columns = sorted(set(_SLEEVE_ANALYTICS_COLUMNS).difference(normalized.columns))
    if missing_columns:
        raise ValueError(
            "sleeve analytics frame is missing required columns: " + ",".join(missing_columns)
        )
    normalized = normalized[list(_SLEEVE_ANALYTICS_COLUMNS)].copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    normalized["unit_return_after_costs"] = pd.to_numeric(
        normalized["unit_return_after_costs"],
        errors="coerce",
    )
    normalized["unit_turnover"] = pd.to_numeric(normalized["unit_turnover"], errors="coerce").fillna(0.0)
    normalized["gross_exposure"] = pd.to_numeric(normalized["gross_exposure"], errors="coerce").fillna(0.0)
    normalized["costs"] = pd.to_numeric(normalized["costs"], errors="coerce").fillna(0.0)
    normalized["is_active"] = normalized["is_active"].fillna(False).astype(bool)
    normalized["has_valid_history"] = normalized["has_valid_history"].fillna(False).astype(bool)
    normalized = normalized.dropna(subset=["timestamp_utc"]).drop_duplicates(
        subset=["timestamp_utc"],
        keep="last",
    )
    normalized = normalized.sort_values("timestamp_utc").reset_index(drop=True)
    return SleeveAnalyticsFrame(slot_id=slot_id, frame=normalized)


def evaluate_portfolio_sizing_run(
    *,
    analytics_by_slot: dict[str, SleeveAnalyticsFrame],
    target_weights: dict[str, float],
    policy: PortfolioExecutionPolicy,
) -> PortfolioSizingRun:
    """Evaluate a causal portfolio return stream using only history strictly before each bar."""

    annualization_factor = resolve_annualization_factor(policy.annualization_policy)
    aligned = _build_aligned_analytics_frame(analytics_by_slot)
    if aligned.empty:
        return PortfolioSizingRun()

    snapshots: list[PortfolioSizingSnapshot] = []
    realized_returns: list[float] = []
    effective_timestamps: list[datetime] = []
    for timestamp_utc in aligned.index:
        current_row = aligned.loc[timestamp_utc]
        history = aligned.loc[aligned.index < timestamp_utc]
        eligible_slots = _eligible_slots(
            timestamp_utc=timestamp_utc,
            history=history,
            current_row=current_row,
            target_weights=target_weights,
            lookback_bars=policy.vol_lookback_bars,
        )
        target_weights_by_slot = {
            str(slot_id): float(target_weights.get(slot_id, 0.0)) for slot_id in target_weights
        }
        if not eligible_slots:
            snapshots.append(
                PortfolioSizingSnapshot(
                    timestamp_utc=ensure_utc(timestamp_utc.to_pydatetime()),
                    target_weights=target_weights_by_slot,
                    effective_weights={slot_id: 0.0 for slot_id in target_weights},
                    eligible_slots=tuple(),
                    portfolio_scalar=0.0,
                    cash_weight=1.0,
                    estimated_vol=0.0,
                    effective_return=0.0,
                )
            )
            realized_returns.append(0.0)
            continue

        covariance = _covariance_matrix(
            history=history,
            eligible_slots=eligible_slots,
            lookback_bars=policy.vol_lookback_bars,
        )
        if covariance is None:
            snapshots.append(
                PortfolioSizingSnapshot(
                    timestamp_utc=ensure_utc(timestamp_utc.to_pydatetime()),
                    target_weights=target_weights_by_slot,
                    effective_weights={slot_id: 0.0 for slot_id in target_weights},
                    eligible_slots=tuple(),
                    portfolio_scalar=0.0,
                    cash_weight=1.0,
                    estimated_vol=0.0,
                    effective_return=0.0,
                )
            )
            realized_returns.append(0.0)
            continue

        weight_vector = pd.Series(
            [float(target_weights[slot_id]) for slot_id in eligible_slots],
            index=eligible_slots,
            dtype="float64",
        )
        raw_variance = float(
            weight_vector.to_numpy(dtype="float64")
            @ covariance.to_numpy(dtype="float64")
            @ weight_vector.to_numpy(dtype="float64")
        )
        estimated_vol = max(raw_variance, 0.0) ** 0.5
        estimated_vol *= annualization_factor**0.5
        portfolio_scalar = resolve_portfolio_scalar(
            estimated_vol=estimated_vol,
            target_portfolio_vol_frac=policy.target_portfolio_vol_frac,
            max_portfolio_leverage=policy.max_portfolio_leverage,
        )
        effective_weights = {
            slot_id: float(target_weights.get(slot_id, 0.0)) * portfolio_scalar
            if slot_id in eligible_slots
            else 0.0
            for slot_id in target_weights
        }
        current_returns = pd.Series(
            {
                slot_id: float(current_row[f"{slot_id}__unit_return_after_costs"])
                for slot_id in eligible_slots
            },
            dtype="float64",
        )
        effective_return = float((current_returns * weight_vector * portfolio_scalar).sum())
        realized_returns.append(effective_return)
        if any(value > 0.0 for value in effective_weights.values()):
            effective_timestamps.append(ensure_utc(timestamp_utc.to_pydatetime()))
        cash_weight = max(0.0, 1.0 - float(sum(effective_weights.values())))
        snapshots.append(
            PortfolioSizingSnapshot(
                timestamp_utc=ensure_utc(timestamp_utc.to_pydatetime()),
                target_weights=target_weights_by_slot,
                effective_weights=effective_weights,
                eligible_slots=tuple(eligible_slots),
                portfolio_scalar=portfolio_scalar,
                cash_weight=cash_weight,
                estimated_vol=max(estimated_vol, 0.0),
                effective_return=effective_return,
            )
        )

    returns_series = pd.Series(realized_returns, dtype="float64")
    return PortfolioSizingRun(
        snapshots=tuple(snapshots),
        effective_bar_count=len(effective_timestamps),
        effective_start_utc=effective_timestamps[0] if effective_timestamps else None,
        effective_end_utc=effective_timestamps[-1] if effective_timestamps else None,
        net_return=_series_net_return(returns_series),
        sharpe_after_costs=_series_sharpe_after_costs(
            returns_series,
            annualization_factor=annualization_factor,
        ),
        max_drawdown=_series_max_drawdown(returns_series),
    )


def _build_aligned_analytics_frame(
    analytics_by_slot: dict[str, SleeveAnalyticsFrame],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for slot_id, analytics_frame in analytics_by_slot.items():
        frame = analytics_frame.frame.copy()
        frame = frame.rename(
            columns={
                "unit_return_after_costs": f"{slot_id}__unit_return_after_costs",
                "unit_turnover": f"{slot_id}__unit_turnover",
                "is_active": f"{slot_id}__is_active",
                "has_valid_history": f"{slot_id}__has_valid_history",
                "gross_exposure": f"{slot_id}__gross_exposure",
                "costs": f"{slot_id}__costs",
            }
        )
        frame = frame.set_index("timestamp_utc")
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).sort_index()


def _eligible_slots(
    *,
    timestamp_utc: pd.Timestamp,
    history: pd.DataFrame,
    current_row: pd.Series,
    target_weights: dict[str, float],
    lookback_bars: int,
) -> tuple[str, ...]:
    eligible: list[str] = []
    for slot_id, target_weight in target_weights.items():
        if float(target_weight) <= 0.0:
            continue
        current_return_key = f"{slot_id}__unit_return_after_costs"
        current_active_key = f"{slot_id}__is_active"
        current_history_key = f"{slot_id}__has_valid_history"
        if current_return_key not in current_row.index:
            continue
        if pd.isna(current_row[current_return_key]):
            continue
        if not bool(current_row.get(current_active_key, False)):
            continue
        if not bool(current_row.get(current_history_key, False)):
            continue
        history_returns = _history_returns(history, slot_id=slot_id)
        if len(history_returns) < lookback_bars:
            continue
        eligible.append(slot_id)
    return tuple(eligible)


def _history_returns(history: pd.DataFrame, *, slot_id: str) -> pd.Series:
    return pd.to_numeric(
        history.loc[
            history.get(f"{slot_id}__is_active", pd.Series(dtype=bool)).fillna(False)
            & history.get(f"{slot_id}__has_valid_history", pd.Series(dtype=bool)).fillna(False),
            f"{slot_id}__unit_return_after_costs",
        ],
        errors="coerce",
    ).dropna()


def _covariance_matrix(
    *,
    history: pd.DataFrame,
    eligible_slots: tuple[str, ...],
    lookback_bars: int,
) -> pd.DataFrame | None:
    columns = [f"{slot_id}__unit_return_after_costs" for slot_id in eligible_slots]
    if history.empty:
        return None
    matrix = history[columns].dropna(how="any")
    if len(matrix) < lookback_bars:
        return None
    trailing = matrix.tail(lookback_bars).rename(
        columns={f"{slot_id}__unit_return_after_costs": slot_id for slot_id in eligible_slots}
    )
    if len(trailing) < lookback_bars:
        return None
    return trailing.cov()


def resolve_portfolio_scalar(
    *,
    estimated_vol: float,
    target_portfolio_vol_frac: float,
    max_portfolio_leverage: float,
) -> float:
    if estimated_vol <= 0.0:
        return 0.0
    return float(min(1.0, max_portfolio_leverage, target_portfolio_vol_frac / estimated_vol))


def _series_net_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((1.0 + returns).cumprod().iloc[-1] - 1.0)


def _series_sharpe_after_costs(
    returns: pd.Series,
    *,
    annualization_factor: float,
) -> float:
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=0))
    if std <= 0.0:
        return 0.0
    return float((float(returns.mean()) / std) * (annualization_factor**0.5))


def _series_max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity_curve = (1.0 + returns).cumprod()
    running_peak = equity_curve.cummax()
    drawdown = (equity_curve / running_peak) - 1.0
    return float(abs(drawdown.min()))


__all__ = [
    "PortfolioSizingRun",
    "PortfolioSizingSnapshot",
    "SleeveAnalyticsFrame",
    "build_sleeve_analytics_frame",
    "evaluate_portfolio_sizing_run",
    "resolve_portfolio_scalar",
]
