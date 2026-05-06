# Module Map

## Ownership Map

- `src/backtest_engine/core/`
  Stable primitives and shared types.
- `src/backtest_engine/config/`
  Validated settings, run contracts, platform configuration, and YAML-backed
  execution-cost assumptions, including validation for static and dynamic
  spread profile schemas, canonical execution-cost config hashes, dynamic
  spread runtime feature settings, and offline calibration settings/policy
  defaults.
- `src/backtest_engine/domain/`
  Business semantics for strategy-agnostic contracts, markets, execution,
  portfolio, and artifacts.
  Execution owns pure order-economics, instrument-metadata, commission, spread,
  dynamic spread evaluation, slippage, and combined preview contracts; it must
  not import Nautilus or other infrastructure.
- `src/backtest_engine/strategies/`
  Concrete strategy cartridges discovered by `implementation_id`. Each
  strategy folder owns its parameters, optional pure policy modules, Nautilus
  wrapper, local docs, and local tests.
- `src/backtest_engine/application/`
  Use-cases for single runs, portfolios, batches, studies, scenarios,
  baselines, market-data orchestration, and offline calibration. Calibration
  owns local EDGE estimation, ex-ante target/feature panel construction from
  verified normalized OHLCV data, and generated execution-cost YAML/report/PNG
  diagnostics publication from an existing Phase 1 panel. Calibration includes
  normalized-artifact provenance, explicit volume-coverage validation,
  train/holdout publication splits, panel conversion-unit validation,
  liquidity volume-semantics gating, fit convergence checks, canonical
  execution-cost config hashing, publication artifact identity keyed by
  target/settings/base-config/symbol-map inputs, duplicate canonical-symbol
  alias rejection, deterministic holdout diagnostics over raw and clipped
  predictions, train-derived baseline comparisons, report-only heuristic flags,
  and must not be wired into Nautilus runtime execution.
- `src/backtest_engine/infrastructure/`
  Nautilus, historical-data providers, storage, study persistence, and
  observability adapters. Nautilus infrastructure also owns execution-policy
  compilation into importable fee/fill model payloads keyed by `instrument_id`
  and dynamic spread feature artifact generation when a policy-present run
  resolves a dynamic spread model with hash-anchored config provenance.
  Nautilus report persistence also owns the versioned
  `synthetic_fill_diagnostics.json` artifact and stable
  `synthetic_fill_diagnostics` report key.
- `src/backtest_engine/analytics/`
  Derived read models over persisted bundles, saved-bundle dashboard artifacts,
  study artifacts, and recommendations.
- `src/backtest_engine/interfaces/`
  CLI, terminal UI, worker delivery surfaces, and run-profile file parsing.
- `src/backtest_engine/bootstrap/`
  Dependency assembly and default application containers.

## Add Code By Intent

- stable primitive or shared type -> `core/`
- validated run contract or settings model -> `config/`
- strategy-agnostic policy or signal contract -> `domain/strategy/`
- concrete strategy implementation -> `strategies/<implementation_id>/`
- portfolio planning or sizing semantics -> `domain/portfolio/`
- execution truth contract -> `domain/execution/`
- orchestration or use-case flow -> `application/`
- Nautilus, filesystem, data, or external adapter -> `infrastructure/`
- delivery adapter or request translation -> `interfaces/`
- dependency wiring -> `bootstrap/composition_root.py`

## Delivery Surfaces

- `interfaces/cli/`
  Typed request translation into application commands, including the runnable
  backtest CLI under `interfaces/cli/backtest/`, the market-data CLI under
  `interfaces/cli/market_data/`, and the calibration CLI under
  `interfaces/cli/calibration/`. The backtest CLI owns the operator handoff for
  generated execution-cost YAML paths and validates the run-profile hash before
  the Nautilus compiler is built.
- `interfaces/run_profiles/`
  YAML/TOML operator launch specs parsed into the canonical `BacktestRunSpec`.
  This package owns the public `RunProfile` file schema and must not import
  Nautilus runtime adapters or concrete strategy cartridges.
- `interfaces/terminal_ui/`
  FastAPI app, saved-bundle dashboard HTML, bundle reads, study reads,
  recommendation reads, and scenario rerun planning.
- `interfaces/workers/`
  Background scenario rerun adapter over canonical portfolio orchestration.

## Execution Flows

Single run:

```text
backtest CLI or library caller
-> application.single.run_single_backtest
-> infrastructure.data.parquet_normalizer
-> infrastructure.nautilus.catalogs
-> infrastructure.nautilus.run_spec_compiler
   (execution_policy -> importable fee/fill configs when present;
    dynamic spread profiles -> strict-lagged feature artifacts)
-> infrastructure.nautilus.strategy_package_resolver
-> strategies.<implementation_id>
-> infrastructure.nautilus.runner
-> infrastructure.nautilus.reports
   (runtime reports + synthetic_fill_diagnostics.json)
-> application.single.export_single_bundle
-> infrastructure.artifacts.artifact_store
```

Portfolio run:

```text
backtest CLI, worker, or library caller
-> application.portfolio.build_portfolio_plan
-> application.portfolio.run_portfolio_backtest
-> infrastructure.data.parquet_normalizer
-> infrastructure.nautilus.catalogs
-> infrastructure.nautilus.run_spec_compiler
   (execution_policy -> importable fee/fill configs when present;
    dynamic spread profiles -> strict-lagged feature artifacts)
-> infrastructure.nautilus.strategy_package_resolver
-> strategies.<implementation_id>
-> infrastructure.nautilus.runner
-> infrastructure.nautilus.reports
   (runtime reports + synthetic_fill_diagnostics.json)
-> infrastructure.nautilus.portfolio_projection
-> application.portfolio.export_portfolio_bundle
```

Terminal UI read flow:

```text
terminal UI route
-> interfaces.terminal_ui.query_service or read_* adapter
-> bootstrap.composition_root.ApplicationContainer
-> analytics.read_models
-> infrastructure.artifacts.bundle_loader or infrastructure.optimization.study_store
```

Saved-bundle dashboard flow:

```text
terminal UI route
-> interfaces.terminal_ui.query_service
-> bootstrap.composition_root.ApplicationContainer
-> analytics.read_models.bundle_dashboard
-> infrastructure.artifacts.bundle_loader
-> parquet artifact paths declared by ResultBundle.artifact_locations
```

Historical market-data flow:

```text
market_data CLI
-> interfaces.cli.market_data.parsing
-> application.market_data.HistoricalMarketDataService
-> infrastructure.data.ib or infrastructure.data.mt5
-> FilesystemHistoricalDataStore
-> interfaces.cli.market_data.rendering and diagnostics
```

Backtest dry-run flow:

```text
backtest CLI
-> interfaces.run_profiles.load_run_profile_spec
-> optional execution-cost YAML hash preflight when --execution-costs-path is used
-> application.backtests.dry_run_backtest
-> infrastructure.data.parquet_normalizer
-> infrastructure.nautilus.catalogs
-> infrastructure.nautilus.run_spec_compiler
-> infrastructure.nautilus.strategy_package_resolver
-> strategies.<implementation_id>
-> interfaces.cli.backtest.rendering and diagnostics
```

Calibration flow:

```text
calibration CLI
-> interfaces.run_profiles.load_run_profile_spec
-> bootstrap.composition_root.build_calibration_dataset_materializer
-> infrastructure.data.parquet_normalizer
-> application.calibration.build_spread_calibration_panel
-> application.calibration.publish_spread_calibration
-> generated execution_costs.yaml, calibration_report.json, calibration_panel.parquet,
   calibration_diagnostics_summary.png, calibration_diagnostics_<symbol>_<hash>.png
-> interfaces.cli.calibration.rendering
```

Provider-managed source slices keep:

- canonical-symbol storage paths with provider-symbol metadata in manifests
- partial source parquet plus `checkpoint.json` for resumable backfills
- calendar and session metadata used by validation
- app-owned market-data DTOs at the application boundary
- IB raw-contract lineage plus roll manifests for additive futures audits

## Persistence Layout

- result bundles -> `results/<bundle_id>/bundle.json`
- study artifacts -> `results/studies/...`
- recommendation artifacts -> `results/recommendations/...`
- Nautilus runtime artifacts -> `var/runtime/nautilus/<run_id>/`
- synthetic fill diagnostics ->
  `var/runtime/nautilus/<run_id>/artifacts/synthetic_fill_diagnostics.json`
- spread calibration bundles ->
  `var/runtime/calibration/<calibration_id>/<publication_id>/`

## Documentation Rule

When ownership changes, update both the nearest package `README.md` and the
relevant canonical document in `docs/`.
