## Backtest Database Integration Checklist

- [ ] Backtest still performs simulation only
- [ ] No broker order submit/cancel/replace code added
- [ ] Database publishing targets `/backtests/runs`
- [ ] Endpoint works when publishing is disabled
- [ ] Tests cover payload shape and endpoint behavior

## Validation

```bash
python -m pytest tests/test_database_publisher.py tests/test_run_and_publish_endpoint.py
python -m pytest
```
