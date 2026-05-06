# ADR-005: Statarb Strategy Scope

## Status

Accepted

## Decision

`statarb_weighted_spread` covers the weighted-spread regime logic and the
minimum execution adapter surface required to run it through Nautilus.

Portfolio sizing and rebalance policy remain separate portfolio concerns.

## Consequences

- strategy regime logic stays in `domain`
- the Nautilus wrapper stays focused on synchronization and order translation
- portfolio sizing policy can evolve without polluting statarb strategy
  semantics
