# Domain

## Ownership

Owns business meaning and pure contracts for market, strategy-agnostic
strategy contracts, execution, portfolio, and artifact semantics.

## May import

- `core`

## Must never import

- `infrastructure`
- `interfaces`

## Public Surface

- dataset specifications
- strategy specifications, intents, signals, and strategy-agnostic policy
  contracts
- execution truth contracts
- portfolio policies, plans, and sizing semantics
- artifact manifests and bundles

## Add Code Here

- pure market semantics
- strategy-agnostic contracts that must remain reusable across concrete
  strategies
- portfolio planning and risk semantics
- artifact truth models
- contracts that must remain framework-agnostic

## Verification

- `tests/unit/domain/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Module Map](../../../docs/MODULE_MAP.md)
