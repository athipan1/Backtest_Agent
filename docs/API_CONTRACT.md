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
POST /backtest/compare
POST /backtest/walk-forward
POST /backtest/report
```

### `POST /backtest/run-and-publish`

Runs the same historical simulation as `/backtest/run`, then optionally publishes the normalized result to `Database_Agent` via `POST /backtests/runs`.

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

## Safety Rules

1. `Backtest_Agent` validates strategies using historical simulation only.
2. `Backtest_Agent` must not submit broker orders.
3. Backtest reports should gate strategy promotion before paper or live workflows.
4. Manager remains responsible for orchestration.
5. Risk and Execution controls remain required outside simulation.
6. Database publishing is storage-only. It does not submit, cancel, approve, or modify broker orders.
