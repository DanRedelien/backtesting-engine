# Bootstrap

## Ownership

Owns dependency assembly and default container construction only.

## May Import

- `application`
- `infrastructure`
- `config`

## Must Never Import

- UI rendering code
- business logic beyond dependency assembly

## Public Surface

- `composition_root.py`
- `build_application_container(...)`
- `build_infrastructure_ports(...)`
- `build_default_infrastructure_ports(...)`
- `build_cli_container(...)`
- `build_calibration_dataset_materializer(...)`
- `build_http_container(...)`
- `build_ib_historical_ingestor(...)`
- `build_market_data_service(...)`

Private sibling modules under `bootstrap/` support `composition_root.py` and do
not expand the public bootstrap surface.

Keep narrow wiring paths available for isolated delivery surfaces. Historical
market-data assembly should not require importing the broader optimization or
runtime container just to construct provider and validator dependencies.

Default CLI and execution wiring reuse one Nautilus run-spec compiler instance
for both dry-run preparation and `BacktestNodeNautilusRunner`. The backtest CLI
may pass an explicit generated `execution_costs_path` into this compiler at
composition time after its run-profile hash preflight succeeds.

## Add Code Here

- dependency wiring
- default adapter assembly
- composition-time diagnostics wiring

## Verification

- `tests/unit/bootstrap/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Import Rules](../../../docs/IMPORT_RULES.md)
