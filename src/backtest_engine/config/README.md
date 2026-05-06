# Config

## Ownership

Owns validated immutable settings, platform configuration, and the canonical
`BacktestRunSpec`.

## May import

- `core`
- stable domain contracts used in validated schemas

## Must never import

- `interfaces`
- delivery-only request models

## Public Surface

- runtime settings and run contract
- data, IB, MT5, portfolio, optimization, and UI settings
- root platform settings loader
- declarative execution policy references on `BacktestRunSpec`
- execution-cost profile loader for validated commission, spread, dynamic
  spread, and slippage assumptions
- offline calibration settings models for Phase 1 panel construction and
  Phase 2 publication policy knobs

## Add Code Here

- validated settings model
- environment-backed configuration
- immutable execution contract field or derived config rule
- YAML-backed execution-cost assumptions that stay separate from instrument
  identity metadata

## Execution Policy

`BacktestRunSpec.execution_policy` is an optional declarative contract. `None`
preserves the current runtime behavior. A non-null policy records the selected
execution-cost profile (`default_execution_costs`), an optional
`config_content_hash`, plus optional venue override intent and participates in
`content_hash` / `run_id`.

This layer does not import or construct Nautilus `FillModel`, fee engines,
latency models, or venue configs. Policy-present runtime effects are applied by
the Nautilus infrastructure compiler/runner; latency remains intentionally
unwired.

## Execution Costs

`execution_costs.py` validates execution-cost profiles loaded from YAML or
in-memory fixtures. The spread schema includes the pure
`log_linear_dynamic_half_spread` contract, including session buckets and
calibration provenance, because final profile resolution lives at this config
boundary. Dynamic spread provenance is symbol-specific; resolving a profile for
another symbol is rejected instead of silently reusing calibration.

The bundled `execution_costs.yaml` intentionally remains on static spread
models. Dynamic spread parameters can be proven with injected execution-cost
YAML using the existing policy profile reference, not inline cost payloads.
Custom execution-cost YAML must be anchored by
`execution_policy.execution_costs.config_content_hash`, which is compared to
the validated config's canonical hash before compilation. That hash is part of
the run identity, so two dynamic YAML contents cannot share a
`BacktestRunSpec.content_hash`.

Dynamic YAML must include `dynamic_spread_runtime` when any resolved profile
uses `log_linear_dynamic_half_spread`. The runtime profile names
`volatility_signal_method: true_range_atr`, an explicit positive
`volatility_floor_price`, `volume_floor`, feature windows, `dynamic_order_types`
currently fixed to `[market]`, and UTC session buckets. The volatility floor is
configuration, not `tick_size`. UTC session bucket times are naive `HH:MM:SS`
values; timezone-suffixed values such as `13:30:00Z` are rejected at config
validation. Nautilus infrastructure owns artifact generation and runtime lookup.

Operator-facing dynamic spread handoff rules live in
[`USAGE/microstructure-calibration.md`](../../../USAGE/microstructure-calibration.md).
The calibration CLI publishes generated execution-cost YAML from verified
market data, and the backtest CLI accepts that generated file through
`--execution-costs-path` only when the run profile carries the matching
`config_content_hash`.

## Calibration Settings

`calibration.py` owns validated defaults for offline spread calibration. These
settings are separate from `execution_costs.yaml`: calibration settings control
how a generated profile is fit and published, while execution-cost YAML is the
runtime input/output contract consumed by backtests.

The settings include EDGE panel defaults, dynamic feature windows/floors,
publication split parameters, tick-floor policy, fit convergence tolerance and
iteration cap, mixed-asset-class override, cross-timeframe dynamic-weight
override, and explicit volume semantics required before liquidity weights can
be fit. Calibration diagnostics load their threshold policy, status levels,
plot palette, decile count, and low/mid/high regime labels from
`calibration_diagnostics.yaml`; those thresholds are internal report-only
heuristics, not statistical acceptance tests. Calibration's default validator
ruleset is imported from the shared core market-data validation identity used
by infrastructure verification, so fresh/stale manifest checks cannot drift
between layers.

## Verification

- `tests/unit/config/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Import Rules](../../../docs/IMPORT_RULES.md)
