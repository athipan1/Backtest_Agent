from app.engine import run_backtest, sma
from app.models import BacktestRunRequest


def bars(closes):
    rows = []
    for idx, close in enumerate(closes, start=1):
        rows.append(
            {
                "timestamp": f"2026-01-{idx:02d}T00:00:00Z",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
        )
    return rows


def test_sma_returns_none_until_enough_values():
    assert sma([1, 2], 3) is None
    assert sma([1, 2, 3], 3) == 2


def test_run_backtest_returns_equity_curve_and_trades():
    request = BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        fast_window=2,
        slow_window=3,
        fee_bps=0,
        slippage_bps=0,
        bars={"AAPL": bars([10, 11, 12, 13, 12, 11, 10])},
    )

    result = run_backtest(request)

    assert result.strategy == "sma_crossover"
    assert result.symbols == ["AAPL"]
    assert len(result.equity_curve) == 7
    assert len(result.trades) >= 2
    assert result.trades[0].side == "buy"
    assert result.trades[-1].side == "sell"
    assert result.metrics.trade_count >= 1


def test_run_backtest_warns_when_not_enough_bars():
    request = BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        fast_window=2,
        slow_window=5,
        bars={"AAPL": bars([10, 11])},
    )

    result = run_backtest(request)

    assert "AAPL has fewer bars than slow_window" in result.warnings
    assert result.metrics.trade_count == 0
