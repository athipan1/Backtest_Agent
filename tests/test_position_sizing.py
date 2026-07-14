from datetime import datetime, timedelta

from app.engine import _position_size, run_backtest
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


def test_position_size_uses_stop_distance_and_current_equity():
    full_equity = _position_size(
        cash=100000,
        current_equity=100000,
        entry_price=100,
        stop_loss=90,
        risk_per_trade=0.01,
        max_position_pct=1.0,
        fee_bps=0,
    )
    reduced_equity = _position_size(
        cash=90000,
        current_equity=90000,
        entry_price=100,
        stop_loss=90,
        risk_per_trade=0.01,
        max_position_pct=1.0,
        fee_bps=0,
    )

    assert full_equity == 100
    assert reduced_equity == 90


def test_position_size_applies_position_cap_and_fee_aware_cash_limit():
    position_capped = _position_size(
        cash=100000,
        current_equity=100000,
        entry_price=100,
        stop_loss=99,
        risk_per_trade=0.10,
        max_position_pct=0.10,
        fee_bps=0,
    )
    cash_capped = _position_size(
        cash=1000,
        current_equity=100000,
        entry_price=100,
        stop_loss=99,
        risk_per_trade=0.10,
        max_position_pct=1.0,
        fee_bps=100,
    )

    assert position_capped == 100
    assert cash_capped == 9


def sizing_rows() -> list[PriceBar]:
    return [
        bar(0, open_price=100, high=101, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        bar(2, open_price=102, high=104, low=101, close=103),
        bar(3, open_price=120, high=122, low=119, close=121),
    ]


def sizing_request(*, use_risk_agent: bool) -> BacktestRunRequest:
    return BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=10000,
        bars={"AAPL": sizing_rows()},
        strategy="breakout",
        fast_window=1,
        slow_window=2,
        risk_per_trade=0.01,
        max_position_pct=1.0,
        stop_loss_pct=0.10,
        fee_bps=0,
        slippage_bps=0,
        use_risk_agent=use_risk_agent,
    )


def test_plain_and_risk_engines_use_risk_based_quantity():
    plain = run_backtest(sizing_request(use_risk_agent=False))
    risk_aware = run_backtest_with_risk(sizing_request(use_risk_agent=True))

    assert plain.trades[0].quantity == 8
    assert risk_aware.trades[0].quantity == 8
    assert plain.position_sizing_model == "current_equity_risk_and_position_cap"
    assert risk_aware.position_sizing_model == "current_equity_risk_and_position_cap"


def test_risk_engine_reduces_quantity_after_realized_loss():
    rows = [
        bar(0, open_price=100, high=101, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        bar(2, open_price=102, high=104, low=101, close=103),
        # First entry at 100 risks 10 per share and stops at 90.
        bar(3, open_price=100, high=101, low=89, close=95),
        # This close creates the next breakout signal.
        bar(4, open_price=96, high=111, low=95, close=110),
        # Current equity is now 9,900, so 1% risk permits 9 shares.
        bar(5, open_price=110, high=112, low=109, close=111),
    ]
    request = BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=10000,
        bars={"AAPL": rows},
        strategy="breakout",
        fast_window=1,
        slow_window=2,
        risk_per_trade=0.01,
        max_position_pct=1.0,
        stop_loss_pct=0.10,
        fee_bps=0,
        slippage_bps=0,
        use_risk_agent=True,
    )

    result = run_backtest_with_risk(request)
    buys = [trade for trade in result.trades if trade.side == "buy"]

    assert [trade.quantity for trade in buys] == [10, 9]
