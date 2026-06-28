from app.compare import compare_strategies, score_result
from app.models import BacktestCompareRequest


def bars(closes):
    return [
        {
            "timestamp": f"2026-01-{index:02d}T00:00:00Z",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        }
        for index, close in enumerate(closes, start=1)
    ]


def test_score_penalizes_no_trades_and_risk_rejections():
    clean = score_result(return_pct=0.10, max_drawdown=-0.02, profit_factor=1.5, trade_count=5, risk_rejections=0)
    no_trades = score_result(return_pct=0.10, max_drawdown=-0.02, profit_factor=1.5, trade_count=0, risk_rejections=0)
    rejected = score_result(return_pct=0.10, max_drawdown=-0.02, profit_factor=1.5, trade_count=5, risk_rejections=10)

    assert clean > no_trades
    assert clean > rejected


def test_compare_strategies_returns_ranked_results():
    request = BacktestCompareRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        fee_bps=0,
        slippage_bps=0,
        bars={"AAPL": bars([10, 11, 12, 13, 12, 11, 10, 11, 12])},
        candidates=[
            {"name": "fast", "fast_window": 2, "slow_window": 3},
            {"name": "slow", "fast_window": 3, "slow_window": 5},
        ],
    )

    result = compare_strategies(request)

    assert result.symbols == ["AAPL"]
    assert len(result.ranked_results) == 2
    assert result.best is not None
    assert [item.rank for item in result.ranked_results] == [1, 2]
    assert result.ranked_results[0].score >= result.ranked_results[1].score
