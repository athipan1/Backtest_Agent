# Backtest Agent

Backtest Agent is the simulation service for the multi-agent trading system.

It replays historical OHLCV bars, generates strategy signals, simulates fee and slippage, tracks positions and equity, and returns performance metrics before paper or live trading.

## MVP features

- FastAPI service
- Health endpoint
- Backtest run endpoint
- SMA crossover strategy
- Long-only simulated execution
- Fee and slippage model
- Equity curve
- Basic performance metrics

## Run locally

```bash
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8016
```

## Test

```bash
PYTHONPATH=. pytest -q
```

## Endpoints

- `GET /health`
- `POST /backtest/run`

## Next phases

- Risk Agent adapter
- Performance Agent report adapter
- Scanner replay mode
- Strategy comparison endpoint
- Walk-forward validation
