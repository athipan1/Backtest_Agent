"""Real engine regressions: stress assumptions must reach execution prices."""
from copy import deepcopy

import pytest

from app.data_provider import HistoricalDataError, validate_price_bars
from app.execution_policy import ExecutionRealismPolicy
from app.models import BacktestRobustnessRequest, BacktestRunRequest
from app.promotion_robustness import _run_request
from app.robustness import _neighboring_windows, run_robustness_analysis
from app.risk_engine import run_backtest_with_risk


def request(**updates):
    payload = dict(
        symbols=["TEST"], initial_equity=100000, fast_window=1, slow_window=2,
        use_risk_agent=False, fee_bps=10, slippage_bps=5,
        bars={"TEST": [dict(timestamp=f"2026-01-{i:02}T00:00:00Z", open=p,
                            high=p+1, low=p-1, close=p, volume=10000)
                       for i,p in enumerate([100,101,102,103,104,105,106],1)]},
    )
    payload.update(updates)
    return BacktestRunRequest(**payload)


def test_spread_stress_changes_real_engine_fills_without_mutating_baseline():
    original = request()
    before = original.model_dump()
    baseline = _run_request(original)
    stressed = _run_request(original, policy=ExecutionRealismPolicy(bid_ask_spread_bps=100))
    assert stressed.trades[0].price > baseline.trades[0].price
    assert stressed.trades[-1].price < baseline.trades[-1].price
    assert stressed.metrics.final_equity < baseline.metrics.final_equity
    assert original.model_dump() == before
    assert _run_request(original) == baseline  # stress does not leak to the next run


def test_robustness_conversion_preserves_configured_execution_policy():
    req = request(execution_policy={"bid_ask_spread_bps":100, "quantity_increment":2})
    robust_req = BacktestRobustnessRequest(**req.model_dump(), monte_carlo_simulations=100)
    actual = run_robustness_analysis(robust_req)
    expected = run_backtest_with_risk(req)
    assert actual.baseline.trades == expected.trades
    assert actual.baseline.metrics == expected.metrics
    assert all(t.quantity % 2 == 0 for t in actual.baseline.trades)
    plain = run_robustness_analysis(BacktestRobustnessRequest(**request().model_dump()))
    assert actual.baseline.trades[0].price > plain.baseline.trades[0].price


@pytest.mark.parametrize("strategy", ["mean_reversion", "breakout"])
def test_one_dimensional_strategy_probes_have_no_baseline_replicas(strategy):
    req = BacktestRobustnessRequest(**request(strategy=strategy,fast_window=5,slow_window=20).model_dump())
    probes = _neighboring_windows(req)
    assert probes == [(5,18),(5,19),(5,21),(5,22)]
    assert len({slow for _,slow in probes}) == 4
    assert all(slow != req.slow_window for _,slow in probes)


def test_small_neighborhood_is_reported_honestly_without_padding():
    req = BacktestRobustnessRequest(**request(strategy="mean_reversion").model_dump())
    assert _neighboring_windows(req) == [(1,3),(1,4)]


@pytest.mark.parametrize("field,value", [
    ("volume",float('inf')), ("volume",float('nan')), ("high",float('inf')),
    ("timestamp","2026-01-01T00:00:00"), ("timestamp","2026-01-01T00:00:00+00:99"),
])
def test_market_data_ingestion_fails_closed_on_invalid_numeric_or_timezone(field,value):
    row=request().bars['TEST'][0].model_dump(mode='json');row[field]=value
    with pytest.raises(HistoricalDataError,match='invalid'):
        validate_price_bars([row],symbol='TEST',minimum_bars=1)


@pytest.mark.parametrize("strategy", ["sma_crossover","trend_following","mean_reversion","breakout"])
def test_future_price_changes_do_not_change_earlier_signal_execution(strategy):
    req=request(strategy=strategy)
    # A deliberately extreme future tail must not affect preceding fills/equity.
    changed=deepcopy(req)
    last=changed.bars['TEST'][-1]
    last.open=500;last.high=501;last.low=499;last.close=500;last.volume=2
    original=run_backtest_with_risk(req);future=run_backtest_with_risk(changed)
    cutoff=last.timestamp
    assert [t for t in original.trades if t.timestamp<cutoff] == [t for t in future.trades if t.timestamp<cutoff]
    assert original.equity_curve[:-1] == future.equity_curve[:-1]
