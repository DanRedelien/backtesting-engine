# Execution Domain

This package owns pure execution contracts. It must not import Nautilus,
filesystem adapters, run-profile parsing, or other infrastructure modules.

## Phase 1 Realism Contracts

`OrderType.STOP_LIMIT` is a stable domain order type with string value
`stop_limit`. The execution-economics classifier is intentionally conservative:

- `MARKET` and `STOP` are market-like and taker-default.
- `LIMIT` and `STOP_LIMIT` are limit-like and taker-default.
- `LIMIT` and `STOP_LIMIT` do not imply maker or passive fills by default.
  Passive treatment requires an explicit future policy.
- `LIMIT` and `STOP_LIMIT` protect the limit price. Later spread or slippage
  policies must not worsen the effective fill beyond that limit.

`ExecutionInstrumentMetadata` is the lightweight domain metadata contract for
future cost calculations. It carries symbol, instrument type, asset class,
quote currency, tick size, point size, lot size, multiplier, and price
precision. The contract validates positive decimal units but does not calculate
commission, spread, or slippage.

Phase 1 deliberately does not add execution-cost fields to
`nautilus_symbol_map.yaml`, fail-fast fee validation to `symbol_map.py`,
Nautilus `FillModel` wiring, fee-engine wiring, or inline run-profile cost
payloads.

## Phase 2 Commission Contracts

`commissions.py` replaces the placeholder `CommissionModelSpec` with typed,
pure commission contracts:

- `rate_of_notional` charges `commission_rate_bps` against absolute notional.
- `fixed_per_contract` charges `amount_per_contract` in an explicit currency.
- `zero_explicit` is the only valid way to represent zero commission.

`ResolvedExecutionCostProfile` is the final per-symbol profile after applying
an asset-class default and then any symbol override. It validates the selected
commission model and rejects fixed-fee currency mismatches rather than doing
implicit FX conversion.

Commission previews are per symbol/per leg. `preview_commissions_for_legs`
returns one `CommissionPreview` per input leg and does not create a scalar
synthetic-spread commission. Notional calculation stays tied to
`ExecutionInstrumentMetadata`: futures use `quantity * price * multiplier`,
while FX and CFDs use `quantity * price * lot_size * multiplier`.

Execution-cost assumptions are loaded outside this package by
`backtest_engine.config.execution_costs` from `execution_costs.yaml`. This
package remains pure: no Nautilus imports, no YAML or filesystem I/O, and no
runtime state.

Known Phase 2 omissions: broker minimums and fixed-per-order fees. Nautilus
fee-engine wiring is owned by `infrastructure.nautilus`, not this pure domain
package.

## Phase 3 Spread Contracts

`spreads.py` owns deterministic adverse spread previews separately from
commission and slippage. Supported models are:

- `static_half_spread_price` with `half_spread_price` in instrument price units.
- `static_half_spread_ticks` with `half_spread_ticks` converted through
  `ExecutionInstrumentMetadata.tick_size`.
- `buffered_static_spread` with `base_half_spread_price` and an explicit
  positive `buffer_multiplier`.

`ResolvedExecutionCostProfile` contains `commission_model`, `spread_model`,
and, as of Phase 4, `slippage_model` after asset-class defaults and symbol
overrides are resolved. The profile remains a pure domain contract. YAML
loading stays in `backtest_engine.config.execution_costs`.

Spread previews are per symbol/per leg. A BUY receives a positive adverse
price adjustment; a SELL receives a negative adverse price adjustment. MARKET
and STOP orders can apply the full deterministic adjustment. LIMIT and
STOP_LIMIT previews protect the limit price: if the adverse candidate would
make a BUY worse than its limit or a SELL worse than its limit, the preview
returns `blocked_by_limit` with no effective price instead of pretending the
fill is valid.

The preview input explicitly marks the bar reference basis as `LAST-EXTERNAL`.
That is truthful for the current bar data shape: no bid/ask, depth, tick
sequence, missed-fill simulation, or latency model is inferred.

Known Phase 3 omissions: missed-fill simulation and maker/passive spread
semantics. Nautilus `FillModel` wiring is owned by `infrastructure.nautilus`,
not this pure domain package.

## Phase 4A Dynamic Spread Contracts

`spreads.py` also owns the pure `log_linear_dynamic_half_spread` contract for
policy-present runtime wiring. The model is widen-only and evaluates
precomputed ex-ante stress signals:

```text
log_effective =
    ln(base_half_spread_price)
    + volatility_weight * max(0, volatility_stress_signal)
    + liquidity_weight * max(0, liquidity_stress_signal)
    + session_adjustment_log
```

The result is clipped to the configured price-unit
`min_half_spread_price` / `max_half_spread_price` guardrails. Dynamic model
parameters are already in instrument price units; this package does not
convert ticks, points, bps, provider spread fields, or estimator percentages.

`DynamicSpreadFeatureInput` is the runtime evaluation boundary. It carries
`fill_timestamp_utc`, `feature_observed_at_utc`, one
`session_bucket_id`, precomputed volatility/liquidity stress signals, and the
observed liquidity volume scalar used to enforce the zero/missing-volume
policy. Timestamps must be timezone-aware UTC and must satisfy
`feature_observed_at_utc < fill_timestamp_utc`; equality is invalid.

Complete dynamic models require `DynamicSpreadCalibrationProvenance` with
symbol, venue, timeframe, provider/broker, sample window, row count, data
quality notes, sample role, estimator method, and conversion method. Partial
`SpreadModelPatch` objects may omit provenance until inheritance resolution,
but final `validate_spread_model(...)` calls require it. Resolved profiles and
manual dynamic previews also require the provenance symbol to match the
instrument being priced.

`evaluate_dynamic_half_spread(...)` returns a `DynamicSpreadEvaluation` with
`DynamicSpreadBlockedReason` when the model cannot truthfully evaluate. Dynamic
spread previews are limited to taker-like `MARKET` and `STOP` order semantics;
`LIMIT`, `STOP_LIMIT`, maker semantics, missed-fill logic, and OHLC
outside-range reporting remain deferred to later phases.

The current Nautilus runtime wiring applies dynamic spread features to MARKET
orders only. Runtime feature generation uses the config-declared
`true_range_atr` volatility signal over prior completed bars and an explicit
`volatility_floor_price`; the domain still receives only the precomputed
stress signal and does not know about pandas, files, tick size floors, or
Nautilus order objects. Stop-market and trailing-stop-market dynamic runtime
fills return to Nautilus' default path through the typed `dynamic_order_types`
runtime policy until real Nautilus stop trigger/fill timestamp behavior is
characterized.

## Phase 4 Slippage And Combined Preview Contracts

`slippage.py` owns deterministic adverse slippage separately from spread.
Supported models are:

- `fixed_ticks` with `slippage_ticks` converted through
  `ExecutionInstrumentMetadata.tick_size`.
- `bps_of_price` with `slippage_bps` applied to an explicit positive
  `price_base`.
- `none_explicit`, the only valid way to select no deterministic slippage.

MARKET and STOP previews can receive adverse slippage: BUY increases the
effective price and SELL decreases it. LIMIT and STOP_LIMIT previews receive
zero adverse slippage, preserving limit-price protection after the spread
eligibility check.

`cost_preview.py` composes the deterministic cost stack per symbol/per leg. It
starts from the reference price, applies spread first, stops immediately if the
spread preview is `blocked_by_limit` or `blocked_by_model_state`, applies
slippage only as allowed by `OrderExecutionEconomics`, and calculates
commission from the final effective price after spread plus slippage. Statarb
and basket callers receive one preview per leg; the domain layer does not net
costs into a synthetic spread scalar.

The domain contract still does not import or construct Nautilus runtime
objects. Policy-present Nautilus runs consume these contracts through
`infrastructure.nautilus.execution_models`, which translates Nautilus runtime
objects into primitive/domain inputs before calling the pure previews. Dynamic
spread runtime feature artifacts and the characterized MARKET timestamp source
(`ts_init`) live in `infrastructure.nautilus`; this package only validates and
evaluates the feature input contract. There is still no latency model,
volatility-scaled slippage, missed-fill simulation, or domain-level order-book
abstraction in this package.
