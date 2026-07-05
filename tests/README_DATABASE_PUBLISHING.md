# Database Publishing Tests

These focused tests verify that Backtest_Agent can normalize simulation outputs into the Database_Agent `/backtests/runs` payload shape without touching broker/execution flows.

Run:

```bash
python -m pytest tests/test_database_publisher.py tests/test_run_and_publish_endpoint.py
```
