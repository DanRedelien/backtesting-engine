# Microstructure Calibration

Use this guide after you have already installed the project, downloaded and
verified market data with [Historical Market Data](market-data.md), and read the
normal backtest flow in [Backtesting](backtesting.md).

Calibration is needed when a run profile should use frozen, data-derived spread
costs instead of the bundled static execution-cost defaults. It builds an
offline EDGE spread panel from verified OHLCV bars, publishes a generated
`execution_costs.yaml`, and gives you the exact hash snippet to paste into the
run profile.

The bundled `src/backtest_engine/config/execution_costs.yaml` stays static. Do
not edit it for a calibration handoff.

## Run Calibration

Run calibration against the same run profile you plan to backtest. The
`--estimator-timeframe` points to the verified market-data timeframe used for
the EDGE estimator, normally `1m`. The generated YAML is published for the run
profile dataset timeframe.

```bash
python -m backtest_engine.interfaces.cli.calibration spread \
  --spec run_profiles/fx_single_asset.yaml \
  --estimator-timeframe 1m \
  --output-root var/runtime/calibration
```

Expected output shape:

```text
OK spread-calibration
calibration_id: spread-calibration-...
profile_id: default_execution_costs
estimator_timeframe: 1m
target_timeframe: 1h
output_dir: var/runtime/calibration/spread-calibration-.../target-1h-...
execution_costs_yaml: var/runtime/calibration/.../execution_costs.yaml
calibration_report_json: var/runtime/calibration/.../calibration_report.json
calibration_panel_parquet: var/runtime/calibration/.../calibration_panel.parquet
diagnostic_pngs:
  var/runtime/calibration/.../calibration_diagnostics_summary.png
  var/runtime/calibration/.../calibration_diagnostics_EURUSD_<hash>.png
execution_costs_config_hash: <64-character hash>
published_symbols:
  EURUSD
run_profile_snippet:
  execution_policy:
    execution_costs:
      profile_id: default_execution_costs
      config_content_hash: <64-character hash>
backtest_handoff:
  python -m backtest_engine.interfaces.cli.backtest single \
    --spec run_profiles/fx_single_asset.yaml \
    --execution-costs-path var/runtime/calibration/.../execution_costs.yaml
```

If calibration fails, fix the reported input problem first. Common causes are
missing `PASS` market-data verification, a stale validation fingerprint, an
unverified estimator timeframe, too few usable EDGE windows, mixed asset
classes, or symbol-map aliases that would publish two inputs to one execution
symbol.

## Produced Files

The CLI writes one target publication under:

```text
var/runtime/calibration/<calibration_id>/<target_publication_id>/
```

Files:

- `execution_costs.yaml`: generated runtime execution-cost config for the
  backtest CLI.
- `calibration_report.json`: operator report with source references, symbol
  diagnostics, fit settings, the canonical hash, and the run-profile snippet.
  The report schema is `spread_calibration_report.v2`; PNG artifact paths under
  `diagnostic_artifacts` are relative to the report directory.
- `calibration_panel.parquet`: reviewable train, purged, and holdout panel rows.
- `calibration_diagnostics_summary.png`: compact symbol table with core
  holdout metrics and only yellow/red review flags.
- `calibration_diagnostics_<symbol>_<hash>.png`: per-symbol decile, regime,
  baseline, saturation, and regression diagnostics. The short hash keeps
  distinct symbols from colliding after filename sanitization.

Keep these files together. The hash is for the generated `execution_costs.yaml`
content, not for the bundled static config.

## Read Diagnostics

Diagnostics are deterministic audit aids, not an acceptance gate. The publisher
scores both raw model predictions and clipped runtime predictions on log-scale
metrics, then reports `observed / predicted` ratios as secondary context. It
also compares the dynamic runtime prediction against three holdout baselines:
`row_weighted_matched_budget`, `train_static_baseline`, and
`train_bucket_baseline`.

Flags use internal heuristic thresholds from
`src/backtest_engine/config/calibration_diagnostics.yaml`. They are economic
review hints, not statistical tests; for example, a log-bias of `0.05` means
about `exp(0.05)-1`, or 5.1 percent multiplicative bias. Yellow warnings and
red review flags never block `execution_costs.yaml` publication.

## Paste The Snippet

Open the same run profile used in the calibration command and paste or update
only this block:

```yaml
execution_policy:
  execution_costs:
    profile_id: default_execution_costs
    config_content_hash: "<64-character hash from calibration output>"
```

Do not paste the generated YAML into the run profile. The run profile records
the hash; the backtest command passes the generated YAML path.

## Return To Backtesting

Run the handoff command printed by calibration:

```bash
python -m backtest_engine.interfaces.cli.backtest single \
  --spec run_profiles/fx_single_asset.yaml \
  --execution-costs-path var/runtime/calibration/.../execution_costs.yaml
```

For portfolio profiles, use the `portfolio` subcommand:

```bash
python -m backtest_engine.interfaces.cli.backtest portfolio \
  --spec run_profiles/three_slot_portfolio.yaml \
  --execution-costs-path var/runtime/calibration/.../execution_costs.yaml
```

The backtest CLI fails closed when `--execution-costs-path` is present and the
run profile is missing `execution_policy.execution_costs.config_content_hash`,
or when the hash does not match the generated YAML.

Continue with [Backtesting](backtesting.md) for dry-runs, execution, exit codes,
and saved-bundle inspection.

## Advanced Python API

The CLI is the normal operator path. Python callers can use the same application
APIs directly when they already have a verified `MaterializedDataset`:

```python
from pathlib import Path

from backtest_engine.application.calibration import (
    SpreadCalibrationCommand,
    SpreadCalibrationPublicationCommand,
    build_spread_calibration_panel,
    publish_spread_calibration,
)

panel = build_spread_calibration_panel(
    SpreadCalibrationCommand(
        materialized_dataset=materialized_dataset,
        estimator_timeframe="1m",
    )
)

publication = publish_spread_calibration(
    SpreadCalibrationPublicationCommand(
        calibration_result=panel,
        target_timeframe="1h",
        output_root=Path("var/runtime/calibration"),
    )
)
```

The application APIs do not read strategy PnL, Sharpe, trades, alpha
parameters, or portfolio weights. Calibration is an offline market-data
workflow whose output is a frozen runtime input for a later backtest.

## References

- [EDGE project and license](https://github.com/eguidotti/bidask)
- [Python `bidask` docs](https://pypi.org/project/bidask/)
- [R EDGE docs](https://www.rdocumentation.org/packages/bidask/versions/2.1.5/topics/edge)
