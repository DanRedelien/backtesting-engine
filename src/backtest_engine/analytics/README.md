# Analytics

## Ownership

Owns derived read models over persisted artifacts. Analytics never owns
execution truth.

## May Import

- `core`
- `domain`
- `infrastructure.artifacts` for read-only loading

## Must Never Import

- runtime execution adapters as truth owners

## Public Surface

- bundle read models
- saved-bundle dashboard read models
- study read models
- recommendation read models
- read-only loaders used by delivery surfaces

## Add Code Here

- derived read projection
- reporting view models built from persisted artifacts
- artifact query surfaces with no runtime side effects

## Saved-Bundle Dashboard

`read_models.bundle_dashboard` owns the typed Stage-1 dashboard payload used by
the terminal UI. It loads bundle truth through the canonical bundle loader and
reads parquet files only from `ResultBundle.artifact_locations`.

It derives:

- closed-position equity from non-snapshot `positions_report` rows with
  `ts_closed` and finite `realized_return`
- combined, long, and short equity series, where statarb long/short means
  spread direction resolved from `spread_weights`
- relative drawdown from the combined closed-position equity curve
- fixed-order core trading stats: Net Return, Max Drawdown, Sharpe, Trade
  Count, Win Rate, Profit Factor, Avg Win / Avg Loss, and Expectancy
- strategy-level realized-return or realized-PnL-proxy correlation when
  `positions_report` exposes stable per-strategy observations

When an artifact is missing, unreadable, malformed, or insufficient for a
panel, the read model returns an explicit empty/error reason instead of
fabricating data.

## Verification

- `tests/unit/analytics/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Module Map](../../../docs/MODULE_MAP.md)
