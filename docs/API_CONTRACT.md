# Backtest_Agent API Contract

This document defines the baseline API contract for `Backtest_Agent` in the multi-agent trading system.

`Backtest_Agent` validates historical strategy behavior before promotion to paper or live workflows. It should not submit broker orders or bypass Manager, Risk, or Execution controls.

## Standard Headers

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <backtest-agent-api-key>
```

## Standard Response Envelope

Operational contract endpoints return this envelope:

```json
{
  "status": "success",
  "agent_type": "backtest-agent",
  "version": "0.1.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-04T00:00:00Z",
  "correlation_id": null,
  "data": {},
  "metadata": {},
  "error": null,
  "confidence_score": null
}
```

## Operational Endpoints

```http
GET /health
GET /ready
GET /version
```

## Backtest Endpoints

```http
POST /backtest/run
POST /backtest/run-and-publish
POST /backtest/run-and-publish-batch
POST /backtest/compare
POST /backtest/multi-strategy
POST /backtest/walk-forward
POST /backtest/robustness
POST /backtest/report
```

### `POST /backtest/multi-strategy`

Runs multiple strategy configurations for exactly one symbol. When candidates are omitted, the endpoint evaluates the deterministic `balanced_v1` suite containing SMA crossover, trend following, mean reversion, and breakout strategies.

Each ranked result contains:

- exact `strategy_id`
- strategy name and effective parameters
- performance metrics and score components
- selection gate results
- eligibility status and disqualification reasons

The response exposes `best_overall` for diagnostics and `best_eligible` for orchestration. `best_eligible` is null unless every configured selection gate passes. `selected_result` contains the full simulation result only for the eligible selection.

The endpoint rejects requests containing more than one symbol. Callers must evaluate each Scanner-selected symbol independently so strategy evidence cannot leak between symbols.

See `docs/MULTI_STRATEGY_SELECTION.md` for the default suite, scoring model, and safety gates.

### `POST /backtest/run-and-publish`

Runs the same historical simulation as `/backtest/run`, then optionally publishes the normalized result to `Database_Agent` via `POST /backtests/runs`.
This endpoint accepts exactly one unique symbol; multi-symbol callers must use
`/backtest/run-and-publish-batch` so database evidence cannot be ambiguous.

Additional request fields:

```json
{
  "account_id": "1",
  "run_id": "optional-run-id",
  "skill_id": "optional-skill-id",
  "strategy_id": "optional-strategy-id",
  "timeframe": "1d",
  "publish_to_database": true,
  "metadata": {}
}
```

Environment variables used by the publisher:

```bash
DATABASE_AGENT_URL=http://database-agent:8004
DATABASE_AGENT_API_KEY=dev_database_key
```

### `POST /backtest/run-and-publish-batch`

Runs each requested symbol as an independent simulation and publishes one
Database_Agent run per exact `skill_id + strategy_id + symbol + timeframe`
identity. A batch never combines metrics from different symbols into one
database record.

The request accepts the same fields as `/backtest/run-and-publish`, plus an
optional `batch_id`. At most 25 symbols are accepted. Symbols are normalized to
uppercase and duplicates are removed while preserving order.

Each result item contains its own `run_id`, simulation result, publish status,
database payload, and database response. A failure for one symbol is reported
against that symbol and cannot fall back to evidence from another symbol. The
batch response sets `all_succeeded=false`, and the hourly CLI exits non-zero,
when any requested simulation or required database publish fails.

## Safety Rules

1. `Backtest_Agent` validates strategies using historical simulation only.
2. `Backtest_Agent` must not submit broker orders.
3. Backtest reports should gate strategy promotion before paper or live workflows.
4. Manager remains responsible for orchestration.
5. Risk and Execution controls remain required outside simulation.
6. Database publishing is storage-only. It does not submit, cancel, approve, or modify broker orders.
7. Batch execution is bounded and sequential; it does not call broker trading APIs.
8. Multi-strategy selection is exact-symbol scoped and must not promote an ineligible strategy.
