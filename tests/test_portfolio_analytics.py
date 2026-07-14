from datetime import datetime, timedelta

import pytest

from app.analytics import (
    equal_weight_buy_and_hold_return,
    portfolio_analytics,
)
from app.engine import max_drawdown, run_backtest
from app.models import BacktestRunRequest, EquityPoint, PriceBar


def point(index: int, equity: float) -> EquityPoint:
    return EquityPoint(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        equity=equity,
    )


def price_bar(index: int, open_price: float, close: float) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        open=open_price,
        high=max(open_price, close) + 1,
        low=min(open_price, close) - 1,
        close=close,
        volume=1000,
    )


def test_drawdown_includes_loss_from_initial_equity():
    curve = [point(0, 90), point(1, 95)]

    assert max_drawdown(curve, initial_equity=100) == -0.10


def test_equal_weight_benchmark_averages_constituent_buy_and_hold_returns():
    bars = {
        "AAPL": [price_bar(0, 100, 100), price_bar(1, 110, 120)],
        "MSFT": [price_bar(0, 200, 200), price_bar(1, 190, 180)],
    }

    result = equal_weight_buy_and_hold_return(["MSFT", "AAPL"], bars)

    assert result == pytest.approx(0.05)


def test_risk_adjusted_metrics_are_annualized_and_benchmark_aware():
    curve = [point(0, 100), point(1, 110), point(2, 99), point(3, 105)]

    result = portfolio_analytics(
        initial_equity=100,
        final_equity=105,
        curve=curve,
        max_drawdown=-0.10,
        periods_per_year=4,
        annual_risk_free_rate=0.0,
        benchmark_return_pct=0.02,
    )

    assert result.annualized_return == pytest.approx(0.05)
    assert result.annualized_volatility is not None
    assert result.sharpe_ratio is not None
    assert result.sortino_ratio is not None
    assert result.calmar_ratio == pytest.approx(0.5)
    assert result.benchmark_return_pct == pytest.approx(0.02)
    assert result.excess_return_pct == pytest.approx(0.03)


def test_engine_reports_strategy_underperformance_against_buy_and_hold():
    rows = [
        price_bar(0, 100, 100),
        price_bar(1, 110, 110),
        price_bar(2, 120, 120),
    ]
    request = BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=10000,
        bars={"AAPL": rows},
        fast_window=2,
        slow_window=5,
        fee_bps=0,
        slippage_bps=0,
    )

    result = run_backtest(request)

    assert result.metrics.return_pct == 0
    assert result.metrics.benchmark_return_pct == pytest.approx(0.20)
    assert result.metrics.excess_return_pct == pytest.approx(-0.20)
    assert result.metrics.annualized_return == 0
    assert result.metrics.sharpe_ratio is None
    assert result.benchmark_model == (
        "equal_weight_buy_and_hold_first_open_to_last_close"
    )
