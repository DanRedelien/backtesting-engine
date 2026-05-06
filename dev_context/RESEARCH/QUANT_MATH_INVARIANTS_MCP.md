# Quant Math Invariants MCP

Use this document for universal numerical and financial-convention rules.

## 1. Returns must match the task

Common default:

- simple returns for cross-sectional aggregation and portfolio arithmetic
- log returns for some time-series modeling tasks

Never treat them as interchangeable without proving that the approximation is
acceptable.

## 2. Aggregation rule

Across assets, portfolio returns are generally aggregated in simple-return
space, not by summing log returns.

Across time, log returns are additive, while simple returns compound
multiplicatively.

Always choose the return representation that matches the mathematical operation.

## 3. Unit discipline

Be explicit about:

- percent vs fraction
- basis points vs decimal rates
- daily vs annualized measures
- notional vs exposure vs market value

Use variable names that carry the unit when ambiguity is possible.

## 4. Annualization

Do not annualize by reflex.

If annualization is needed, make the convention explicit:

- 252 trading days
- 365 calendar days
- asset-class- or venue-specific session counts

## 5. Drawdown and turnover

Document whether drawdown is stored as:

- negative percent
- positive percent magnitude
- fraction

Do the same for turnover, fees, and slippage.

## 6. Horizon calculations

Multi-period return and risk calculations must state whether they use:

- overlapping windows
- non-overlapping windows
- square-root-of-time approximations
- direct horizon aggregation

These are not interchangeable.

## 7. Data alignment

Math is wrong if the underlying time alignment is wrong.

Always verify:

- timestamps
- session boundaries
- timezone normalization
- forward-return labeling
- train/test split boundaries

## 8. Repository examples

Examples from the current and prior projects:

- execution engines require strict next-bar semantics to avoid lookahead
- VaR and portfolio aggregation require explicit return-space choices

These examples illustrate the invariant: numerical correctness depends on both
formula choice and time alignment.
