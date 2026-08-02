from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import BacktestMetrics
from app.multi_strategy_walk_forward import (
    WalkForwardMultiStrategyRequest,
    WalkForwardStabilityCriteria,
    run_candidate_walk_forward_stability,
    run_nested_walk_forward_stability,
)


def bars(count=630):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(count):
        price += 0.35 if index % 12 < 8 else -0.20
        rows.append(
            {
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": price - 0.2,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000_000,
            }
        )
    return rows


def metrics(**overrides):
    payload = {
        "initial_equity": 100000,
        "final_equity": 105000,
        "net_profit": 5000,
        "return_pct": 0.05,
        "trade_count": 5,
        "winning_trades": 3,
        "losing_trades": 2,
        "win_rate": 0.60,
        "gross_profit": 7500,
        "gross_loss": -2500,
        "profit_factor": 3.0,
        "expectancy": 1000,
        "max_drawdown": -0.05,
        "annualized_return": 0.12,
        "annualized_volatility": 0.18,
        "sharpe_ratio": 1.10,
        "sortino_ratio": 1.40,
        "calmar_ratio": 2.40,
        "benchmark_return_pct": 0.03,
        "excess_return_pct": 0.02,
        "realized_net_profit": 5000,
        "unrealized_pnl": 0,
        "open_position_count": 0,
        "allocation_rejections": 0,
        "partial_fills": 0,
        "liquidity_rejections": 0,
        "risk_rejections": 0,
        "kill_switch_events": 0,
    }
    payload.update(overrides)
    return BacktestMetrics(**payload)


def request(count=630, candidates=None, **criteria):
    return WalkForwardMultiStrategyRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        bars={"AAPL": bars(count)},
        candidates=candidates
        or [
            {
                "strategy_id": "trend-test-v1",
                "name": "Trend test",
                "strategy": "trend_following",
                "fast_window": 10,
                "slow_window": 30,
            }
        ],
        walk_forward_criteria=WalkForwardStabilityCriteria(**criteria),
        fee_bps=0,
        slippage_bps=0,
        force_close_at_end=True,
    )


def test_overlapping_test_windows_require_explicit_opt_in():
    with pytest.raises(ValidationError, match="allow_overlapping_test_windows"):
        WalkForwardStabilityCriteria(
            train_bars=60,
            test_bars=60,
            step_bars=30,
        )

    criteria = WalkForwardStabilityCriteria(
        train_bars=60,
        test_bars=60,
        step_bars=30,
        allow_overlapping_test_windows=True,
    )
    assert criteria.step_bars < criteria.test_bars


def test_walk_forward_requires_minimum_number_of_out_of_sample_windows():
    value = request(count=300)

    result = run_candidate_walk_forward_stability(
        request=value,
        candidate=value.candidates[0],
    )

    assert result.status == "insufficient_history"
    assert result.evaluated_windows < 4
    assert result.passed is False
    assert result.gates["window_count"] is False
    assert any("walk_forward_window_count" in reason for reason in result.reasons)


def test_walk_forward_passes_stable_out_of_sample_results(monkeypatch):
    value = request()

    monkeypatch.setattr(
        "app.multi_strategy_walk_forward.run_backtest_with_risk",
        lambda _: SimpleNamespace(metrics=metrics(), warnings=[]),
    )

    result = run_candidate_walk_forward_stability(
        request=value,
        candidate=value.candidates[0],
    )

    assert result.status == "completed"
    assert result.evaluated_windows == 4
    assert result.profitable_windows == 4
    assert result.profitable_window_rate == 1.0
    assert result.train_eligible_window_rate == 1.0
    assert result.median_sharpe_ratio == 1.10
    assert result.median_profit_factor == 3.0
    assert result.worst_max_drawdown == -0.05
    assert result.overlapping_test_windows is False
    assert result.passed is True
    assert all(result.gates.values())


def test_walk_forward_rejects_strategy_that_only_works_in_one_window(monkeypatch):
    value = request()
    test_outcomes = [
        metrics(return_pct=0.08, sharpe_ratio=1.4, profit_factor=2.0),
        metrics(
            final_equity=98000,
            net_profit=-2000,
            return_pct=-0.02,
            sharpe_ratio=-0.4,
            profit_factor=0.7,
        ),
        metrics(
            final_equity=97000,
            net_profit=-3000,
            return_pct=-0.03,
            sharpe_ratio=-0.6,
            profit_factor=0.6,
        ),
        metrics(
            final_equity=99000,
            net_profit=-1000,
            return_pct=-0.01,
            sharpe_ratio=-0.2,
            profit_factor=0.8,
        ),
    ]
    outcomes = iter(
        result
        for test_result in test_outcomes
        for result in (metrics(), test_result)
    )
    monkeypatch.setattr(
        "app.multi_strategy_walk_forward.run_backtest_with_risk",
        lambda _: SimpleNamespace(metrics=next(outcomes), warnings=[]),
    )

    result = run_candidate_walk_forward_stability(
        request=value,
        candidate=value.candidates[0],
    )

    assert result.evaluated_windows == 4
    assert result.profitable_windows == 1
    assert result.profitable_window_rate == 0.25
    assert result.passed is False
    assert result.gates["profitable_window_rate"] is False
    assert result.gates["median_sharpe_ratio"] is False
    assert result.gates["median_profit_factor"] is False


def test_walk_forward_train_and_test_windows_do_not_overlap(monkeypatch):
    value = request()
    observed = []

    def capture(run_request):
        window = run_request.bars["AAPL"]
        observed.append((window[0].timestamp, window[-1].timestamp, len(window)))
        return SimpleNamespace(metrics=metrics(), warnings=[])

    monkeypatch.setattr(
        "app.multi_strategy_walk_forward.run_backtest_with_risk",
        capture,
    )

    result = run_candidate_walk_forward_stability(
        request=value,
        candidate=value.candidates[0],
    )

    assert len(observed) == result.evaluated_windows * 2 == 8
    train_windows = observed[0::2]
    test_windows = observed[1::2]
    assert all(length == 126 for _, _, length in observed)
    assert train_windows[0][0] == value.bars["AAPL"][0].timestamp
    assert test_windows[0][0] == value.bars["AAPL"][126].timestamp
    assert train_windows[0][1] < test_windows[0][0]
    assert test_windows[0][1] < test_windows[1][0]


def test_nested_walk_forward_selects_on_train_then_tests_selected_candidate(
    monkeypatch,
):
    candidates = [
        {
            "strategy_id": "trend-v1",
            "name": "Trend",
            "strategy": "trend_following",
            "fast_window": 10,
            "slow_window": 30,
        },
        {
            "strategy_id": "mean-v1",
            "name": "Mean",
            "strategy": "mean_reversion",
            "fast_window": 5,
            "slow_window": 20,
        },
    ]
    value = request(candidates=candidates)
    selected_ids = ["trend-v1", "mean-v1", "trend-v1", "mean-v1"]
    selections = iter(selected_ids)

    def fake_train_selection(train_request):
        strategy_id = next(selections)
        candidate = next(
            item
            for item in train_request.candidates
            if item.strategy_id == strategy_id
        )
        selected = SimpleNamespace(
            strategy_id=strategy_id,
            name=candidate.name,
            score=1.0,
            metrics=metrics(),
            warnings=[],
        )
        return SimpleNamespace(best_eligible=selected, best_overall=selected)

    tested = []

    def fake_test(run_request):
        tested.append(
            (
                run_request.strategy,
                run_request.bars["AAPL"][0].timestamp,
            )
        )
        return SimpleNamespace(metrics=metrics(), warnings=[])

    monkeypatch.setattr(
        "app.multi_strategy_walk_forward.run_multi_strategy_backtest",
        fake_train_selection,
    )
    monkeypatch.setattr(
        "app.multi_strategy_walk_forward.run_backtest_with_risk",
        fake_test,
    )

    result = run_nested_walk_forward_stability(value)

    assert result.selection_method == "nested_train_select_test_evaluate"
    assert [window.selected_strategy_id for window in result.windows] == selected_ids
    assert [strategy for strategy, _ in tested] == [
        "trend_following",
        "mean_reversion",
        "trend_following",
        "mean_reversion",
    ]
    assert tested[0][1] == value.bars["AAPL"][126].timestamp
    assert tested[1][1] == value.bars["AAPL"][378 - 126].timestamp
    assert result.selection_counts == {"mean-v1": 2, "trend-v1": 2}
    assert result.latest_selected_strategy_id == "mean-v1"
    assert result.latest_selection_eligible is True
