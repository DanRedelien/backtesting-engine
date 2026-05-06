# LLM Operating Guide

Purpose: help any LLM use this folder predictably and without hallucinated
architecture rules.

## 1. Start with scope

Before reading deep task-specific files, decide:

- what kind of system this is
- what size the system is
- which bounded context the task belongs to
- whether the task is research-only, production-facing, or both

## 2. Recommended reading sequence

For most tasks:

1. `dev_context/README.md`
2. `dev_context/CLEAN_CODE_MCP.md`
3. `dev_context/QUANT_FRAMEWORK_MCP.md`
4. one project-scale framework file
5. only the documents directly relevant to the task

## 3. Do not over-read

Do not read every file in `dev_context/` by default.

Read only what the task needs:

- data task -> `DATA/`
- strategy or optimization task -> `RESEARCH/`
- risk-model task -> `RISK/`
- dashboard or artifact task -> `REPORTING/`
- live trading, monitoring, or safety task -> `OPS/`

## 3.5. Keep local mapping separate from universal guidance

Repository-specific paths belong primarily in:

- `dev_context/README.md`
- `docs/agents.md`

Topic-specific MCP documents should stay generic unless a local path is truly
required to explain the active repository.

## 4. Examples are examples

Examples from the current repository or past projects are there to show one
good implementation pattern.

They are not universal laws.

Always check:

- local code
- local tests
- repository-specific docs

before applying an example literally.

## 5. Conflict resolution

If two sources disagree, use this order:

1. repository code and tests
2. repository-specific docs
3. `dev_context/` guidance

## 6. Specialized documents

Treat specialized documents as opt-in, not global defaults.

Example:

- `RISK/VAR_WHS_MCP.md` is for regime-aware VaR / ES work
- it is not a default playbook for a trading bot, stat-arb engine, or market
  data adapter

## 7. Universal warning signs

Slow down and verify assumptions when you see:

- time alignment across multiple timeframes
- percent vs fraction ambiguity
- futures contract rolling
- strategy signals mixed with execution sizing
- UI logic mixed with analytics transforms
- model-validation language that applies only to one model class
