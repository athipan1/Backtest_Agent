from datetime import datetime, timedelta

import pytest

from app.engine import run_backtest
from app.models import BacktestRunRequest, PriceBar
from app.risk_engine import run_backtest_with_risk


def bar(index: int, *, open_price: float, high: float, low: float, close: float) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def breakout_rows(offset: float = 0) -> list[PriceBar]:
    return [
        bar(0, open_price=100 + offset, high=101 + offset, low=99 + offset, close=100 + offset),
        bar(1, open_price=101 + offset, high=102 + offset, low=100 + offset, close=101 + offset),
        bar(2, open_price=102 + offset, high=104 + offset, low=101 + offset, close=103 + offset),
        bar(3, open_price=120 + offset, high=122 + offset, low=119 + offset, close=121 + offset),
    ]


def portfolio_request(symbols: list[str], **overrides) -> BacktestRunRequest:
    bars = {
        symbol: breakout_rows(0 if symbol == "AAPL" else 100)
        for symbol in symbols
    }
    payload = {
        "symbols": symbols,
        "initial_equity": 10000,
        "bars": bars,
        "strategy": "breakout",
        "fast_window": 1,
        "slow_window": 2,
        "risk_per_trade": 0.01,
        "max_position_pct": 1.0,
        "stop_loss_pct": 0.10,
        "fee_bps": 0,
        "slippage_bps": 0,
        "max_total_exposure_pct": 1.0,
        "max_open_positions": 1,
        "cash_reserve_pct": 0.0,
        "max_new_positions_per_bar": 25,
    }
    payload.update(overrides)
    return BacktestRunRequest(**payload)


@pytest.mark.parametrize("runner", [run_backtest, run_backtest_with_risk])
def test_symbol_input_order_does_not_change_allocation(runner):
    forward = runner(portfolio_request(["AAPL", "MSFT"]))
    reversed_order = runner(portfolio_request(["MSFT", "AAPL"]))

    forward_buys = [
        (trade.symbol, trade.quantity, trade.price)
        for trade in forward.trades
        if trade.side == "buy"
    ]
    reversed_buys = [
        (trade.symbol, trade.quantity, trade.price)
        for trade in reversed_order.trades
        if trade.side == "buy"
    ]

    assert forward_buys == reversed_buys == [("AAPL", 8.0, 120.0)]
    assert forward.metrics.final_equity == reversed_order.metrics.final_equity
    assert forward.allocation_policy == "timestamp_batch_symbol_ascending"
    assert [item.symbol for item in forward.allocation_rejections] == ["MSFT"]
    assert forward.allocation_rejections[0].reason == "max_open_positions"


def test_equity_curve_has_one_point_per_shared_timestamp():
    result = run_backtest(portfolio_request(["AAPL", "MSFT"]))

    assert len(result.equity_curve) == 4
    assert len({point.timestamp for point in result.equity_curve}) == 4


def test_force_close_replaces_final_timestamp_equity_point():
    result = run_backtest(
        portfolio_request(["AAPL", "MSFT"], force_close_at_end=True)
    )

    assert len(result.equity_curve) == 4
    assert len({point.timestamp for point in result.equity_curve}) == 4
    assert result.metrics.open_position_count == 0


def test_total_exposure_limit_clips_approved_quantity():
    result = run_backtest(
        portfolio_request(
            ["AAPL"],
            max_open_positions=25,
            max_total_exposure_pct=0.05,
        )
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.quantity == 4
    assert buy.quantity * buy.price <= 10000 * 0.05


def test_cash_reserve_limits_new_position_without_negative_cash():
    result = run_backtest(
        portfolio_request(
            ["AAPL"],
            max_open_positions=25,
            cash_reserve_pct=0.96,
        )
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.quantity == 3
    assert buy.quantity * buy.price <= 10000 * (1 - 0.96)


def test_max_new_positions_per_timestamp_records_rejection_reason():
    result = run_backtest(
        portfolio_request(
            ["MSFT", "AAPL"],
            max_open_positions=25,
            max_new_positions_per_bar=1,
        )
    )

    buys = [trade.symbol for trade in result.trades if trade.side == "buy"]
    assert buys == ["AAPL"]
    assert result.metrics.allocation_rejections == 1
    assert result.allocation_rejections[0].symbol == "MSFT"
    assert result.allocation_rejections[0].reason == "max_new_positions_per_bar"
