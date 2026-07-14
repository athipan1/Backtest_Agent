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
- Next-bar-open execution to prevent same-bar look-ahead
- Gap-aware stop-loss and take-profit fills
- Round-trip fee accounting with realized/unrealized P/L separation
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
- `POST /backtest/compare`
- `POST /backtest/walk-forward`
- `POST /backtest/report`
- `POST /backtest/run-and-publish`
- `POST /backtest/run-and-publish-batch`

## Execution realism

Signals are generated after a bar closes and execute at the next available bar
open. This prevents a strategy from using a close that was not yet observable
and filling at that same close. Stop-loss orders fill at the opening price when
the market gaps through the stop, and configured slippage is applied to exits.

Entry and exit fees are both included in realized trade P/L. Results separately
report `realized_net_profit`, `unrealized_pnl`, and `open_position_count`.
Set `force_close_at_end=true` to liquidate remaining positions at the final close
for closed-trade comparisons. Scheduled runs can set
`BACKTEST_FORCE_CLOSE_AT_END=true`; this setting and the engine version are part
of the deterministic run identity.

## Next phases

- Risk Agent adapter
- Performance Agent report adapter
- Scanner replay mode
- Strategy comparison endpoint
- Rolling multi-fold walk-forward validation

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
