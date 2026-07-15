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
POST /backtest/multi-strategy/walk-forward
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

### `POST /backtest/multi-strategy/walk-forward`

Runs the exact-symbol multi-strategy comparison and then validates every fixed candidate across rolling out-of-sample test windows.

A candidate is eligible only when:

- every full-period selection gate passes
- the minimum number of rolling windows is available
- the configured share of windows is profitable
- median Sharpe and median profit factor pass
- worst out-of-sample drawdown remains inside the configured floor
- aggregate kill-switch events remain within the configured limit

The default chronology uses 126 training bars, 126 out-of-sample test bars, a 63-bar step, and at least four completed windows. Test simulations use only their chronological test slice; future bars never enter an earlier window.

Each ranked result includes full-period metrics plus `walk_forward` stability evidence and per-window date boundaries. `best_eligible` and `selected_result` are null unless both validation layers pass. Insufficient history is a safe no-trade result and must not fall back to full-period-only evidence.

See `docs/WALK_FORWARD_MULTI_STRATEGY.md` for the window design, default stability gates, and expected orchestration.

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
9. Walk-forward selection must not promote full-period-only evidence when rolling validation fails or history is insufficient.
