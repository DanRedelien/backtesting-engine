# Usage Guide

This directory is the operator entrypoint for the repository.

Open the guide that matches the task you are trying to complete:

- [Install and Terminal Preparation](install.md)
  Set up Python, install dependencies, prepare shared `BTE_` environment
  variables, run quality gates, and launch the saved-bundle dashboard.
- [Historical Market Data](market-data.md)
  Download, verify, recover, and troubleshoot provider-managed market-data
  slices for IB/TWS and MT5.
- [Backtesting](backtesting.md)
  Current-state overview for single-asset, statarb, and portfolio backtesting
  flows plus post-run saved-bundle inspection through the local dashboard.
- [Microstructure Calibration](microstructure-calibration.md)
  Operator CLI path for generated spread-cost YAML, config hash anchoring, and
  backtest `--execution-costs-path` handoff.
- [WFO Optimization](wfo.md)
  Current-state overview for strategy and portfolio optimization workflows plus
  TODO placeholders for the future operator runbook.

For repository-wide architecture and ownership context, continue with
[README.md](../README.md), [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md),
and [docs/MODULE_MAP.md](../docs/MODULE_MAP.md).
