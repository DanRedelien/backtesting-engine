# Reporting And Visualization MCP

Use this document for artifacts, dashboards, research reports, and visual
communication layers.

## 1. Principle

Reporting exists to support decisions, debugging, and auditability.

It should not become the hidden source of truth for analytics semantics.

## 2. Separation of concerns

Keep these layers distinct:

- analytics and metric calculation
- artifact serialization and storage
- API or runtime payload assembly
- rendering and styling

This separation makes dashboards easier to trust and easier to refactor.

## 3. Artifact-first thinking

When reproducibility matters, prefer durable artifacts over UI-only state.

Useful artifact families:

- performance summaries
- equity and drawdown series
- trade logs
- optimization reports
- validation reports
- scenario manifests
- diagnostics for failed runs

## 4. Chart selection

Use the simplest chart that answers the operational question.

Examples:

- equity and drawdown for strategy performance
- distribution plots for return shape and tails
- heatmaps for optimization sweeps or correlation structure
- exposure and turnover charts for portfolio diagnostics
- scenario tables for stress testing

Avoid decorative charts with unclear decisions behind them.

## 5. Style rules

- prioritize legibility over novelty
- keep labeling explicit
- use consistent semantic colors across the same project
- avoid encoding critical meaning through color alone
- show units and time horizon clearly

Do not hardcode one visual theme as a universal law for every project.

## 6. Static vs interactive

Choose the medium by workflow:

- static reports for reproducible research, exports, and review packets
- interactive dashboards for drill-down, diagnostics, and operational flows

Both are valid. The right choice depends on the audience and task.

## 7. Cross-project examples

Backtester example:

- analytics layer writes trade logs, equity curves, and summary artifacts
- dashboard or notebook layer only renders saved results

Risk-dashboard example:

- model layer computes VaR / ES, exposures, and breaches
- API layer serves validated payloads to the UI

Research-report example:

- experiment pipeline writes static tables and charts
- presentation layer assembles a review packet without recomputing the model
