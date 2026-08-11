from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import hourly_promotion_runner as hourly
from app import multi_strategy_walk_forward as walk_forward
from app.models import BacktestMetrics, BacktestRunResult, PriceBar
from app.multi_strategy import MultiStrategyCandidate
from app.multi_strategy_walk_forward import (
    WalkForwardMultiStrategyRequest,
    WalkForwardStabilityCriteria,
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


def _metrics(*, return_pct: float = 0.05) -> BacktestMetrics:
    return BacktestMetrics(
        initial_equity=100_000,
        final_equity=100_000 * (1 + return_pct),
        net_profit=100_000 * return_pct,
        return_pct=return_pct,
        trade_count=5,
        winning_trades=4,
        losing_trades=1,
        win_rate=0.8,
        gross_profit=6_000,
        gross_loss=1_000,
        profit_factor=6.0,
        expectancy=1_000,
        max_drawdown=-0.05,
        annualized_return=0.12,
        annualized_volatility=0.10,
        sharpe_ratio=1.2,
        sortino_ratio=1.4,
        calmar_ratio=2.4,
    )


def _request(
    *,
    min_eligible_selection_rate: float = 0.0,
    max_abstention_rate: float = 1.0,
) -> WalkForwardMultiStrategyRequest:
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
        min_eligible_selection_rate=min_eligible_selection_rate,
        max_abstention_rate=max_abstention_rate,
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


def _selection(*, eligible: bool) -> SimpleNamespace:
    best = SimpleNamespace(
        strategy_id="candidate-a",
        name="Candidate A",
        score=0.91,
        metrics=_metrics(),
        warnings=[],
    )
    return SimpleNamespace(
        best_eligible=best if eligible else None,
        best_overall=best,
    )


def _test_result() -> BacktestRunResult:
    return BacktestRunResult(
        strategy="sma_crossover",
        symbols=["AAPL"],
        metrics=_metrics(),
        trades=[],
        equity_curve=[],
    )


def test_all_failed_candidates_produce_true_no_trade_without_exposure(monkeypatch):
    request = _request()
    monkeypatch.setattr(
        walk_forward,
        "run_multi_strategy_backtest",
        lambda train_request: _selection(eligible=False),
    )
    monkeypatch.setattr(
        walk_forward,
        "run_backtest_with_risk",
        lambda test_request: pytest.fail(
            "NO_TRADE window must not run the strategy execution simulator"
        ),
    )

    result = walk_forward.run_nested_walk_forward_stability(request)

    assert result.evaluated_windows == 4
    assert result.no_trade_windows == 4
    assert result.trade_windows == 0
    assert result.abstention_rate == 1.0
    assert result.eligible_selection_rate == 0.0
    assert result.capital_deployed_rate == 0.0
    assert result.selection_counts == {}
    assert result.latest_selected_strategy_id is None
    assert result.latest_selection_eligible is False

    for window in result.windows:
        assert window.decision == "NO_TRADE"
        assert window.selected_strategy_id is None
        assert window.selected_strategy_name is None
        assert window.train_selection_eligible is False
        assert window.train_selection_score is None
        assert window.train_metrics is None
        assert window.capital_deployed is False
        assert window.profitable is False
        assert window.metrics.trade_count == 0
        assert window.metrics.initial_equity == 100_000
        assert window.metrics.final_equity == 100_000
        assert window.metrics.return_pct == 0.0
        assert window.metrics.open_position_count == 0


def test_abstention_aggregate_counts_only_real_trade_windows(monkeypatch):
    request = _request()
    selections = iter(
        [
            _selection(eligible=True),
            _selection(eligible=False),
            _selection(eligible=True),
            _selection(eligible=False),
        ]
    )
    execution_calls = []
    monkeypatch.setattr(
        walk_forward,
        "run_multi_strategy_backtest",
        lambda train_request: next(selections),
    )

    def _execute(test_request):
        execution_calls.append(test_request)
        return _test_result()

    monkeypatch.setattr(walk_forward, "run_backtest_with_risk", _execute)

    result = walk_forward.run_nested_walk_forward_stability(request)

    assert len(execution_calls) == 2
    assert result.evaluated_windows == 4
    assert result.trade_windows == 2
    assert result.no_trade_windows == 2
    assert result.abstention_rate == 0.5
    assert result.eligible_selection_rate == 0.5
    assert result.train_eligible_window_rate == 0.5
    assert result.capital_deployed_rate == 0.5
    assert result.profitable_windows == 2
    assert result.profitable_window_rate == 0.5
    assert result.selection_counts == {"candidate-a": 2}
    assert [window.decision for window in result.windows] == [
        "TRADE",
        "NO_TRADE",
        "TRADE",
        "NO_TRADE",
    ]


def test_abstention_policy_blocks_nested_promotion_even_if_latest_is_eligible(
    monkeypatch,
):
    request = _request(
        min_eligible_selection_rate=0.75,
        max_abstention_rate=0.25,
    )
    selections = iter(
        [
            _selection(eligible=False),
            _selection(eligible=False),
            _selection(eligible=True),
            _selection(eligible=True),
        ]
    )
    monkeypatch.setattr(
        walk_forward,
        "run_multi_strategy_backtest",
        lambda train_request: next(selections),
    )
    monkeypatch.setattr(
        walk_forward,
        "run_backtest_with_risk",
        lambda test_request: _test_result(),
    )

    nested = walk_forward.run_nested_walk_forward_stability(request)

    assert nested.latest_selected_strategy_id == "candidate-a"
    assert nested.latest_selection_eligible is True
    assert nested.eligible_selection_rate == 0.5
    assert nested.abstention_rate == 0.5
    assert nested.gates["eligible_selection_rate"] is False
    assert nested.gates["max_abstention_rate"] is False
    assert nested.passed is False

    base_item = SimpleNamespace(
        strategy_id="candidate-a",
        name="Candidate A",
        strategy="sma_crossover",
        fast_window=2,
        slow_window=3,
        effective_parameters={"strategy": "sma_crossover"},
        eligible=True,
        gates={"diagnostic": True},
        score=0.5,
        score_components={"base": 0.5},
        metrics=_metrics(),
        warnings=[],
    )
    base_result = SimpleNamespace(
        symbol="AAPL",
        candidate_source="provided",
        selection_criteria={"diagnostic_only": True},
        ranked_results=[base_item],
        warnings=[],
    )
    monkeypatch.setattr(
        walk_forward,
        "run_multi_strategy_backtest",
        lambda full_request: base_result,
    )
    monkeypatch.setattr(
        walk_forward,
        "run_nested_walk_forward_stability",
        lambda nested_request: nested,
    )
    monkeypatch.setattr(
        walk_forward,
        "run_candidate_walk_forward_stability",
        lambda **kwargs: nested,
    )
    monkeypatch.setattr(
        walk_forward,
        "run_backtest_with_risk",
        lambda selected_request: pytest.fail(
            "failed abstention policy must not produce a selected strategy result"
        ),
    )

    selection = walk_forward.run_walk_forward_multi_strategy_backtest(request)

    assert selection.selection_status == "no_eligible_strategy"
    assert selection.best_eligible is None
    assert selection.selected_result is None
    assert selection.eligible_count == 0


def test_hourly_criteria_reads_new_abstention_environment(monkeypatch):
    monkeypatch.setenv("BACKTEST_WALK_FORWARD_MIN_ELIGIBLE_SELECTION_RATE", "0.80")
    monkeypatch.setenv("BACKTEST_WALK_FORWARD_MIN_TRAIN_ELIGIBLE_RATE", "0.10")
    monkeypatch.setenv("BACKTEST_WALK_FORWARD_MAX_ABSTENTION_RATE", "0.20")

    criteria = hourly._walk_forward_criteria()

    assert criteria["min_eligible_selection_rate"] == 0.80
    assert criteria["min_train_eligible_window_rate"] == 0.80
    assert criteria["max_abstention_rate"] == 0.20


def test_hourly_criteria_keeps_legacy_eligible_rate_as_fallback(monkeypatch):
    monkeypatch.delenv(
        "BACKTEST_WALK_FORWARD_MIN_ELIGIBLE_SELECTION_RATE",
        raising=False,
    )
    monkeypatch.setenv("BACKTEST_WALK_FORWARD_MIN_TRAIN_ELIGIBLE_RATE", "0.65")

    criteria = hourly._walk_forward_criteria()

    assert criteria["min_eligible_selection_rate"] == 0.65
    assert criteria["min_train_eligible_window_rate"] == 0.65


def test_run_identity_changes_when_abstention_policy_changes():
    base_metadata = {
        "evidence_version": 3,
        "walk_forward_criteria": {
            "min_eligible_selection_rate": 0.50,
            "max_abstention_rate": 0.50,
        },
        "statistical_schema_version": "statistical-validation.v2",
        "statistical_criteria": {"enabled": True},
        "robustness_validation": {"criteria": {"min_scenario_pass_rate": 0.8}},
        "final_holdout_criteria": {
            "enabled": True,
            "bars": 252,
            "min_trades": 10,
        },
        "sealed_holdout": {"dataset_fingerprint": "h" * 64},
    }
    strict_metadata = {
        **base_metadata,
        "walk_forward_criteria": {
            "min_eligible_selection_rate": 0.80,
            "max_abstention_rate": 0.20,
        },
    }

    common = {
        "symbol": "AAPL",
        "strategy_id": "candidate-a",
        "fingerprint": "a" * 64,
        "research_fingerprint": "r" * 64,
        "effective_parameters": {"strategy": "sma_crossover"},
        "timeframe": "1d",
    }
    base_run_id = hourly._run_id(
        **common,
        promotion_metadata=base_metadata,
    )
    strict_run_id = hourly._run_id(
        **common,
        promotion_metadata=strict_metadata,
    )

    assert base_run_id != strict_run_id
