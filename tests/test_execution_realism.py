from datetime import datetime, timedelta

import pytest

from app.engine import run_backtest
from app.models import BacktestRunRequest, PriceBar


def bar(index: int, *, open_price: float, high: float, low: float, close: float) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def breakout_request(rows: list[PriceBar], **overrides) -> BacktestRunRequest:
    payload = {
        "symbols": ["AAPL"],
        "initial_equity": 10000,
        "bars": {"AAPL": rows},
        "strategy": "breakout",
        "fast_window": 1,
        "slow_window": 2,
        "max_position_pct": 0.10,
        "stop_loss_pct": 0.03,
        "reward_risk_ratio": 2.0,
        "fee_bps": 0,
        "slippage_bps": 0,
        "use_risk_agent": False,
    }
    payload.update(overrides)
    return BacktestRunRequest(**payload)


def signal_then_gap_rows() -> list[PriceBar]:
    return [
        bar(0, open_price=100, high=100, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        # This close breaks the previous high and creates a buy signal.
        bar(2, open_price=102, high=104, low=101, close=103),
        # The signal must fill here, not retroactively at the prior close.
        bar(3, open_price=120, high=122, low=119, close=121),
    ]


def test_close_signal_fills_at_next_bar_open_without_lookahead():
    result = run_backtest(breakout_request(signal_then_gap_rows()))

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.timestamp == signal_then_gap_rows()[3].timestamp
    assert buy.price == 120
    assert result.execution_model == "next_bar_open"


def test_open_position_metrics_reconcile_unrealized_pnl_and_final_equity():
    result = run_backtest(breakout_request(signal_then_gap_rows()))

    assert result.metrics.trade_count == 0
    assert result.metrics.realized_net_profit == 0
    assert result.metrics.unrealized_pnl == 8
    assert result.metrics.open_position_count == 1
    assert result.metrics.net_profit == pytest.approx(
        result.metrics.realized_net_profit + result.metrics.unrealized_pnl
    )


def test_realized_pnl_includes_entry_and_exit_fees():
    rows = [
        bar(0, open_price=100, high=100, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        bar(2, open_price=102, high=104, low=101, close=103),
        bar(3, open_price=104, high=110, low=103, close=110),
    ]
    result = run_backtest(
        breakout_request(rows, fee_bps=100, force_close_at_end=True)
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    sell = next(trade for trade in result.trades if trade.side == "sell")
    expected = (
        (sell.price - buy.price) * buy.quantity
        - buy.fees
        - sell.fees
    )

    assert sell.reason == "end_of_data"
    assert sell.realized_pnl == pytest.approx(expected)
    assert result.metrics.realized_net_profit == pytest.approx(expected)
    assert result.metrics.unrealized_pnl == 0
    assert result.metrics.open_position_count == 0
    assert result.metrics.net_profit == pytest.approx(expected)


def test_force_close_at_end_is_explicit_and_optional():
    open_result = run_backtest(breakout_request(signal_then_gap_rows()))
    closed_result = run_backtest(
        breakout_request(signal_then_gap_rows(), force_close_at_end=True)
    )

    assert open_result.metrics.open_position_count == 1
    assert not any(trade.reason == "end_of_data" for trade in open_result.trades)
    assert closed_result.metrics.open_position_count == 0
    assert closed_result.trades[-1].reason == "end_of_data"
