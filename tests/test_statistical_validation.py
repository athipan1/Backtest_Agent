from datetime import datetime, timedelta, timezone
import math

import pytest

from app.models import BacktestMetrics, BacktestRunResult, EquityPoint
from app.statistical_validation import (
    StatisticalValidationCriteria,
    equity_returns,
    run_statistical_validation,
)


def _metrics(*, trade_count=20, return_pct=0.20):
    return BacktestMetrics(
        initial_equity=100000,
        final_equity=100000 * (1 + return_pct),
        net_profit=100000 * return_pct,
        return_pct=return_pct,
        trade_count=trade_count,
        winning_trades=max(trade_count - 5, 0),
        losing_trades=min(5, trade_count),
        win_rate=0.75 if trade_count else 0,
        gross_profit=25000,
        gross_loss=-5000,
        profit_factor=5.0,
        expectancy=1000,
        max_drawdown=-0.05,
        annualized_return=0.25,
        annualized_volatility=0.12,
        sharpe_ratio=2.0,
        sortino_ratio=2.5,
        calmar_ratio=5.0,
        benchmark_return_pct=0.08,
        excess_return_pct=0.12,
    )


def _result(returns, *, trade_count=20):
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    equity = 100000.0
    curve = [EquityPoint(timestamp=timestamp, equity=equity)]
    for index, value in enumerate(returns, start=1):
        equity *= 1 + value
        curve.append(
            EquityPoint(
                timestamp=timestamp + timedelta(days=index),
                equity=equity,
            )
        )
    return BacktestRunResult(
        strategy="test",
        symbols=["AAPL"],
        metrics=_metrics(
            trade_count=trade_count,
            return_pct=equity / 100000 - 1,
        ),
        trades=[],
        equity_curve=curve,
    )


def test_equity_returns_are_derived_from_chronological_curve():
    result = _result([0.01, -0.005, 0.02])

    values = equity_returns(result)

    assert len(values) == 3
    assert values[0] == pytest.approx(0.01)
    assert values[1] == pytest.approx(-0.005)
    assert values[2] == pytest.approx(0.02)


def test_positive_repeatable_edge_passes_lenient_statistical_gates():
    returns = [0.001 + ((index % 5) - 2) * 0.00005 for index in range(100)]
    criteria = StatisticalValidationCriteria(
        min_observations=30,
        min_trades=10,
        max_adjusted_p_value=0.05,
        min_probabilistic_sharpe_ratio=0.90,
        min_deflated_sharpe_probability=0.80,
        min_bootstrap_annualized_return=0.0,
        bootstrap_simulations=300,
        bootstrap_seed=7,
    )

    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=4,
        periods_per_year=252,
        criteria=criteria,
    )

    assert evidence.status == "completed"
    assert evidence.passed is True
    assert all(evidence.gates.values())
    assert evidence.adjusted_p_value <= criteria.max_adjusted_p_value
    assert evidence.bootstrap_annualized_return_lower > 0
    assert evidence.probabilistic_sharpe_ratio >= 0.90
    assert evidence.deflated_sharpe_probability >= 0.80


def test_bonferroni_adjustment_penalizes_multiple_candidate_trials():
    returns = [0.0002 + ((index % 7) - 3) * 0.001 for index in range(80)]
    criteria = StatisticalValidationCriteria(
        min_observations=30,
        min_trades=1,
        max_adjusted_p_value=1.0,
        min_probabilistic_sharpe_ratio=0.0,
        min_deflated_sharpe_probability=0.0,
        min_bootstrap_annualized_return=-1.0,
        bootstrap_simulations=100,
    )

    single = run_statistical_validation(
        _result(returns),
        candidate_count=1,
        periods_per_year=252,
        criteria=criteria,
    )
    many = run_statistical_validation(
        _result(returns),
        candidate_count=10,
        periods_per_year=252,
        criteria=criteria,
    )

    assert single.raw_one_sided_p_value == many.raw_one_sided_p_value
    assert many.adjusted_p_value >= single.adjusted_p_value
    assert many.expected_max_sharpe_ratio >= single.expected_max_sharpe_ratio
    assert many.deflated_sharpe_probability <= single.deflated_sharpe_probability


def test_small_sample_is_blocked_even_when_total_return_is_positive():
    evidence = run_statistical_validation(
        _result([0.02] * 5, trade_count=2),
        candidate_count=4,
        periods_per_year=252,
        criteria=StatisticalValidationCriteria(bootstrap_simulations=100),
    )

    assert evidence.status == "insufficient_data"
    assert evidence.passed is False
    assert evidence.gates["observation_count"] is False
    assert evidence.gates["trade_count"] is False


def test_negative_edge_fails_significance_and_bootstrap_gates():
    returns = [-0.001 + ((index % 5) - 2) * 0.0001 for index in range(100)]
    evidence = run_statistical_validation(
        _result(returns),
        candidate_count=4,
        periods_per_year=252,
        criteria=StatisticalValidationCriteria(
            min_trades=1,
            bootstrap_simulations=200,
        ),
    )

    assert evidence.status == "completed"
    assert evidence.passed is False
    assert evidence.gates["adjusted_p_value"] is False
    assert evidence.gates["bootstrap_lower_bound"] is False


def test_bootstrap_evidence_is_deterministic_for_same_seed():
    returns = [0.0005 + ((index % 9) - 4) * 0.0002 for index in range(80)]
    criteria = StatisticalValidationCriteria(
        min_trades=1,
        max_adjusted_p_value=1.0,
        min_probabilistic_sharpe_ratio=0.0,
        min_deflated_sharpe_probability=0.0,
        min_bootstrap_annualized_return=-1.0,
        bootstrap_simulations=200,
        bootstrap_seed=123,
    )

    first = run_statistical_validation(
        _result(returns),
        candidate_count=3,
        periods_per_year=252,
        criteria=criteria,
    )
    second = run_statistical_validation(
        _result(returns),
        candidate_count=3,
        periods_per_year=252,
        criteria=criteria,
    )

    assert first.model_dump() == second.model_dump()


def test_constant_positive_returns_remain_finite_and_json_serializable():
    evidence = run_statistical_validation(
        _result([0.001] * 60),
        candidate_count=4,
        periods_per_year=252,
        criteria=StatisticalValidationCriteria(
            min_trades=1,
            bootstrap_simulations=100,
        ),
    )

    assert evidence.periodic_sharpe_ratio is not None
    assert math.isfinite(evidence.periodic_sharpe_ratio)
    serialized = evidence.model_dump_json()
    assert "Infinity" not in serialized
    assert "NaN" not in serialized
