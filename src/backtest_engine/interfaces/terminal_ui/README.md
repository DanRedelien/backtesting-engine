# Terminal UI

## Ownership

Owns the FastAPI terminal delivery surface for saved-bundle dashboard reads,
bundle catalog JSON, study reads, recommendation reads, and scenario rerun
planning.

## Depends On

- `bootstrap.composition_root.ApplicationContainer`
- persisted artifacts under `results/`
- analytics read models
- canonical scenario rerun planning

## Public Surface

Primary routes:

- `/health`
- `/`
- `/bundles/{bundle_id}`
- `/api/bundles`
- `/api/bundles/{bundle_id}`
- `/api/bundles/{bundle_id}/scenario-plan`
- `/api/studies/summary`
- `/api/studies/folds`
- `/api/studies/champion`
- `/api/recommendations`
- `/api/recommendations/latest`

`/` selects the newest loadable saved bundle by `created_at_utc`.
`/bundles/{bundle_id}` renders the explicit bundle identified in the URL.
Both HTML routes are read-only and render the Stage-1 saved-bundle dashboard:

- core trading stats
- strategy correlation
- combined/long/short equity
- drawdown

## Rules

- do not compute execution truth here
- keep route handlers thin and presentation-focused
- load persisted artifacts through canonical query services
- do not render execution controls on the dashboard

## Add Code Here

- HTML delivery over existing read models
- JSON read endpoints over persisted artifacts
- presentation-only scenario preparation surfaces

## Dashboard Artifact Inputs

The HTML dashboard consumes the typed analytics payload built from the saved
bundle and parquet artifact locations declared by `bundle.artifact_locations`.
It does not infer files from runtime roots.

Current dashboard inputs:

- `positions_report`: closed non-snapshot rows with `ts_closed`,
  `realized_return`, `entry`, and `instrument_id` for core stats plus
  combined/long/short equity; statarb long/short side classification resolves
  spread direction from the run spec `spread_weights`
- `positions_report`: optional strategy-level realized return or realized PnL
  observations for correlation

Missing or unreadable artifacts keep the route at HTTP 200 and render honest
panel empty/error states. The scenario rerun planner remains available through
`/api/bundles/{bundle_id}/scenario-plan`; the dashboard itself does not show
scenario controls.

## Verification

- `tests/unit/interfaces/test_terminal_ui_app.py`
- `tests/unit/interfaces/test_terminal_ui_bundle_summary.py`
- `tests/unit/interfaces/test_terminal_ui_bundle_reruns.py`
- `tests/unit/interfaces/test_terminal_ui_study_reads.py`

## Canonical References

- [Architecture](../../../../docs/ARCHITECTURE.md)
- [Module Map](../../../../docs/MODULE_MAP.md)
