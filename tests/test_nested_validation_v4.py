from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import nested_validation_v4 as v4
from app.models import BacktestMetrics, BacktestRunResult, PriceBar
from app.multi_strategy import MultiStrategyCandidate
from app.multi_strategy_walk_forward import (
    WalkForwardMultiStrategyRequest,
    WalkForwardStabilityCriteria,
)


def _metrics(*, return_pct: float = 0.05) -> BacktestMetrics:
    return BacktestMetrics(
        initial_equity=100_000,
        final_equity=100_000 * (1 + return_pct),
        net_profit=100_000 * return_pct,
        return_pct=return_pct,
        trade_count=12,
        winning_trades=7,
        losing_trades=5,
        win_rate=7 / 12,
        gross_profit=6_000,
        gross_loss=3_000,
        profit_factor=2.0,
        expectancy=250,
        max_drawdown=-0.05,
        annualized_return=0.12,
        annualized_volatility=0.10,
        sharpe_ratio=1.2,
        sortino_ratio=1.4,
        calmar_ratio=2.4,
        kill_switch_events=0,
    )


def _ranked_item(*, safety_passes: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_id="candidate-a",
        name="Candidate A",
        score=0.91,
        metrics=_metrics(),
        warnings=[],
        eligible=False,
        gates={
            "trade_count": safety_passes,
            "annualized_return": False,
            "sharpe_ratio": True,
            "profit_factor": True,
            "max_drawdown": True,
            "excess_return": False,
            "kill_switch_safety": True,
            "statistical_observation_count": True,
            "statistical_trade_count": True,
            "statistical_adjusted_p_value": False,
            "statistical_probabilistic_sharpe_ratio": False,
            "statistical_deflated_sharpe_probability": False,
            "statistical_bootstrap_lower_bound": False,
            "statistical_block_bootstrap_lower_bound": False,
            "statistical_hac_mean_confidence": False,
            "statistical_time_series_bootstrap_authority": True,
        },
    )


def _bars(count: int = 100) -> list[PriceBar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=10_000,
        )
        for index in range(count)
    ]


def _request() -> WalkForwardMultiStrategyRequest:
    candidate = MultiStrategyCandidate(
        strategy_id="candidate-a",
        name="Candidate A",
        strategy="sma_crossover",
        fast_window=2,
        slow_window=3,
    )
    criteria = WalkForwardStabilityCriteria(
        train_bars=20,
        test_bars=20,
        step_bars=20,
        min_windows=4,
        min_window_trades=0,
        min_train_eligible_window_rate=0.0,
        min_eligible_selection_rate=0.0,
        max_abstention_rate=1.0,
        min_profitable_window_rate=0.0,
        min_median_sharpe_ratio=-10.0,
        min_median_profit_factor=0.0,
        max_drawdown_floor=-1.0,
    )
    return WalkForwardMultiStrategyRequest(
        symbols=["AAPL"],
        initial_equity=100_000,
        bars={"AAPL": _bars()},
        candidates=[candidate],
        fee_bps=0,
        slippage_bps=0,
        walk_forward_criteria=criteria,
    )


def _test_result() -> BacktestRunResult:
    return BacktestRunResult(
        strategy="sma_crossover",
        symbols=["AAPL"],
        metrics=_metrics(),
        trades=[],
        equity_curve=[],
    )


def test_inner_selection_admits_safe_candidate_without_promoting_train_stats():
    item = _ranked_item(safety_passes=True)
    selection = SimpleNamespace(ranked_results=[item], best_eligible=None)

    selected, gates = v4._select_inner_training_candidate(selection)

    assert selected is item
    assert all(gates.values())
    assert item.eligible is False
    assert item.gates["statistical_adjusted_p_value"] is False
    assert item.gates["annualized_return"] is False
    assert item.gates["excess_return"] is False


def test_inner_selection_rejects_candidate_when_hard_safety_gate_fails():
    item = _ranked_item(safety_passes=False)
    selection = SimpleNamespace(ranked_results=[item], best_eligible=None)

    selected, gates = v4._select_inner_training_candidate(selection)

    assert selected is None
    assert gates == {}


def test_v4_no_safe_candidate_is_true_no_trade_and_never_executes_test(monkeypatch):
    request = _request()
    failed = _ranked_item(safety_passes=False)
    monkeypatch.setattr(
        v4.legacy,
        "run_multi_strategy_backtest",
        lambda train_request: SimpleNamespace(ranked_results=[failed]),
    )
    monkeypatch.setattr(
        v4,
        "run_backtest_with_risk",
        lambda test_request: pytest.fail(
            "unsafe inner candidate must not execute the untouched future test slice"
        ),
    )

    result = v4.run_nested_walk_forward_stability_v4(request)

    assert result.evaluated_windows == 4
    assert result.trade_windows == 0
    assert result.no_trade_windows == 4
    assert result.abstention_rate == 1.0
    assert result.capital_deployed_rate == 0.0
    assert all(window.decision == "NO_TRADE" for window in result.windows)
    assert all(window.metrics.trade_count == 0 for window in result.windows)


def test_v4_safe_candidate_reaches_outer_oos_even_when_train_promotion_stats_fail(
    monkeypatch,
):
    request = _request()
    safe = _ranked_item(safety_passes=True)
    execution_calls = []
    monkeypatch.setattr(
        v4.legacy,
        "run_multi_strategy_backtest",
        lambda train_request: SimpleNamespace(
            ranked_results=[safe],
            best_eligible=None,
        ),
    )

    def _execute(test_request):
        execution_calls.append(test_request)
        return _test_result()

    monkeypatch.setattr(v4, "run_backtest_with_risk", _execute)

    result = v4.run_nested_walk_forward_stability_v4(request)

    assert len(execution_calls) == 4
    assert result.trade_windows == 4
    assert result.no_trade_windows == 0
    assert result.train_eligible_window_rate == 1.0
    assert result.latest_selected_strategy_id == "candidate-a"
    assert result.latest_selection_eligible is True
    assert result.passed is True
    assert all(window.decision == "TRADE" for window in result.windows)
    assert all(
        any("promotion-grade train-slice gates" in warning for warning in window.warnings)
        for window in result.windows
    )


def test_adapter_versions_profile_without_changing_downstream_authority():
    sentinel = object()
    runner = SimpleNamespace(
        VALIDATION_PROFILE="nested_walk_forward_v3",
        run_walk_forward_multi_strategy_backtest=sentinel,
    )

    evidence = v4.apply_nested_validation_v4(runner)

    assert runner.VALIDATION_PROFILE == "nested_walk_forward_v4"
    assert runner.run_walk_forward_multi_strategy_backtest is v4.run_walk_forward_multi_strategy_backtest_v4
    assert runner.INNER_SELECTION_POLICY == "safety_data_sufficiency_ranked_v1"
    assert evidence["outer_oos_gates_changed"] is False
    assert evidence["full_statistical_authority_changed"] is False
    assert evidence["robustness_authority_changed"] is False
    assert evidence["sealed_holdout_authority_changed"] is False
