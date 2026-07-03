from datetime import datetime, timedelta

from app.engine import Position, _intrabar_exit_price, run_backtest
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


def request_with_bars(bars: list[PriceBar]) -> BacktestRunRequest:
    return BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=10000,
        bars={"AAPL": bars},
        strategy="breakout",
        fast_window=1,
        slow_window=2,
        max_position_pct=0.10,
        stop_loss_pct=0.03,
        reward_risk_ratio=2.0,
        fee_bps=0,
        slippage_bps=0,
        use_risk_agent=False,
    )


def test_intrabar_take_profit_exit_is_detected():
    position = Position(quantity=10, average_price=100, stop_loss=97, take_profit=106)
    exit_price, reason = _intrabar_exit_price(
        position,
        bar(1, open_price=101, high=107, low=100, close=106),
    )

    assert exit_price == 106
    assert reason == "take_profit"


def test_intrabar_stop_loss_wins_when_stop_and_take_profit_hit_same_bar():
    position = Position(quantity=10, average_price=100, stop_loss=97, take_profit=106)
    exit_price, reason = _intrabar_exit_price(
        position,
        bar(1, open_price=100, high=107, low=96, close=105),
    )

    assert exit_price == 97
    assert reason == "stop_loss"


def test_run_backtest_exits_open_position_on_take_profit_bar():
    result = run_backtest(
        request_with_bars([
            bar(0, open_price=100, high=100, low=99, close=100),
            bar(1, open_price=101, high=102, low=100, close=101),
            # Breakout strategy buys at close 103. Stop = 99.91, TP = 109.18.
            bar(2, open_price=102, high=104, low=101, close=103),
            bar(3, open_price=104, high=110, low=103, close=109),
        ])
    )

    sell_trades = [trade for trade in result.trades if trade.side == "sell"]
    assert len(sell_trades) == 1
    assert sell_trades[0].reason == "take_profit"
    assert sell_trades[0].price == 109.18
    assert sell_trades[0].realized_pnl > 0


def test_run_backtest_exits_open_position_on_stop_loss_bar():
    result = run_backtest(
        request_with_bars([
            bar(0, open_price=100, high=100, low=99, close=100),
            bar(1, open_price=101, high=102, low=100, close=101),
            # Breakout strategy buys at close 103. Stop = 99.91.
            bar(2, open_price=102, high=104, low=101, close=103),
            bar(3, open_price=101, high=102, low=99, close=100),
        ])
    )

    sell_trades = [trade for trade in result.trades if trade.side == "sell"]
    assert len(sell_trades) == 1
    assert sell_trades[0].reason == "stop_loss"
    assert sell_trades[0].price == 99.91
    assert sell_trades[0].realized_pnl < 0
