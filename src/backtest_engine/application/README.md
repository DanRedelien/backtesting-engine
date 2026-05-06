# Application

## Ownership

Owns top-down use-cases and orchestration across single, portfolio, batch,
optimization, scenario, baseline, and market-data flows.

## May Import

- `core`
- `config`
- `domain`
- `infrastructure`

## Must Never Import

- CLI parsing
- FastAPI routes
- delivery-specific rendering

## Public Surface

- single, portfolio, batch, scenario, and baseline use-cases
- backtest dry-run preparation over the canonical compiler path
- walk-forward and portfolio-weight-study orchestration
- optimization trial runtime and trial executor contracts
- application-owned market-data request and result DTOs plus download and
  verification orchestration
- offline spread calibration command/result contracts, EDGE calibration panel
  construction from verified normalized OHLCV data, and Phase 2 publication of
  generated execution-cost YAML plus calibration reports and diagnostics PNGs;
  calibration fails closed on stale source/validation/normalized-artifact
  provenance, inconsistent panel conversion units, invalid publication splits,
  untrusted volume semantics, non-converged fits, alias sets that resolve
  multiple input symbols to one canonical execution symbol, and records explicit
  positive-volume coverage diagnostics. Publication artifact identity includes
  the target/settings, validated base execution-cost config hash, and symbol-map
  content/path identity. Diagnostics are deterministic report-only audit aids:
  they compare raw model and clipped runtime predictions, score train-derived
  baselines on holdout rows, emit heuristic flags, and never block YAML
  publication.
- `HistoricalMarketDataService` assembly, where the service, providers, and
  verifier must share one historical-data store instance for skip/path truth
- bundle export, study publication, and study confirmation workflows

## Add Code Here

- use-case orchestration
- application command and result contracts
- workflow coordination over canonical ports
- pure offline calibration estimators, panel builders, and generated
  execution-cost publication flows that are not wired into Nautilus runtime
  execution

## Verification

- `tests/unit/application/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Module Map](../../../docs/MODULE_MAP.md)
