# Integration Flow

```text
Backtest_Agent
  POST /backtest/run-and-publish
    ↓
Database_Agent
  POST /backtests/runs
    ↓
Curator_Agent / Manager_Agent
  read skill backtest status before promotion
```

This flow lets the system build a history of strategy and skill test results before any paper/live promotion logic is added.
