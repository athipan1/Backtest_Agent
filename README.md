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
- Current-equity risk-based position sizing
- Synchronous multi-symbol portfolio allocation
- Volume-aware partial fills and linear market impact
- Equity curve
- Risk-adjusted performance and buy-and-hold benchmark metrics

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
- `POST /backtest/robustness`
- `POST /backtest/compare`
- `POST /backtest/walk-forward`
- `POST /backtest/multi-strategy/walk-forward`
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

## Position sizing

Long entries are sized from current marked-to-market equity and the distance
between entry and stop loss:

```text
risk budget      = current equity * risk_per_trade
risk quantity    = risk budget / (entry price - stop loss)
position quantity = minimum of risk quantity, position cap, and fee-aware cash quantity
```

This prevents a backtest from continuing to size every trade from the original
starting balance after gains or losses. The local Risk_Agent-compatible adapter
independently enforces the same risk budget and rejects invalid long protection
prices.

Scheduled runs can configure the policy with:

```text
BACKTEST_RISK_PER_TRADE
BACKTEST_MAX_POSITION_PCT
BACKTEST_STOP_LOSS_PCT
BACKTEST_REWARD_RISK_RATIO
BACKTEST_USE_RISK_AGENT
BACKTEST_MAX_TRADES_PER_DAY
BACKTEST_EMERGENCY_HALT
```

Risk and execution parameters are stored with Database_Agent evidence and are
part of the deterministic run identity, so changing the risk policy produces a
different run ID.

## Synchronous portfolio allocation

Bars that share a timestamp are processed as one portfolio batch. The engine
marks every available symbol at the open, handles gap exits and pending sells,
then ranks new buy candidates by a stable uppercase symbol key before allocating
capital. Changing request order from `AAPL,MSFT` to `MSFT,AAPL` therefore cannot
change which candidate receives capital first.

New entries are constrained by:

- `max_total_exposure_pct`
- `max_open_positions`
- `cash_reserve_pct`
- `max_new_positions_per_bar`

Candidates that cannot receive at least one share are returned in
`allocation_rejections` with a deterministic reason such as
`max_open_positions`, `portfolio_exposure_limit`, or `cash_reserve_limit`.
The equity curve contains one point per timestamp rather than one point per
symbol event.

Scheduled runs can configure these controls with:

```text
BACKTEST_MAX_TOTAL_EXPOSURE_PCT
BACKTEST_MAX_OPEN_POSITIONS
BACKTEST_CASH_RESERVE_PCT
BACKTEST_MAX_NEW_POSITIONS_PER_BAR
```

Portfolio policy is persisted with Database_Agent evidence and included in the
deterministic run identity.

## Portfolio performance analytics

Every run now reports:

- `annualized_return`
- `annualized_volatility`
- `sharpe_ratio`
- `sortino_ratio`
- `calmar_ratio`
- `benchmark_return_pct`
- `excess_return_pct`

The benchmark is a frictionless equal-weight buy-and-hold portfolio of the same
symbols, measured from each symbol's first open to its final close. This makes
it clear when an active strategy earns less than simply holding its universe.
Drawdown includes losses from initial equity, including a loss on the first
period.

`periods_per_year` defaults to `252` for daily bars. Set it to match the input
timeframe before interpreting annualized statistics. The annual risk-free rate
defaults to zero. Scheduled runs can configure both with:

```text
BACKTEST_PERIODS_PER_YEAR
BACKTEST_ANNUAL_RISK_FREE_RATE
```

These assumptions and all analytics are stored with Database_Agent evidence.
Annualized ratios based on very short histories should not be treated as
statistically reliable.

## Volume-aware execution

Entries and exits are limited to a configurable percentage of each OHLCV bar's
reported volume. If an order is larger than the available quantity, the engine
records a partial fill and continues an unfinished exit on later bars. A bar
with zero available volume produces a `liquidity_rejection` rather than a
fabricated fill.

The optional market-impact model increases buy prices and decreases sell prices
linearly with participation rate:

```text
participation rate = filled quantity / bar volume
impact bps         = market_impact_bps * participation rate
```

Defaults preserve previous price behavior for datasets with sufficient non-zero
volume: `max_volume_participation_pct=1.0` and `market_impact_bps=0.0`. Zero
volume is still treated as unavailable liquidity. A more conservative starting
policy for liquid stocks is 10% participation with non-zero impact, but it
should be calibrated from the actual universe and timeframe. Scheduled runs can
use:

```text
BACKTEST_MAX_VOLUME_PARTICIPATION_PCT
BACKTEST_MARKET_IMPACT_BPS
```

Fill status, requested versus filled quantity, participation, impact, and
liquidity rejections are persisted with Database_Agent evidence.

## Strategy robustness testing

`POST /backtest/robustness` runs the baseline backtest and two deterministic
robustness checks:

1. Monte Carlo bootstraps completed round-trip trade P/L with replacement. It
   reports 5th/50th/95th-percentile final equity, probability of loss, and
   drawdown distribution.
2. Parameter sensitivity reruns the same data and execution policy across the
   valid neighboring `fast_window` and `slow_window` combinations. It reports
   the profitable-neighbor percentage, median/worst/best return, and baseline
   rank within the local parameter neighborhood.

Monte Carlo uses a local seeded random generator, so identical input and seed
produce identical output. The default requires at least five completed trades;
otherwise it returns `insufficient_data` instead of fabricated confidence. Set
`force_close_at_end=true` when the analysis should include the final open
position.

The trade-P/L bootstrap is an approximation: it tests outcome-order and sample
risk but does not synthesize new market bars. Sensitivity results should be
combined with walk-forward validation before promotion to paper trading.

## Production hourly nested promotion

Scheduled hourly validation is locked to `BACKTEST_MODE=nested_promotion` and a
production runtime environment. `legacy_fixed` remains available only as an
explicit manual/research mode. Invalid modes fail closed and a nested failure
never falls back to the legacy executor. Hourly reports record the runtime mode
and validation path.

Nested walk-forward uses true abstention semantics. If no candidate passes the
training-window eligibility gates, the untouched future test window is recorded
as `decision=NO_TRADE`: no strategy is selected, capital remains cash, and the
strategy execution simulator is not invoked for that window. A failed candidate
is never promoted merely because it ranked best among the failed candidates.

Each nested window records `decision`, `selected_strategy_id`,
`train_selection_eligible`, and `capital_deployed`. Aggregate evidence includes
`abstention_rate`, `eligible_selection_rate`, `capital_deployed_rate`,
`no_trade_windows`, and `trade_windows`. Production promotion can fail when the
strategy abstains too often or produces too few eligible training selections.
Configure these gates with:

```text
BACKTEST_WALK_FORWARD_MAX_ABSTENTION_RATE
BACKTEST_WALK_FORWARD_MIN_ELIGIBLE_SELECTION_RATE
```

`BACKTEST_WALK_FORWARD_MIN_TRAIN_ELIGIBLE_RATE` is retained as a compatibility
fallback when the new minimum eligible-selection variable is not set. New
promotion evidence uses evidence version 2, and the walk-forward policy is part
of deterministic run identity. `NO_TRADE` is a successful validation outcome,
not an operational failure, but it never creates false promotion evidence.

## Next phases

- Time-series-aware statistical validation
- Sealed final holdout
- Historical experiment registry
- Historical data quality gate
- Full evidence hash reconciliation
- Execution realism v0.8
- Portfolio-level walk-forward validation
- Regime-specific backtest evidence

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
