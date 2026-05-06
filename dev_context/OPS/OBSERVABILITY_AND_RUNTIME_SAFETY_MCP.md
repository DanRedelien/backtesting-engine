# Observability And Runtime Safety MCP

Use this document for production-facing quant systems, especially:

- live trading bots
- broker-connected execution services
- production risk engines
- scheduled market-data pipelines
- operational dashboards that drive decisions

## 1. Principle

A production system must be observable enough to answer:

- is it healthy
- is it degraded but still safe
- must it halt
- can it recover or replay safely

## 2. Minimum observability pillars

Every serious runtime should emit some combination of:

- structured logs
- metrics or counters
- health checks and heartbeats
- alerts for stale or broken inputs
- audit trails for important decisions

## 3. Health states

Use explicit runtime states rather than vague warnings:

- healthy
  Inputs are fresh, invariants hold, outputs are trusted.
- degraded_safe
  Some non-critical feature failed, but a documented safe fallback is active.
- degraded_unsafe
  The system is still alive but outputs are no longer safe to act on.
- halted
  Trading, order routing, or publication is intentionally stopped.

## 4. What should trigger degraded or halted states

Typical degraded-safe triggers:

- one optional vendor feed delayed while a validated fallback feed is active
- one charting or reporting subsystem failing while core model outputs remain
  correct
- one specialized model feature unavailable but a documented simpler model is
  active

Typical degraded-unsafe or halted triggers:

- stale market data with no safe fallback
- broken account or position reconciliation
- repeated model failures beyond threshold
- execution acknowledgements not matching sent orders
- data-quality gate failure on production inputs
- impossible risk numbers or breached hard invariants

## 5. Circuit breaker patterns

Circuit breakers should be explicit and testable.

Common patterns:

- consecutive-failure breaker
  Halt after `N` critical failures in a row.
- freshness breaker
  Halt if market data or positions are older than the allowed threshold.
- exposure breaker
  Halt if actual exposure exceeds allowed exposure.
- reconciliation breaker
  Halt if broker state and internal state disagree beyond tolerance.
- publish blocker
  Suppress outward-facing risk numbers if the model is degraded-unsafe.

## 6. Logging rules

- log in structured form when possible
- include identifiers: symbol, strategy, account, dataset version, model version
- aggregate repeated events instead of spamming loop-level logs
- separate operational errors from research diagnostics
- do not use free-form print noise as the main observability layer

## 7. Metrics that usually matter

Examples:

- market-data freshness
- request latency
- failed ingest count
- model runtime
- fallback activation count
- current health state
- open exposure
- rejected orders
- reconciliation mismatch count

## 8. Alerting guidance

Alert on conditions that require human action or immediate automated response.

Examples:

- market data stale beyond threshold
- broker connection lost
- risk model halted
- repeated order rejects
- scenario or batch job repeatedly failing

Do not alert on every warning-level cosmetic issue.

## 9. Replay and auditability

For systems that influence money or published risk:

- log enough metadata to replay important decisions
- record model version and data version
- preserve order and fill events
- make fallback activation visible in the audit trail

## 10. Cross-project examples

Live trading example:

- broker connection loss flips the system to `halted`
- stale quotes without fallback block new orders

Risk-engine example:

- data-quality failure flips publication to `degraded_unsafe`
- equal-weight HS fallback may be `degraded_safe` if pre-approved

Scheduled data-pipeline example:

- one failed batch can retry
- repeated failures or corrupt output mark the pipeline as failed and block
  downstream consumers
