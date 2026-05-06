# ADR-001: Modular Monolith

## Status

Accepted

## Decision

The system uses one modular monolith with strict bounded contexts.

## Consequences

- local execution stays simple
- imports stay explicit
- cross-context dependencies must be enforced
