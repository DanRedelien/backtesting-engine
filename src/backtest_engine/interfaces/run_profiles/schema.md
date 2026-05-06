# Run Profile Schema

Run profiles are operator-facing launch specs. They are parsed at the
`interfaces/run_profiles` boundary and translated directly into the canonical
`BacktestRunSpec`. They are not a replacement configuration system and they do
not introduce a second runtime contract.

Supported file suffixes:

- `.yaml`
- `.yml`
- `.toml`

YAML input must contain exactly one document. YAML and TOML documents must be a
non-empty top-level mapping. Profile files are capped at 1 MiB because they are
small launch documents, not bulk data.

## Generated Schema

Machine-readable schema lives in
[`docs/generated/run_profile.schema.json`](../../../../docs/generated/run_profile.schema.json).
It is generated from `RunProfile.model_json_schema()` and must not be edited by
hand.

Regenerate after changing the run-profile Pydantic contract:

```bash
python -m tools.generate_run_profile_schema
```

Check drift without writing:

```bash
python -m tools.generate_run_profile_schema --check
```

The generated JSON Schema is a derived artifact for tooling and field-level
structure. The Pydantic loader remains the source of truth because it also
enforces custom validators, canonical `BacktestRunSpec` validation, and
cross-field rules that JSON Schema cannot fully express.

## Top-Level Fields

```text
run_kind: "single" | "portfolio"
execution_window: RunProfileExecutionWindow
dataset: RunProfileDataset
capital_base: Money
strategies: non-empty list[RunProfileStrategySlot]
portfolio_policy: PortfolioExecutionPolicy | null = null
execution_policy: BacktestExecutionPolicy | null = null
runtime_boundary: RuntimeBoundary = "nautilus"
semantic_policy_version: non-empty string = "v1"
tags: list[non-empty string] = []
```

All profile models use Pydantic with `extra="forbid"`. Unknown top-level or
nested fields fail fast.

## Execution Window

```text
start_utc: timezone-aware datetime
end_utc: timezone-aware datetime
```

The profile layer rejects naive datetimes because the field names are explicit
UTC boundary names. Aware non-UTC values are accepted and normalized by
`ExecutionWindow` when the canonical `BacktestRunSpec` is built.

## Dataset

```text
source_system: "ib" | "mt5" | "parquet" | "synthetic"
normalization_policy: non-empty string
schema_version: non-empty string
symbol_universe: non-empty list[Symbol]
timeframe: non-empty string
dataset_version: non-empty string
```

`symbol_universe` values are stripped by the canonical non-empty string type and
must be unique after stripping. Symbols are not uppercased or repaired.

## Strategy Slots

```text
slot_id: non-empty string
weight_frac: float in [0.0, 1.0]
strategy_id: non-empty string
implementation_id: ^[a-z][a-z0-9_]*$
policy_version: non-empty string = "v1"
legs: non-empty list[Symbol]
parameters: JSON-compatible object = {}
```

`implementation_id` is the only strategy cartridge reference allowed in a run
profile. Do not expose Python module names, class names, `strategy_path`,
`config_path`, registry keys, or cartridge imports in YAML/TOML.

The loader syntax-checks `implementation_id` only. It does not validate whether
the cartridge exists and it does not import concrete strategies. The package
resolver validates existence, leg-count support, and cartridge parameters later
during dry-run or execution.

`parameters` contains only external operator knobs. Do not include derived
bindings such as `symbol`, `leg_symbols`, or `strategy_id`; cartridge builders
derive those values from `PortfolioStrategySpec`.

Parameter values must be JSON-compatible exact Python values:

- `str`
- `int`
- finite `float`
- `bool`
- `null`
- `list[...]`
- `dict[str, ...]`

The loader rejects datetimes, dates, tuples, decimals, non-string dictionary
keys, `NaN`, infinities, and arbitrary objects instead of coercing them.

## Execution Policy

```text
execution_costs:
  profile_id: "default_execution_costs"
  config_content_hash: str | null = null
venue_overrides: ExecutionVenueOverrides | null = null
```

`execution_policy` is optional. `null` and omission both preserve the legacy
runtime behavior: no explicit Nautilus fill model, fee engine, latency model,
or venue override application is selected by the run profile.

When present, the policy is captured in `BacktestRunSpec`, serialized, included
in `content_hash` / `run_id`, and applied by the Nautilus infrastructure
compiler. The compiler resolves the selected bundled profile per Nautilus
`instrument_id`, applies venue overrides field-by-field over the legacy
defaults, and leaves latency unwired.

`execution_costs.profile_id` references the selected execution-cost assumptions
profile. It must be exactly `default_execution_costs`; run profiles must not
inline commission, spread, or slippage payloads.

`execution_costs.config_content_hash` is optional for the bundled static
profile path and required when a custom execution-cost YAML is injected into
the Nautilus compiler. Dynamic spread profiles also require it. The value must
match the canonical hash of the validated execution-cost config and is included
in `BacktestRunSpec.content_hash` / `run_id`.

`venue_overrides` may be omitted, set to `null`, or contain any partial subset
of these exact uppercase literals:

- `oms_type`: `NETTING` or `HEDGING`
- `account_type`: `CASH`, `MARGIN`, or `BETTING`
- `book_type`: `L1_MBP`, `L2_MBP`, or `L3_MBO`

An explicit empty mapping (`venue_overrides: {}`) is invalid because it records
no intent.

## Validation Responsibility

| Layer | Owns |
| --- | --- |
| Run profile loader | supported suffix, file size, one non-empty mapping document, runnable `run_kind`, unknown fields, non-empty lists, duplicate slots/symbols/legs/tags, naive datetimes, JSON-compatible parameter payloads, `implementation_id` syntax, and declarative `execution_policy` shape |
| `BacktestRunSpec` | execution-window ordering, UTC normalization, single-vs-portfolio shape, portfolio-policy placement, portfolio weight sum tolerance, and strategy legs existing in `dataset.symbol_universe` |
| Runtime resolver | cartridge existence, cartridge leg-count support, cartridge parameter validation, compiled config JSON compatibility, Nautilus import paths, and execution-policy runtime wiring |

## Minimal YAML

```yaml
run_kind: single
execution_window:
  start_utc: "2024-01-01T00:00:00Z"
  end_utc: "2024-03-01T00:00:00Z"
dataset:
  source_system: mt5
  normalization_policy: nautilus_v1
  schema_version: "1"
  symbol_universe:
    - EURUSD
  timeframe: 15m
  dataset_version: "2026-04-19"
capital_base:
  amount: "100000"
  currency: USD
execution_policy:
  execution_costs:
    profile_id: default_execution_costs
  venue_overrides:
    oms_type: HEDGING
    account_type: MARGIN
    book_type: L1_MBP
strategies:
  - slot_id: eurusd_sma_pullback
    weight_frac: 1.0
    strategy_id: eurusd_sma_pullback_v1
    implementation_id: sma_pullback
    policy_version: v1
    legs:
      - EURUSD
    parameters:
      fast_sma_window: 50
      slow_sma_window: 200
      atr_window: 14
      atr_sl_mult: 2.0
      rr_ratio: 3.0
      trade_direction: both
tags:
  - example
  - fx
```

Example profiles live under repository-root `run_profiles/`.
