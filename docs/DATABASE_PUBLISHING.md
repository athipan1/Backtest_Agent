# Database Publishing

`Backtest_Agent` can publish completed historical simulation results to `Database_Agent` so `Curator_Agent` and `Manager_Agent` can later check whether a skill or strategy passed backtesting before promotion.

## Endpoint

```http
POST /backtest/run-and-publish
```

This endpoint:

1. Runs the same local simulation as `POST /backtest/run`.
2. Normalizes the result into the `Database_Agent` backtest payload shape.
3. Publishes to `POST /backtests/runs` when `publish_to_database=true`.

## Environment

```bash
DATABASE_AGENT_URL=http://database-agent:8004
DATABASE_AGENT_API_KEY=dev_database_key
```

If `DATABASE_AGENT_URL` is not configured, publishing is skipped and the simulation result is still returned.

## Safety

Publishing is storage-only. It does not submit, cancel, approve, or modify broker orders.

## Minimal request

```json
{
  "account_id": "1",
  "run_id": "run-1",
  "skill_id": "skill-1",
  "strategy_id": "sma-crossover-v1",
  "symbols": ["AAPL"],
  "initial_equity": 100000,
  "bars": {
    "AAPL": []
  }
}
```
