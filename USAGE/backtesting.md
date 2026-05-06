# Backtesting

This page is a current-state guide, not the finished operator runbook.

The repository exposes canonical single-run, portfolio-run, batch, and scenario
orchestration through typed Python entrypoints and CLI adapters. It also exposes
YAML/TOML run profiles that load into `BacktestRunSpec`, plus an operator CLI
for dry-run preparation and real single and portfolio backtest runs.

## Current Public Surface

- typed application assembly through
  `backtest_engine.bootstrap.composition_root.build_application_container(...)`
- typed CLI adapter functions under `backtest_engine.interfaces.cli`
- backtest CLI entrypoint:
  `python -m backtest_engine.interfaces.cli.backtest`
- run-profile loading through
  `backtest_engine.interfaces.run_profiles.load_run_profile_spec(...)`
- terminal UI reads for saved bundles, study summaries, champions, and
  recommendations

Use the repository-root `.env.example` as the reference list for `BTE_`
variables needed by backtest runs. The repository does not load `.env` files
automatically; export the variables in your shell or process manager.

## Backtesting CLI

Run a single-asset profile:

```bash
python -m backtest_engine.interfaces.cli.backtest single \
  --spec run_profiles/fx_single_asset.yaml
```

Prepare the same profile without executing Nautilus:

```bash
python -m backtest_engine.interfaces.cli.backtest single \
  --spec run_profiles/fx_single_asset.yaml \
  --dry-run
```

Run a portfolio profile:

```bash
python -m backtest_engine.interfaces.cli.backtest portfolio \
  --spec run_profiles/three_slot_portfolio.yaml
```

Prepare the portfolio profile without executing Nautilus:

```bash
python -m backtest_engine.interfaces.cli.backtest portfolio \
  --spec run_profiles/three_slot_portfolio.yaml \
  --dry-run
```

If the package is installed, the console script is equivalent:

```bash
bte-backtest single --spec run_profiles/fx_single_asset.yaml
bte-backtest single --spec run_profiles/fx_single_asset.yaml --dry-run
bte-backtest portfolio --spec run_profiles/three_slot_portfolio.yaml
bte-backtest portfolio --spec run_profiles/three_slot_portfolio.yaml --dry-run
```

The CLI loads specs only through `load_run_profile_spec(...)`. `single` accepts
only `run_kind: single`; `portfolio` accepts only `run_kind: portfolio`.

When a run profile uses a generated calibration hash, pass the matching
execution-cost YAML explicitly:

```bash
python -m backtest_engine.interfaces.cli.backtest single \
  --spec run_profiles/fx_single_asset.yaml \
  --execution-costs-path var/runtime/calibration/.../execution_costs.yaml
```

The path works for both `single` and `portfolio`. The CLI fails before running
when the profile is missing
`execution_policy.execution_costs.config_content_hash` or when that hash does
not match the YAML. Generate the YAML and snippet with
[Microstructure Calibration](microstructure-calibration.md).

Dry-run validates the profile, builds the canonical `BacktestRunSpec`,
materializes or reuses the normalized dataset cache, builds or reuses the
Nautilus catalog cache, and resolves strategy cartridges by
`implementation_id`. It does not create a Nautilus `BacktestNode`, run a
backtest, save result bundles, persist reports, or create fills, orders,
positions, or account report files.

Exit codes:

- `0` successful run or dry-run
- `1` typed profile, validation, application, or infrastructure failure
- `2` argparse usage error or missing subcommand

## Inspecting Saved Bundles

Successful backtest runs persist saved bundles under
`results/<bundle_id>/bundle.json` with runtime report artifact locations. Use the
dashboard launch and route instructions in
[Install and Terminal Preparation](install.md#saved-bundle-dashboard) to inspect
the newest loadable bundle or open a specific bundle.

The dashboard is read-only. It renders stats, strategy correlation, equity, and
drawdown from saved bundle artifacts only. If the current artifacts do not
contain stable per-strategy realized return or realized PnL observations, the
strategy-correlation panel reports the missing artifact requirement instead of
inferring correlation from aggregate returns.

## Single-Asset Backtesting

Current truth:

- canonical single-run behavior is owned by
  `application.single.run_single_backtest`
- the delivery-facing adapter is
  `interfaces.cli.run_single_backtest.run_single_backtest_cli`
- `run_profiles/fx_single_asset.yaml` is a schema-valid launch profile that
  loads into `BacktestRunSpec`
- the operator command is
  `python -m backtest_engine.interfaces.cli.backtest single --spec <path>`

## Statarb Backtesting

Current truth:

- statarb behavior is implemented through the canonical strategy and portfolio
  run contracts, not through a separate legacy runtime path
- portfolio-oriented orchestration is owned by
  `application.portfolio.run_portfolio_backtest`
- `run_profiles/fx_statarb_pair.yaml` is a schema-valid one-slot statarb launch
  profile that loads into `BacktestRunSpec`
- `run_profiles/fx_statarb_pair.yaml` uses `run_kind: single` and runs through
  the `single` subcommand; portfolio statarb profiles use `portfolio` when
  their `run_kind` is `portfolio`

TODO:

- add one statarb-focused operator example
- document required dataset and strategy inputs
- document expected allocation and position outputs

## Portfolio Backtesting

Current truth:

- canonical portfolio-run behavior is owned by
  `application.portfolio.run_portfolio_backtest`
- the delivery-facing adapter is
  `interfaces.cli.run_portfolio_backtest.run_portfolio_backtest_cli`
- scenario reruns reuse canonical portfolio orchestration
- `run_profiles/three_slot_portfolio.yaml` is a schema-valid portfolio launch
  profile that loads into `BacktestRunSpec`
- the operator command is
  `python -m backtest_engine.interfaces.cli.backtest portfolio --spec <path>`

## Loading A Profile In Python

Profiles can also be validated and translated in Python without starting a
run:

```python
from pathlib import Path

from backtest_engine.interfaces.run_profiles import load_run_profile_spec

run_spec = load_run_profile_spec(Path("run_profiles/fx_single_asset.yaml"))
```

The returned object is the canonical `BacktestRunSpec`; no runner is invoked by
the profile loader.

## Related Guides

- [Install and Terminal Preparation](install.md)
- [Historical Market Data](market-data.md)
- [WFO Optimization](wfo.md)
