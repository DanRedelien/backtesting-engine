# ADR-003: Artifact Contract

## Status

Accepted

## Decision

Runtime artifacts and result bundles are separate concepts with explicit
manifest and provenance models.

Single and portfolio workflows keep separate export use-cases, but they share
one internal bundle-header builder for `ArtifactManifest` and
`ProvenanceRecord`.

`ArtifactManifest` keeps both `run_spec_hash` and `config_hash` because the
persisted contract requires an explicit configuration hash. Today,
`BacktestRunSpec` is the resolved execution and configuration boundary, so the
invariant is:

- `config_hash == run_spec_hash`

This equality is enforced in the artifact contract. If configuration hashing is
split from `BacktestRunSpec` later, the manifest contract must change
explicitly through a follow-up ADR instead of drifting silently in exporters.

`ResultBundle` also persists the full canonical `BacktestRunSpec`. The bundle
is therefore not just a summary container; it is the replay context for
delivery surfaces such as the Terminal UI and worker-triggered scenario reruns.

## Consequences

- execution truth is persisted once
- analytics reads derived bundles and read models
- saved bundles can produce canonical rerun requests from persisted contracts
- single and portfolio exporters stay small and top-down
- manifest/provenance header assembly changes in one place only
