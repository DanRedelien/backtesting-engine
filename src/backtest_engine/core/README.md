# Core

## Ownership

Owns small stable primitives, identifiers, value helpers, enums, protocols, and
shared error types.

## May import

- standard library only

## Must never import

- `domain`
- `application`
- `infrastructure`
- `interfaces`

## Public Surface

- ids
- enums
- money
- percentages
- time
- errors
- protocols
- market_data_validation

## Add Code Here

- shared primitive with no business meaning
- reusable value helper needed across bounded contexts
- stable identifier or enum used by multiple layers
- source validation ruleset identity shared by config and infrastructure

## Verification

- `tests/unit/core/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Module Map](../../../docs/MODULE_MAP.md)
