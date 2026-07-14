from datetime import datetime, timedelta

import pytest

from app.engine import run_backtest
from app.models import BacktestRunRequest, PriceBar


def bar(
    index: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def breakout_prefix(entry_volume: float) -> list[PriceBar]:
    return [
        bar(0, open_price=100, high=101, low=99, close=100, volume=1000),
        bar(1, open_price=101, high=102, low=100, close=101, volume=1000),
        bar(2, open_price=102, high=104, low=101, close=103, volume=1000),
        bar(3, open_price=100, high=101, low=99, close=100, volume=entry_volume),
    ]


def request(rows: list[PriceBar], **overrides) -> BacktestRunRequest:
    payload = {
        "symbols": ["AAPL"],
        "initial_equity": 10000,
        "bars": {"AAPL": rows},
        "strategy": "breakout",
        "fast_window": 1,
        "slow_window": 2,
        "risk_per_trade": 0.01,
        "max_position_pct": 1.0,
        "stop_loss_pct": 0.10,
        "fee_bps": 0,
        "slippage_bps": 0,
        "use_risk_agent": False,
    }
    payload.update(overrides)
    return BacktestRunRequest(**payload)


def test_entry_is_partially_filled_by_bar_volume_with_linear_impact():
    result = run_backtest(
        request(
            breakout_prefix(entry_volume=50),
            max_volume_participation_pct=0.10,
            market_impact_bps=20,
        )
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.requested_quantity == 10
    assert buy.quantity == 5
    assert buy.fill_status == "partial"
    assert buy.participation_rate == pytest.approx(0.10)
    assert buy.market_impact_bps == pytest.approx(2.0)
    assert buy.price == pytest.approx(100.02)
    assert result.metrics.partial_fills == 1


def test_zero_volume_records_liquidity_rejection_without_fabricated_fill():
    result = run_backtest(
        request(
            breakout_prefix(entry_volume=0),
            max_volume_participation_pct=0.10,
        )
    )

    assert not any(trade.side == "buy" for trade in result.trades)
    assert result.metrics.liquidity_rejections == 1
    assert result.liquidity_rejections[0].side == "buy"
    assert result.liquidity_rejections[0].reason == "bar_volume_limit"


def test_invalid_combined_sell_price_adjustment_is_rejected():
    with pytest.raises(ValueError, match="combined slippage and market impact"):
        request(
            breakout_prefix(entry_volume=1000),
            slippage_bps=6000,
            market_impact_bps=4000,
        )


def test_partial_stop_exit_continues_until_position_is_closed():
    rows = breakout_prefix(entry_volume=1000) + [
        bar(4, open_price=85, high=86, low=84, close=85, volume=5),
        bar(5, open_price=80, high=81, low=79, close=80, volume=1000),
    ]
    result = run_backtest(
        request(rows, max_volume_participation_pct=1.0)
    )

    sells = [trade for trade in result.trades if trade.side == "sell"]
    assert [trade.quantity for trade in sells] == [5, 5]
    assert sells[0].fill_status == "partial"
    assert sells[0].position_closed is False
    assert sells[1].position_closed is True
    assert sells[1].round_trip_realized_pnl == pytest.approx(-175)
    assert result.metrics.trade_count == 1
    assert result.metrics.realized_net_profit == pytest.approx(-175)
    assert result.metrics.open_position_count == 0


def test_partial_take_profit_waits_for_limit_to_be_reached_again():
    rows = breakout_prefix(entry_volume=1000) + [
        bar(4, open_price=110, high=121, low=109, close=115, volume=5),
        bar(5, open_price=110, high=115, low=109, close=114, volume=1000),
        bar(6, open_price=118, high=121, low=117, close=120, volume=1000),
    ]
    result = run_backtest(
        request(rows, max_volume_participation_pct=1.0)
    )

    sells = [trade for trade in result.trades if trade.side == "sell"]
    assert [trade.timestamp for trade in sells] == [rows[4].timestamp, rows[6].timestamp]
    assert [trade.price for trade in sells] == [120, 120]
    assert [trade.quantity for trade in sells] == [5, 5]
    assert result.metrics.trade_count == 1
    assert result.metrics.open_position_count == 0
    assert result.metrics.liquidity_rejections == 0
