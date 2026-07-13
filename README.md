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

## Scheduled historical data

The hourly workflow fetches real historical OHLCV bars from Alpaca Market Data.
Set `BACKTEST_SYMBOLS=AAPL,MSFT,NVDA` to run a bounded batch. Each symbol is
simulated and published independently, producing exact per-symbol evidence for
Database_Agent without submitting broker orders.
It deliberately fails when market-data credentials or sufficient bars are not
available; it never falls back to embedded sample prices. Configure
`ALPACA_API_KEY_ID` and `ALPACA_SECRET_KEY` as repository secrets. This endpoint
uses market data only and does not submit, cancel, or inspect broker orders.

Each run stores a SHA-256 dataset fingerprint and derives a deterministic run ID
from the dataset and strategy parameters so repeated data cannot silently create
different backtest identities.
