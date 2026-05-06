# ADR-006: Portfolio Weights and WFO Contract

## Status

Proposed

## Context

The repository already exposes a canonical runtime boundary, bundle
persistence, and thin delivery surfaces around them. Portfolio weights and
walk-forward optimization need one stable contract for multi-sleeve portfolios.

## Decision

Portfolio weights are canonical execution truth through one typed portfolio
execution policy and one causal sizing layer.

The contract is:

- `PortfolioStrategySpec.weight_frac` means normalized sleeve weight.
- A portfolio run uses one typed `PortfolioExecutionPolicy` to define
  rebalance cadence, target portfolio volatility, lookback length, warmup
  behavior, and sizing caps.
- Portfolio sizing is causal and fold-local. It may only use information
  available at or before the rebalance timestamp.
- There is exactly one portfolio-level risk scalar. Strategy wrappers may not
  add a second portfolio-level sizing transform.
- Walk-forward evaluation keeps fixed strategy parameters separate from weight
  search, scoring, confirmation, and persistence.
- Study outputs and live handoff outputs are typed artifacts, not generic
  JSON summaries.
- Publication is fail-closed. A recommendation is only published when the
  study verdict allows it and the source analytics are fresh.

## Consequences

- single-asset and multi-leg sleeves share one portfolio sizing path
- portfolio weights become reproducible inputs rather than informal notes
- WFO can produce stable champion weights for live handoff without mixing
  optimization logic into execution wrappers
- study and recommendation artifacts need schema versioning from the start
- stale or invalid sleeve analytics block publication instead of being silently
  renormalized

## Non-Goals

- no joint strategy-parameter plus weight search in the same contract
- no mixed-mode runtime semantics
