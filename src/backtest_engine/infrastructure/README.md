# Infrastructure

## Ownership

Owns Nautilus integration, storage, market-data adapters, study persistence,
observability adapters, and strategy package resolution at the runtime
boundary.

## May Import

- `core`
- `config`
- `domain`

## Must Never Import

- `interfaces`
- delivery-specific presentation code

## Public Surface

- parquet cache resolution and normalized dataset materialization
- provider-managed historical-data storage, validation, and ingestion adapters
  under `infrastructure/data/`
- IB contract-chain resolution, roll manifests, and raw-contract audit support
- Nautilus run-spec compilation, catalog preparation, and runner adapters
- policy-present execution-cost wiring into Nautilus importable fee/fill models
  keyed by `instrument_id`
- Nautilus runtime report persistence, including the versioned
  `synthetic_fill_diagnostics.json` audit artifact
- package-backed Nautilus strategy resolution from `StrategySpec.implementation_id`
- artifact storage and filesystem bundle persistence/load adapters
- study artifact store implementations
- structured diagnostics and logging adapters

## Bar Timestamp Contract

`infrastructure.data.parquet_normalizer` owns the canonical `ts_event_utc`
semantic: source/provider bar open timestamp normalized to UTC, with no
completed-bar close shift. Nautilus catalog builders receive this already
canonical timestamp and preserve it for strategy replay.

## Execution Policy Wiring

When `BacktestRunSpec.execution_policy` is `None`, Nautilus runs keep the
legacy baseline: no execution-cost YAML load, no venue override application, no
fill model, no fee model, and no latency model. When the policy is present,
`infrastructure.nautilus.run_spec_compiler` resolves the bundled
execution-cost profile against symbol-map metadata and emits one per-venue
importable fee model and fill model config keyed by Nautilus `instrument_id`.
`infrastructure.nautilus.runner` only adapts those compiled DTOs into Nautilus
`ImportableFeeModelConfig` and `ImportableFillModelConfig`.

If an injected execution-cost YAML resolves a
`log_linear_dynamic_half_spread` model, `run_spec_compiler` requires the
run-spec execution-cost reference to carry `config_content_hash` matching the
validated YAML's canonical hash. Dynamic profiles also require matching
symbol, venue, and timeframe provenance before artifact generation.

Dynamic runtime settings are config-owned and explicit: volatility uses
`true_range_atr` over prior completed bars, the volatility floor is
`volatility_floor_price` from config rather than instrument `tick_size`, and
`dynamic_order_types` is currently fixed to `[market]`. The compiler writes
lagged OHLCV feature artifacts under
`var/runtime/nautilus/<run_id>/dynamic_spread_features/`. Manifest
`feature_table_path` values are relative to the manifest directory; the
importable fill-model config keeps absolute artifact references. Feature rows
preserve the domain invariant
`feature_observed_at_utc < fill_timestamp_utc`. Because normalized bar
timestamps are bar opens, feature availability is represented as previous-bar
close minus one microsecond. Static-policy runs do not build those artifacts.

The custom adapters live in `infrastructure.nautilus.execution_models`. They
convert Nautilus runtime objects into primitive/domain inputs before calling
the pure execution contracts. Dynamic feature tables are loaded once by the
fill model and used only for dynamic market-order spread previews. Runtime
MARKET fills must match an exact compiled feature row timestamp; off-grid fills
and fills outside artifact coverage fail closed instead of reusing stale feature
inputs. Dynamic stop-market fills return to Nautilus' default path until stop
trigger/fill timestamps are enabled by the typed runtime policy. For MARKET
orders submitted from `on_bar(...)`, the characterized fill-simulation timestamp
source is the order's nonzero `ts_init`; the runtime fails fast instead of
trying fallback timestamp attributes. Latency remains intentionally unwired.

## Synthetic Fill Diagnostics

`infrastructure.nautilus.reports.NautilusReportWriter` writes
`synthetic_fill_diagnostics.json` under each run artifact root and exposes it
through the stable `synthetic_fill_diagnostics` report key. Saved result bundles
inherit that key through `artifact_locations`.

The diagnostics builder consumes persisted report frames, explicit compiled run
DTO fields, normalized bar paths carried by `NautilusDataSpec`, and dynamic
feature artifact references from the compiled fill-model config. It does not
inspect strategy internals or use hidden runtime state. No-policy and static
policy runs preserve runtime behavior and emit `not_applicable` diagnostics.
Dynamic runs report row-level classification, feature coverage, and
outside-OHLC checks without clamping fills.

## Add Code Here

- filesystem adapters
- broker or market-data integrations
- Nautilus runtime adapters
- strategy package resolver logic; concrete strategy wrappers live under
  `src/backtest_engine/strategies/<implementation_id>/`
- persisted artifact or study store implementations
- observability adapters

## Verification

- adapter-focused unit tests under `tests/unit/infrastructure/`
- integration tests under `tests/integration/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Import Rules](../../../docs/IMPORT_RULES.md)
