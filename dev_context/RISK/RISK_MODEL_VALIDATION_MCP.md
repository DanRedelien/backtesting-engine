# Risk Model Validation MCP

Use this document when validating models that estimate or communicate risk.

Examples:

- VaR / ES engines
- volatility forecasts
- stress-testing models
- factor or exposure models
- scenario loss estimators

## 1. Validation goal

A risk model is useful only if it is both numerically sound and operationally
truthful.

Validation should answer:

- is the model calibrated
- does it fail in clustered or unstable ways
- is it operationally safe to run
- is it better than the challenger or incumbent baseline

## 2. Common validation layers

- data quality validation
- model-output sanity checks
- statistical backtesting
- regime or scenario sensitivity
- comparison against challenger models
- operational resilience checks

## 3. Model-class examples

For VaR / ES:

- breach rate
- unconditional coverage
- independence or clustering of breaches
- tail stability
- expected shortfall sensitivity during stress windows

For volatility forecasts:

- forecast error against realized volatility
- responsiveness to volatility regime changes
- stability vs noise tradeoff

For scenario or stress models:

- scenario completeness
- plausibility of losses
- explainability of extreme outputs

## 4. Challenger vs incumbent

Never replace a risk model using only absolute metrics from the candidate.

Compare:

- calibration
- stability
- responsiveness
- capital efficiency
- operational robustness

## 4.5. Minimum concrete checks for VaR / ES

For VaR / ES releases, the validation pack should usually include:

- observed breach rate vs target breach rate
- unconditional coverage test
- independence or clustering test
- comparison against equal-weight HS or another simple challenger
- sensitivity to recent stress windows
- evidence that the data-quality gate passed

## 5. Release gates

A production-facing risk release should specify:

- minimum data-quality thresholds
- required validation tests
- acceptable operating range
- fallback behavior if inputs fail
- rollback criteria if the model degrades in production

## 6. Important note

This document is universal.

If the task is specifically about regime-aware VaR / ES with weighted
historical simulation, use `RISK/VAR_WHS_MCP.md` as the specialized companion.
