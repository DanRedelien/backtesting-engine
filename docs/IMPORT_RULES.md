# Import Rules

## Allowed Direction

```text
interfaces -> application -> domain -> core
bootstrap  -> application -> domain -> core
bootstrap  -> infrastructure -> domain -> core
application -> infrastructure
infrastructure -> strategies -> domain -> core
analytics -> domain -> core
analytics -> infrastructure.artifacts (read-only)
```

## Forbidden Direction

- `domain` must not import `infrastructure` or `interfaces`
- concrete strategy packages under `backtest_engine.strategies.<implementation_id>`
  must not import `application`, `bootstrap`, `infrastructure`, `interfaces`, or
  another concrete strategy package
- `core` must not import any project package
- `application` must not import CLI parsing, FastAPI, or UI rendering
- `interfaces` must not define business truth
- `analytics` must not define execution truth

## Package Initializers

- package `__init__.py` files must not eagerly import unrelated delivery or
  bootstrap flows when a narrower entrypoint can be loaded independently
- specialized entrypoints such as the historical market-data CLI should be able
  to import without pulling optimization, study, or Nautilus runtime modules

## Forbidden Module Paths

The following module paths are outside the canonical codebase and must not be
imported anywhere under `backtest_engine`:

- `backtest_engine.single_asset`
- `backtest_engine.portfolio_layer`
- `backtest_engine.services`
- `backtest_engine.runtime`
- `backtest_engine.nautilus_layer`

`.importlinter` mirrors these rules for automated enforcement.

## Strategy Package Imports

Concrete strategy folders may import:

- Python standard library modules
- installed dependencies declared by the project
- `backtest_engine.core`
- `backtest_engine.domain`
- `backtest_engine.strategies.package_contracts`
- modules inside their own strategy folder

Concrete strategy folders must not import any runtime resolver, composition
root, delivery adapter, or another concrete strategy package.
