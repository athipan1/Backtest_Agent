from app.models import WalkForwardRequest
from app.walk_forward import run_walk_forward_validation, split_bars_by_ratio


def bars(count=20):
    rows = []
    for index in range(1, count + 1):
        close = 10 + (index % 6)
        rows.append(
            {
                "timestamp": f"2026-01-{index:02d}T00:00:00Z",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
        )
    return rows


def test_split_bars_by_ratio_keeps_chronological_order():
    source = [item for item in WalkForwardRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        bars={"AAPL": bars(10)},
        candidates=[{"name": "fast", "fast_window": 2, "slow_window": 3}],
    ).bars["AAPL"]]

    train, test = split_bars_by_ratio(source, 0.6)

    assert len(train) == 6
    assert len(test) == 4
    assert train[-1].timestamp < test[0].timestamp


def test_walk_forward_selects_train_winner_and_tests_it():
    request = WalkForwardRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        train_ratio=0.6,
        min_train_bars=5,
        min_test_bars=3,
        fee_bps=0,
        slippage_bps=0,
        bars={"AAPL": bars(20)},
        candidates=[
            {"name": "fast", "fast_window": 2, "slow_window": 3},
            {"name": "slow", "fast_window": 3, "slow_window": 5},
        ],
    )

    result = run_walk_forward_validation(request)

    assert result.symbols == ["AAPL"]
    assert result.selected_candidate is not None
    assert result.selected_candidate.rank == 1
    assert len(result.train_ranking) == 2
    assert result.test_result is not None
    assert result.train_bars["AAPL"] == 12
    assert result.test_bars["AAPL"] == 8


def test_walk_forward_records_insufficient_split_reasons():
    request = WalkForwardRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        train_ratio=0.5,
        min_train_bars=10,
        min_test_bars=10,
        bars={"AAPL": bars(12)},
        candidates=[{"name": "fast", "fast_window": 2, "slow_window": 3}],
    )

    result = run_walk_forward_validation(request)

    assert "AAPL_train_bars_below_minimum" in result.reasons
    assert "AAPL_test_bars_below_minimum" in result.reasons
    assert result.passed is False
