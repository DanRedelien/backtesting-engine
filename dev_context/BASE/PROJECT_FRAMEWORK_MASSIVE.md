# Project Framework: Massive

Use this framework for large institutional systems, usually:

- 300+ modules
- 100k+ LOC
- multiple teams or long-lived ownership boundaries
- production-critical workflows with operational controls

Typical examples:

- hedge-fund risk platform
- enterprise execution and monitoring stack
- large multi-asset research platform
- market data plant with downstream model consumers

## Design goal

Optimize for clarity of ownership, contract stability, auditability, and safe
change management.

## Recommended shape

The exact layout may be one monorepo or several repositories, but the system
should make these boundaries explicit:

- platform configuration and shared contracts
- data acquisition and normalization
- reference data and instrument metadata
- model-serving or research engines
- execution or order-routing services
- analytics and artifact pipelines
- delivery surfaces such as APIs, dashboards, schedulers, and workers
- observability, audit, and release tooling

## Mandatory characteristics

- interface-first thinking between major domains
- versioned schemas and contracts
- explicit ownership for packages and services
- clear operational policies for retries, replays, and incident recovery
- strong test layers: unit, contract, integration, scenario, regression
- reproducible artifacts and audit trails

## Structural guidance

- keep domain modules independent of transport where possible
- isolate external-vendor adapters behind explicit interfaces
- prefer append-only or versioned historical artifacts for critical analytics
- make idempotency and replayability explicit in batch or event-driven systems
- document failure modes, not just happy paths

## What changes at this scale

- architecture is no longer only about code organization
- contract governance matters as much as implementation quality
- operational safety matters as much as model quality
- each bounded context may need its own local README, owner, and release rules

## Anti-patterns

- treating a 200k-LOC platform like a single-repo side project
- sharing hidden mutable state across major domains
- relying on tribal knowledge instead of written contracts
- using one "common utils" package as a dumping ground for business logic

