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
POST /backtest/compare
POST /backtest/walk-forward
POST /backtest/report
```

## Safety Rules

1. `Backtest_Agent` validates strategies using historical simulation only.
2. `Backtest_Agent` must not submit broker orders.
3. Backtest reports should gate strategy promotion before paper or live workflows.
4. Manager remains responsible for orchestration.
5. Risk and Execution controls remain required outside simulation.
