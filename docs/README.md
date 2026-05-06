# Documentation Index

This directory is the canonical documentation home for the repository.

## Core Repository Documents

- [Usage Guide](../USAGE/README.md)
  Practical launch, execution, and operator workflow notes.
- [Architecture](ARCHITECTURE.md)
  Institutional architecture, dependency direction, execution flow, and
  operational boundaries.
- [Module Map](MODULE_MAP.md)
  Ownership map, data flow, delivery surfaces, and code placement guide.
- [Contributing](CONTRIBUTING.md)
  Contributor workflow, quality expectations, and documentation maintenance
  rules.
- [Import Rules](IMPORT_RULES.md)
  Dependency governance and forbidden module paths.
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)
  Attribution and license notices for locally adapted external algorithms.
- [Writing a Strategy](WRITING_STRATEGY.md)
  Concrete strategy cartridge layout, loader contract, and authoring rules.
- [Agent Context](agents.md)
  Repository-specific orientation for agents and automation tooling.

## Architecture Decision Records

- [ADR archive](adr/)
  Accepted architectural decisions that define the current system shape.

## Package Contracts

Package-level ownership notes live alongside code under `src/backtest_engine/*/README.md`.
Those documents should stay concise and must remain consistent with the
canonical documents in this folder.

## Generated Contract Artifacts

- [Run Profile JSON Schema](generated/run_profile.schema.json)
  Machine-readable schema generated from the Pydantic `RunProfile` contract.

## Development Context

Cross-project engineering guidance lives in [dev_context/README.md](../dev_context/README.md).
Repository-specific rules in `docs/` take precedence over generic guidance.
