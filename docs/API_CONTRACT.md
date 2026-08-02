# Backtest_Agent API Contract

This document defines the baseline API contract for `Backtest_Agent` in the multi-agent trading system.

`Backtest_Agent` validates historical strategy behavior before promotion to paper or live workflows. It does not submit broker orders or bypass Manager, Risk, or Execution controls.

## Standard Headers

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <backtest-agent-api-key>
```

Compute and publishing endpoints require `X-API-KEY` when `BACKTEST_API_KEY` is configured. Production fails closed when the key is missing from service configuration. Operational health and version endpoints remain open.

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

## Strict request rules

External API requests reject:

- unknown top-level or price-bar fields
- NaN and Infinity
- invalid or duplicate normalized symbols
- duplicate or non-increasing timestamps
- timestamps without an explicit timezone
- empty or unexpected symbol datasets
- symbol, bar, total-bar, or request-byte counts above configured limits

Accepted symbols are canonicalized to uppercase and timestamps to UTC.

### `POST /backtest/multi-strategy`

Runs multiple strategy configurations for exactly one symbol. When candidates are omitted, the endpoint evaluates the deterministic `balanced_v1` suite containing SMA crossover, trend following, mean reversion, and breakout strategies.

Each ranked result contains:

- exact `strategy_id`
- strategy name and effective parameters
- performance metrics and score components
- selection gate results
- eligibility status and disqualification reasons

The response exposes `best_overall` for diagnostics and `best_eligible` for orchestration. `best_eligible` is null unless every configured selection gate passes. `selected_result` contains the simulation result only for the eligible selection.

The endpoint rejects requests containing more than one symbol. Callers evaluate each Scanner-selected symbol independently so strategy evidence cannot leak between symbols.

See `docs/MULTI_STRATEGY_SELECTION.md` for the default suite, scoring model, and safety gates.

### `POST /backtest/multi-strategy/walk-forward`

Performs true nested walk-forward strategy selection for one exact symbol.

For every chronological window the service:

1. ranks all candidates using only the training slice
2. selects the best eligible training candidate, or records the best diagnostic candidate when none is eligible
3. applies an optional embargo gap
4. evaluates only that selected candidate on the untouched future test slice
5. aggregates independent out-of-sample evidence across windows

The default chronology uses 126 training bars, 126 test bars, a 126-bar step, zero embargo bars, and at least four completed windows. Test windows do not overlap by default. Overlap requires explicit `allow_overlapping_test_windows=true` and is reported in the response.

The aggregate nested gates cover:

- minimum completed windows
- minimum rate of windows with an eligible training selection
- profitable future test-window rate
- median future Sharpe and profit factor
- worst future drawdown
- aggregate kill-switch events

Full-period metrics remain present for diagnostics only. They do not grant promotion and do not participate in selecting a candidate for an earlier historical test window.

The top-level `nested_walk_forward` object records:

- `selection_method = nested_train_select_test_evaluate`
- per-window train selection and future test evidence
- selected strategy counts
- latest selected strategy and eligibility
- overlap and embargo configuration
- aggregate metrics, gates, reasons, and stability score

`best_eligible` and `selected_result` remain null unless the nested gates pass, the latest training window selected an eligible exact strategy, and that candidate also passes its fixed-candidate out-of-sample stability diagnostics. Insufficient history is a safe no-trade result.

See `docs/WALK_FORWARD_MULTI_STRATEGY.md` for the full chronology and expected orchestration.

### `POST /backtest/run-and-publish`

Runs the same historical simulation as `/backtest/run`, then optionally publishes the normalized result to `Database_Agent` via `POST /backtests/runs`.

This endpoint accepts exactly one unique symbol. Multi-symbol callers use `/backtest/run-and-publish-batch` so database evidence cannot be ambiguous.

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

A required publish that fails or is skipped produces an error result. The scheduled CLI exits non-zero instead of reporting a false-green workflow.

### `POST /backtest/run-and-publish-batch`

Runs each requested symbol as an independent simulation and publishes one Database_Agent run per exact symbol identity. A batch never combines metrics from different symbols into one database record.

Each symbol receives a deterministic run ID derived from that exact symbol's dataset fingerprint, strategy and execution policy, timeframe, and engine version. `batch_id` is correlation metadata only, so changing one symbol does not change another symbol's run identity.

The request accepts the same fields as `/backtest/run-and-publish`, plus an optional `batch_id`. At most 25 symbols are accepted. Duplicate normalized symbols are rejected.

Each result item contains its own `run_id`, simulation result, publish status, database payload, and database response. A failure for one symbol is reported against that symbol and cannot fall back to evidence from another symbol. The batch response sets `all_succeeded=false`, and the hourly CLI exits non-zero, when any requested simulation or required database publish fails.

## Safety Rules

1. `Backtest_Agent` validates strategies using historical simulation only.
2. `Backtest_Agent` must not submit broker orders.
3. Backtest reports gate strategy promotion before paper or live workflows.
4. Manager remains responsible for orchestration.
5. Risk and Execution controls remain required outside simulation.
6. Database publishing is storage-only. It does not submit, cancel, approve, or modify broker orders.
7. Batch execution is bounded and sequential; it does not call broker trading APIs.
8. Multi-strategy selection is exact-symbol scoped and must not promote an ineligible strategy.
9. Nested walk-forward selection must not use future test data to choose a candidate for that historical window.
10. Full-period-only evidence cannot override failed nested validation or insufficient history.
