# ADR-004: Strategy Policy Split

## Status

Accepted

## Decision

Strategy policy remains a pure domain concern, while Nautilus wrappers live in
infrastructure.

## Consequences

- easier unit testing
- lower context cost for contributors and LLMs
- framework adapters stay outside the domain policy layer
