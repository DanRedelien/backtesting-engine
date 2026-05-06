# Strategies

## Ownership

Owns concrete strategy cartridges addressed by `StrategySpec.implementation_id`.

## Folder Rule

Each concrete strategy lives entirely under
`src/backtest_engine/strategies/<implementation_id>/` and owns:

- its validated parameter model
- its optional pure policy modules
- its Nautilus wrapper
- its package `README.md`
- its local tests

## Must Never Import

- `backtest_engine.application`
- `backtest_engine.bootstrap`
- `backtest_engine.infrastructure`
- `backtest_engine.interfaces`
- another `backtest_engine.strategies.<other_id>` package

## Public Surface

- `package_contracts.py`
- `package_loader.py`
- concrete strategy folders addressed by `implementation_id`

## Runtime Contracts

`build_config` payloads may be nested JSON objects and arrays, but values must
already be exact JSON-compatible Python values. The resolver rejects non-JSON
runtime objects such as tuples, `Decimal`, datetimes, NumPy scalars, `NaN`, and
infinities rather than coercing them.

Package definitions are cached per process. `clear_strategy_package_definition_cache()`
is a test and development helper that clears cached definitions and reloadable
concrete strategy modules.

## Verification

- generic discovery and boundary tests under top-level `tests/`
- strategy-local tests under each strategy folder
