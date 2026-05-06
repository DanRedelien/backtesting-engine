# Architecture

## System Shape

The system is a modular monolith with strict dependency direction:

```text
interfaces -> application -> domain -> core
bootstrap  -> application -> domain -> core
bootstrap  -> infrastructure -> domain -> core
application -> infrastructure
infrastructure -> strategies -> domain -> core
analytics -> domain -> core
analytics -> infrastructure.artifacts (read-only)
```

## Canonical Execution Flow

```text
delivery surface
-> application use-case
   (offline calibration jobs stay here and produce frozen inputs for later runs)
-> provider-managed market-data source slices
   (checkpointed download + calendar-aware verify when needed)
-> infrastructure Nautilus runtime
   (strategy package resolver -> concrete strategy cartridge)
-> domain artifact contract
-> infrastructure artifact store
-> analytics read models
```

## Non-Negotiable Choices

- Nautilus is the only execution runtime boundary.
- `BacktestRunSpec` is the canonical execution contract.
- `bootstrap/composition_root.py` is the only composition root.
- Delivery adapters do not own business truth.
- Result bundles and runtime artifacts are explicit persisted contracts.
- Portfolio, study, and scenario flows reuse canonical orchestration instead of
  defining parallel execution semantics.

## Bar Timestamp Contract

Canonical `ts_event_utc` is the source/provider bar open timestamp normalized
to UTC, with no completed-bar close shift. The owning layer is
`infrastructure.data.parquet_normalizer`; Nautilus catalog construction and
strategy runtime consumers must preserve that semantic and must not apply a
second shift. The contract is enforced by
`test_mt5_client_preserves_rate_time_as_event_time_without_close_shift`,
`test_parquet_normalizer_preserves_source_timestamps_without_close_shift`,
`test_nautilus_bar_data_wrangler_preserves_frame_index_as_bar_event_time`,
and
`test_strategy_bar_replay_observes_open_event_timestamps_without_future_bar`.

## Execution Policy Contract

`BacktestRunSpec.execution_policy` is the optional declarative surface for
execution-realism intent. When it is absent or `null`, runs preserve the current
runtime behavior: no explicit Nautilus fill model, fee engine, latency model,
or venue override application, and the bundled execution-cost YAML is not read.
When it is present, the Nautilus compiler resolves the selected bundled
execution-cost profile per catalog instrument, keys the payload by Nautilus
`instrument_id`, applies venue overrides field-by-field over the legacy
defaults, and emits importable custom fee/fill model configs for the runner.
Latency remains intentionally unwired.

Dynamic spread realism remains opt-in through the execution-cost YAML selected
by the existing policy reference. The bundled `default_execution_costs` profile
still uses static spread models. If a policy-present run resolves a
`log_linear_dynamic_half_spread` model from an injected execution-cost YAML,
the run spec must carry `execution_costs.config_content_hash` matching the
validated YAML's canonical hash; that hash participates in
`content_hash` / `run_id`. The Nautilus compiler also requires dynamic
provenance to match catalog symbol, venue, and timeframe before artifact
generation.

Dynamic runtime feature generation uses `true_range_atr` over prior completed
bars, an explicit positive `volatility_floor_price` from config, and
`dynamic_order_types` currently fixed to MARKET only. The compiler builds
strict-lagged OHLCV feature artifacts from normalized `bars.parquet`, stores
manifest table paths relative to the manifest directory, and passes importable
absolute artifact references into the fill model. Because canonical bar
timestamps are bar opens, dynamic feature availability is encoded as
previous-bar close minus one microsecond, preserving the strict domain
invariant `feature_observed_at_utc < fill_timestamp_utc`. MARKET dynamic
fills use the characterized nonzero Nautilus order `ts_init`; STOP_MARKET and
trailing stop dynamic fills stay on Nautilus' default path until enabled by the
typed runtime policy.

Nautilus reporting always emits the versioned
`synthetic_fill_diagnostics.json` artifact under the run artifact root and
exposes it through the stable `synthetic_fill_diagnostics` report key. Saved
bundles propagate the same key through `artifact_locations`. The artifact is
owned by `infrastructure.nautilus.reports` and
`infrastructure.nautilus.synthetic_fill_diagnostics`; it consumes persisted
reports, compiled run DTOs, normalized bar paths, and dynamic feature artifact
references, not strategy internals or hidden runtime state.

## Bounded Contexts

- `core`
  Tiny stable primitives, value types, identifiers, enums, and shared errors.
- `config`
  Validated immutable settings and run contracts.
- `domain`
  Market, strategy-agnostic contracts, execution, portfolio, and artifact
  semantics.
- `strategies`
  Concrete strategy cartridges keyed by `StrategySpec.implementation_id`.
  Each folder owns its parameter model, pure policy code, Nautilus wrapper,
  docs, and local tests.
- `application`
  Use-cases and orchestration across single, portfolio, batch, optimization,
  scenario, baseline, market-data download/verify, and offline calibration
  flows. EDGE-based spread calibration is an explicit pre-backtest use-case
  that reads verified normalized OHLCV data, builds ex-ante target/feature
  panels, fits the runtime `log_linear_dynamic_half_spread` surface, and
  publishes generated execution-cost YAML plus calibration reports and
  diagnostics PNGs. It fails closed on stale source, validation,
  normalized-artifact provenance, invalid panel unit conversion, invalid
  publication splits, untrusted liquidity volume semantics, duplicate
  symbol-map aliases that would merge inputs into one canonical execution
  symbol, fit non-convergence, or YAML validation failures, and it does not run
  inside Nautilus execution or inspect strategy results. Diagnostics compare
  raw model predictions with clipped runtime predictions, report train-derived
  baselines on holdout rows, and emit internal heuristic flags that never block
  publication. Publication output directories are keyed by target/settings,
  validated base execution-cost config hash, and symbol-map identity.
- `infrastructure`
  Nautilus integration, provider-managed historical-data adapters, storage,
  optimization runtime adapters, and observability.
- `analytics`
  Read models over persisted artifacts only.
- `interfaces`
  CLI, terminal UI, worker delivery adapters, and operator-facing run-profile
  parsing into canonical run specs.
- `bootstrap`
  Dependency wiring and default container assembly.

## Current Operator Surface

- Typed CLI adapter functions under `backtest_engine.interfaces.cli`
- YAML/TOML run-profile loading under
  `backtest_engine.interfaces.run_profiles`, which parses operator launch
  documents into `BacktestRunSpec` without importing Nautilus runtime modules
  or concrete strategy cartridges; optional `execution_policy` blocks are
  passed through as declarative config only
- Unified historical market-data CLI under
  `backtest_engine.interfaces.cli.market_data`
  with paired explicit `--start/--end` windows or provider-resolved
  max-available downloads when both are omitted
- Offline spread calibration CLI under
  `backtest_engine.interfaces.cli.calibration`, which materializes the run
  profile universe at the estimator timeframe, calls the application
  calibration panel/publisher APIs, and prints the generated YAML path,
  diagnostics PNG paths, canonical hash, and run-profile snippet
- Runnable backtest CLI under `backtest_engine.interfaces.cli.backtest`
  (`python -m backtest_engine.interfaces.cli.backtest` or `bte-backtest`) for
  single and portfolio run-profile dry-runs and execution, plus explicit
  `--execution-costs-path` handoff for generated execution-cost YAML when the
  run profile hash matches
- FastAPI terminal UI app under `backtest_engine.interfaces.terminal_ui.app`
- Worker adapter for scenario reruns under `backtest_engine.interfaces.workers`
- Filesystem-backed result bundles under `results/`
- Nautilus runtime payloads and reports under `var/runtime/nautilus/`

Detailed operator workflow, prerequisites, and command examples live in
`USAGE/README.md`.

## Architectural Constraints

- Domain modules do not import infrastructure or interfaces.
- Concrete strategy packages do not import application, bootstrap,
  infrastructure, interfaces, or other concrete strategy packages.
- Core does not import project packages.
- Interfaces do not define execution, portfolio, or artifact truth.
- Analytics reads persisted artifacts but does not define runtime semantics.
- Removed module paths are forbidden import targets anywhere under
  `backtest_engine`.

## Known Limits

- The repository does not currently ship one umbrella launcher for every
  operator flow; market-data and backtest workflows use separate CLI entrypoints.
- `DatasetSource.IB` and `DatasetSource.MT5` datasets require a fresh `PASS`
  validation manifest before materialization into Nautilus datasets.
- Market-data verification must be reproducible from the canonical stored slice
  plus persisted request/source metadata, never from manifest-owned active
  storage pointers.
- `HistoricalMarketDataService`, its providers, and its verifier must share one
  historical-data store instance so verified-slice skips and reported paths
  resolve against the same persisted source of truth.
- MT5 transport interprets provider bar timestamps in the configured broker
  timezone, normalizes them to UTC, and keeps the broker-timezone/session
  metadata in the source manifest for verification and reproducibility.
- IB continuous futures validation depends on both the adjusted slice and the
  saved raw-contract lineage plus roll manifest.
- CI runs the declared repository gates, and failures should be treated as real
  regressions in the current tree.
- Strategy package discovery is cold-process scoped. Adding, removing, or
  renaming a strategy folder is guaranteed after a fresh Python process or fresh
  test session.
