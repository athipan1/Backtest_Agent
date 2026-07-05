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

## Hourly GitHub Actions Workflow

The workflow `.github/workflows/hourly_backtest.yml` runs automatically once per hour:

```yaml
schedule:
  - cron: "7 * * * *"
```

It also supports manual runs through `workflow_dispatch`.

The workflow:

1. Installs Python dependencies.
2. Runs focused publisher tests.
3. Executes `scripts/run_hourly_backtest.py`.
4. Uploads `reports/hourly-backtest-result.json` as an artifact.

## Environment

```bash
DATABASE_AGENT_URL=http://database-agent:8004
DATABASE_AGENT_API_KEY=dev_database_key
```

For GitHub Actions, configure these as repository secrets:

```bash
DATABASE_AGENT_URL
DATABASE_AGENT_API_KEY
```

Optional repository variables:

```bash
BACKTEST_ACCOUNT_ID
BACKTEST_SYMBOL
BACKTEST_SKILL_ID
BACKTEST_STRATEGY_ID
BACKTEST_TIMEFRAME
BACKTEST_INITIAL_EQUITY
BACKTEST_STRATEGY
BACKTEST_FAST_WINDOW
BACKTEST_SLOW_WINDOW
BACKTEST_FEE_BPS
BACKTEST_SLIPPAGE_BPS
PUBLISH_TO_DATABASE
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
