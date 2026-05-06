"""PNG artifact rendering for spread calibration diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtest_engine.application.calibration.diagnostics_types import (
    CalibrationDiagnosticRow,
    DiagnosticsArtifacts,
)
from backtest_engine.application.calibration.publication_helpers import artifact_path_part
from backtest_engine.config.calibration import SpreadCalibrationDiagnosticsSettings
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.ids import stable_hash


def write_diagnostic_artifacts(
    *,
    output_dir: Path,
    diagnostics: dict[str, Any],
    holdout_rows_by_symbol: dict[str, tuple[CalibrationDiagnosticRow, ...]],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> DiagnosticsArtifacts:
    """Write deterministic summary and per-symbol diagnostics PNG files."""

    plt = _pyplot(settings)
    summary_path = output_dir / "calibration_diagnostics_summary.png"
    _write_summary_png(plt, summary_path, diagnostics, settings)

    symbol_paths_by_symbol = _symbol_png_paths(output_dir, tuple(sorted(holdout_rows_by_symbol)))
    for symbol, symbol_path in symbol_paths_by_symbol.items():
        _write_symbol_png(
            plt,
            symbol_path,
            symbol,
            diagnostics["symbols"][symbol],
            holdout_rows_by_symbol[symbol],
            settings,
        )

    return DiagnosticsArtifacts(
        summary_png_path=summary_path,
        symbol_png_paths_by_symbol=symbol_paths_by_symbol,
    )


def diagnostic_symbol_png_name(symbol: str) -> str:
    """Return a deterministic collision-resistant per-symbol diagnostics PNG name."""

    safe_symbol = artifact_path_part(symbol) or "symbol"
    symbol_hash = stable_hash({"symbol": symbol})[:8]
    return f"calibration_diagnostics_{safe_symbol}_{symbol_hash}.png"


def _symbol_png_paths(output_dir: Path, symbols: tuple[str, ...]) -> dict[str, Path]:
    paths_by_symbol: dict[str, Path] = {}
    paths_by_name: dict[str, str] = {}
    for symbol in symbols:
        filename = diagnostic_symbol_png_name(symbol)
        previous_symbol = paths_by_name.get(filename)
        if previous_symbol is not None:
            raise ApplicationError(
                "spread calibration diagnostic PNG filename collision",
                symbol=symbol,
                previous_symbol=previous_symbol,
                filename=filename,
            )
        paths_by_name[filename] = symbol
        paths_by_symbol[symbol] = output_dir / filename
    return paths_by_symbol


def _pyplot(settings: SpreadCalibrationDiagnosticsSettings) -> Any:
    import matplotlib

    matplotlib.use(settings.plot.backend, force=True)
    from matplotlib import pyplot as plt

    return plt


def _write_summary_png(
    plt: Any,
    path: Path,
    diagnostics: dict[str, Any],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    fig, axis = plt.subplots(
        figsize=(settings.plot.summary_width_inches, settings.plot.summary_height_inches),
        dpi=settings.plot.dpi,
    )
    try:
        fig.patch.set_facecolor(palette.paper)
        axis.set_facecolor(palette.paper)
        axis.axis("off")
        rows = []
        row_colours = []
        for symbol, payload in sorted(diagnostics["symbols"].items()):
            effective = payload["holdout"]["effective_runtime_prediction"]
            flags = payload["flags"]
            visible_flags = [
                flag for flag in flags if flag["severity"] in {"warning", "review_flag"}
            ]
            severity = _highest_severity(visible_flags)
            rows.append(
                [
                    symbol,
                    f"{effective['mae_log']:.4f}",
                    f"{effective['rmse_log']:.4f}",
                    f"{effective['mean_log_error']:.4f}",
                    f"{payload['saturation']['max_clip_rate']:.1%}",
                    ", ".join(flag["code"] for flag in visible_flags[:3]),
                ]
            )
            row_colours.append(_severity_colour(severity, settings))

        axis.set_title(
            "Spread Calibration Diagnostics",
            loc="left",
            color=palette.ink,
            fontsize=14,
            pad=16,
        )
        axis.text(
            0.0,
            0.94,
            "Report-only internal heuristics. Yellow and red flags never block publication.",
            transform=axis.transAxes,
            color=palette.muted,
            fontsize=9,
        )
        table = axis.table(
            cellText=rows,
            colLabels=[
                "Symbol",
                "MAE log",
                "RMSE log",
                "Mean log error",
                "Max clip",
                "Flags",
            ],
            loc="center",
            cellLoc="left",
            colLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.35)
        for (row_index, _column_index), cell in table.get_celld().items():
            cell.set_edgecolor(palette.line)
            if row_index == 0:
                cell.set_facecolor(palette.panel)
                cell.set_text_props(color=palette.ink, weight="bold")
                continue
            cell.set_facecolor(row_colours[row_index - 1])
            cell.set_text_props(color=palette.ink)
        fig.tight_layout()
        fig.savefig(path, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)


def _write_symbol_png(
    plt: Any,
    path: Path,
    symbol: str,
    payload: dict[str, Any],
    holdout_rows: tuple[CalibrationDiagnosticRow, ...],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    fig, axes = plt.subplots(
        3,
        2,
        figsize=(settings.plot.symbol_width_inches, settings.plot.symbol_height_inches),
        dpi=settings.plot.dpi,
    )
    try:
        fig.patch.set_facecolor(palette.paper)
        for axis in axes.flat:
            axis.set_facecolor(palette.panel)
            axis.tick_params(colors=palette.muted, labelsize=7)
            for spine in axis.spines.values():
                spine.set_color(palette.line)

        fig.suptitle(f"{symbol} Spread Calibration Diagnostics", color=palette.ink, fontsize=14)
        _plot_deciles(axes[0][0], payload, settings)
        _plot_regime_ratios(axes[0][1], payload, "session", settings)
        _plot_regime_ratios(axes[1][0], payload, "volatility", settings)
        _plot_baselines(axes[1][1], payload, settings)
        _plot_saturation(axes[2][0], payload, settings)
        _plot_regression_summary(axes[2][1], payload, holdout_rows, settings)
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(path, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)


def _plot_deciles(axis: Any, payload: dict[str, Any], settings: SpreadCalibrationDiagnosticsSettings) -> None:
    palette = settings.palette
    deciles = payload["deciles"]["effective_runtime_prediction"]["rows"]
    labels = [row["bucket"] for row in deciles]
    predicted = [row["mean_predicted_half_spread"] for row in deciles]
    observed = [row["mean_observed_half_spread"] for row in deciles]
    positions = list(range(len(labels)))
    axis.plot(positions, predicted, color=palette.accent, marker="o", label="predicted")
    axis.plot(positions, observed, color=palette.negative, marker="o", label="observed")
    axis.set_title("Deciles", color=palette.ink, fontsize=10)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=45, ha="right")
    axis.legend(fontsize=7, frameon=False)


def _plot_regime_ratios(
    axis: Any,
    payload: dict[str, Any],
    regime_name: str,
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    rows = payload["regimes"][regime_name]["rows"]
    labels = [row["bucket"] for row in rows]
    ratios = [row["geometric_mean_ratio"] for row in rows]
    axis.bar(labels, ratios, color=palette.accent)
    axis.axhline(1.0, color=palette.line, linewidth=1)
    axis.set_title(f"{regime_name.title()} Ratio", color=palette.ink, fontsize=10)
    axis.tick_params(axis="x", rotation=30)


def _plot_baselines(
    axis: Any,
    payload: dict[str, Any],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    comparison = payload["baseline_comparison"]
    labels = list(comparison)
    mae_values = [comparison[label]["mae_log"] for label in labels]
    axis.bar(labels, mae_values, color=[palette.accent, palette.muted, palette.amber, palette.line])
    axis.set_title("Holdout Baselines MAE", color=palette.ink, fontsize=10)
    axis.tick_params(axis="x", rotation=35)


def _plot_saturation(
    axis: Any,
    payload: dict[str, Any],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    saturation = payload["saturation"]
    labels = ["min clip", "max clip", "target floor"]
    values = [
        saturation["min_clip_rate"],
        saturation["max_clip_rate"],
        saturation["target_floor_rate"],
    ]
    axis.bar(labels, values, color=[palette.muted, palette.negative, palette.amber])
    axis.set_ylim(0.0, max(1.0, max(values, default=0.0)))
    axis.set_title("Saturation", color=palette.ink, fontsize=10)
    axis.yaxis.set_major_formatter(lambda value, _position: f"{value:.0%}")


def _plot_regression_summary(
    axis: Any,
    payload: dict[str, Any],
    holdout_rows: tuple[CalibrationDiagnosticRow, ...],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> None:
    palette = settings.palette
    predicted = [row.effective_predicted for row in holdout_rows]
    observed = [row.observed_effective for row in holdout_rows]
    axis.scatter(predicted, observed, color=palette.accent, s=18)
    lower = min([*predicted, *observed])
    upper = max([*predicted, *observed])
    axis.plot([lower, upper], [lower, upper], color=palette.line, linewidth=1)
    regression = payload["holdout"]["effective_runtime_prediction"]
    r2 = regression["r2_log"]
    rank_corr = regression["rank_corr"]
    text = [
        f"r2_log: {_metric_text(r2)}",
        f"rank_corr: {_metric_text(rank_corr)}",
        f"mean_log_error: {regression['mean_log_error']:.4f}",
    ]
    axis.text(
        0.02,
        0.98,
        "\n".join(text),
        transform=axis.transAxes,
        va="top",
        color=palette.ink,
        fontsize=8,
    )
    axis.set_title("Regression Summary", color=palette.ink, fontsize=10)
    axis.set_xlabel("Predicted")
    axis.set_ylabel("Observed")


def _metric_text(metric: dict[str, Any]) -> str:
    value = metric["value"]
    if value is None:
        return f"null ({metric['reason']})"
    return f"{value:.4f}"


def _highest_severity(flags: list[dict[str, Any]]) -> str | None:
    if any(flag["severity"] == "review_flag" for flag in flags):
        return "review_flag"
    if any(flag["severity"] == "warning" for flag in flags):
        return "warning"
    return None


def _severity_colour(
    severity: str | None,
    settings: SpreadCalibrationDiagnosticsSettings,
) -> str:
    if severity == "review_flag":
        return settings.palette.negative
    if severity == "warning":
        return settings.palette.amber
    return settings.palette.panel


__all__ = ["diagnostic_symbol_png_name", "write_diagnostic_artifacts"]
