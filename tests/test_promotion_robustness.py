from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.promotion_robustness as promotion_robustness
from app.models import (
    BacktestMetrics,
    BacktestRobustnessResult,
    BacktestRunRequest,
    BacktestRunResult,
    MonteCarloResult,
    ParameterSensitivityResult,
    PriceBar,
    SensitivityScenarioResult,
)
from app.promotion_robustness import (
    PromotionRobustnessCriteria,
    run_promotion_robustness,
)


def _metrics(
    *,
    return_pct: float = 0.08,
    drawdown: float = -0.08,
    final_equity: float = 108000.0,
    kill_switch_events: int = 0,
) -> BacktestMetrics:
    return BacktestMetrics(
        initial_equity=100000.0,
        final_equity=final_equity,
        net_profit=final_equity - 100000.0,
        return_pct=return_pct,
        trade_count=20,
        winning_trades=12,
        losing_trades=8,
        win_rate=0.60,
        gross_profit=12000.0,
        gross_loss=-4000.0,
        profit_factor=3.0,
        expectancy=400.0,
        max_drawdown=drawdown,
        kill_switch_events=kill_switch_events,
    )


def _result(**kwargs) -> BacktestRunResult:
    return BacktestRunResult(
        strategy="sma_crossover",
        symbols=["AAPL"],
        metrics=_metrics(**kwargs),
        trades=[],
        equity_curve=[],
    )


def _request() -> BacktestRunRequest:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=100.0 + index,
            high=102.0 + index,
            low=99.0 + index,
            close=101.0 + index,
            volume=10000.0,
        )
        for index in range(5)
    ]
    return BacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=100000.0,
        bars={"AAPL": bars},
        fast_window=1,
        slow_window=2,
        fee_bps=5.0,
        slippage_bps=5.0,
        max_volume_participation_pct=1.0,
    )


def _core(*, monte_carlo_status: str = "completed") -> BacktestRobustnessResult:
    scenarios = [
        SensitivityScenarioResult(
            fast_window=fast,
            slow_window=slow,
            metrics=_metrics(return_pct=0.04 + fast / 1000),
        )
        for fast, slow in [(1, 3), (1, 4), (2, 3), (2, 4)]
    ]
    monte_carlo = (
        MonteCarloResult(
            status="completed",
            simulations=500,
            seed=42,
            source_trade_count=20,
            trades_per_simulation=20,
            median_final_equity=108000.0,
            p05_final_equity=92000.0,
            p95_final_equity=118000.0,
            probability_of_loss=0.20,
            median_max_drawdown=-0.10,
            p05_max_drawdown=-0.25,
        )
        if monte_carlo_status == "completed"
        else MonteCarloResult(
            status="insufficient_data",
            simulations=500,
            seed=42,
            source_trade_count=1,
            trades_per_simulation=1,
            reason="insufficient trades",
        )
    )
    return BacktestRobustnessResult(
        baseline=_result(),
        monte_carlo=monte_carlo,
        sensitivity=ParameterSensitivityResult(
            scenario_count=4,
            baseline_fast_window=1,
            baseline_slow_window=2,
            fast_delta=1,
            slow_delta=1,
            profitable_scenario_pct=1.0,
            median_return_pct=0.05,
            worst_return_pct=0.04,
            best_return_pct=0.06,
            baseline_rank_by_return=1,
            scenarios=scenarios,
        ),
    )


def test_all_required_robustness_gates_pass_and_assumptions_are_explicit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        promotion_robustness,
        "run_robustness_analysis",
        lambda request: _core(),
    )

    def fake_run(request, *, updates=None, policy=None):
        calls.append({"updates": updates, "policy": policy})
        return _result()

    monkeypatch.setattr(promotion_robustness, "_run_request", fake_run)
    evidence = run_promotion_robustness(_request())

    assert evidence.passed is True
    assert evidence.scenario_pass_rate == 1.0
    assert all(evidence.gates.values())
    assert [item.name for item in evidence.stress_scenarios] == [
        "fee_stress",
        "spread_stress",
        "slippage_stress",
        "liquidity_stress",
    ]
    assert calls[0]["updates"]["fee_bps"] == 10.0
    assert calls[1]["policy"].bid_ask_spread_bps == 5.0
    assert calls[2]["updates"]["slippage_bps"] == 10.0
    assert calls[3]["updates"]["max_volume_participation_pct"] == 0.25


def test_single_failed_stress_scenario_blocks_promotion(monkeypatch):
    monkeypatch.setattr(
        promotion_robustness,
        "run_robustness_analysis",
        lambda request: _core(),
    )
    results = iter(
        [
            _result(return_pct=-0.20),
            _result(),
            _result(),
            _result(),
        ]
    )
    monkeypatch.setattr(
        promotion_robustness,
        "_run_request",
        lambda *args, **kwargs: next(results),
    )

    evidence = run_promotion_robustness(_request())

    assert evidence.passed is False
    assert evidence.gates["fee_stress"] is False
    assert "fee_stress" in evidence.failure_reasons
    assert evidence.stress_scenarios[0].failure_reasons == [
        "stress_return_below_floor"
    ]


def test_insufficient_monte_carlo_blocks_drawdown_gate(monkeypatch):
    monkeypatch.setattr(
        promotion_robustness,
        "run_robustness_analysis",
        lambda request: _core(monte_carlo_status="insufficient_data"),
    )
    monkeypatch.setattr(
        promotion_robustness,
        "_run_request",
        lambda *args, **kwargs: _result(),
    )

    evidence = run_promotion_robustness(_request())

    assert evidence.passed is False
    assert evidence.gates["drawdown_stress"] is False
    assert "drawdown_stress" in evidence.failure_reasons


def test_catastrophic_loss_and_non_finite_environment_are_rejected(monkeypatch):
    catastrophic = _core()
    catastrophic.sensitivity.scenarios[0].metrics.return_pct = -0.60
    monkeypatch.setattr(
        promotion_robustness,
        "run_robustness_analysis",
        lambda request: catastrophic,
    )
    monkeypatch.setattr(
        promotion_robustness,
        "_run_request",
        lambda *args, **kwargs: _result(),
    )

    evidence = run_promotion_robustness(
        _request(),
        criteria=PromotionRobustnessCriteria(catastrophic_loss_floor=-0.50),
    )
    assert evidence.catastrophic_loss is True
    assert evidence.gates["no_catastrophic_loss"] is False

    monkeypatch.setenv(
        "BACKTEST_PROMOTION_MIN_ROBUSTNESS_PASS_RATE",
        "nan",
    )
    with pytest.raises(ValueError, match="must be finite"):
        promotion_robustness.promotion_robustness_criteria_from_env()
