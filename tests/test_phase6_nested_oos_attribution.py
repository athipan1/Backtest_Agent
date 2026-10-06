from types import SimpleNamespace

from app.phase6_nested_oos_attribution import phase6_nested_oos_failure_attribution


def test_phase6_attributes_nested_failures_and_stays_diagnostic_only():
    metrics = SimpleNamespace(return_pct=-0.01, sharpe_ratio=-0.2, profit_factor=0.8, max_drawdown=-0.04, trade_count=12)
    window = SimpleNamespace(window=1, decision="TRADE", selected_strategy_id="sma-a", train_selection_eligible=True, capital_deployed=True, profitable=False, metrics=metrics)
    walk = SimpleNamespace(profitable_window_rate=0.5, median_sharpe_ratio=0.4, median_profit_factor=1.1, worst_max_drawdown=-0.08, evaluated_windows=6)
    candidate = SimpleNamespace(
        strategy_id="sma-a", strategy="sma_crossover", eligible=False,
        gates={"nested_oos_profitable_window_rate": False, "nested_oos_median_sharpe_ratio": False, "latest_training_selection": False},
        walk_forward=walk, disqualification_reasons=["nested failure"],
    )
    selection = SimpleNamespace(ranked_results=[candidate], nested_walk_forward=SimpleNamespace(passed=False, windows=[window]))
    output = phase6_nested_oos_failure_attribution(
        selection=selection,
        parameter_stability={"families": {"sma_crossover": {"plateau_observed": True}}},
    )
    assert output["stable_parameter_families"] == ["sma_crossover"]
    assert output["nested_selection_passed"] is False
    assert output["nested_gate_failure_counts"] == {
        "nested_oos_profitable_window_rate": 1,
        "nested_oos_median_sharpe_ratio": 1,
    }
    assert output["latest_training_selection_failure_count"] == 1
    assert output["nested_windows"][0]["oos_return_pct"] == -0.01
    assert output["diagnostic_only"] is True
    assert output["thresholds_changed"] is False
    assert output["used_for_selection"] is False
    assert output["promotion_allowed"] is False
    assert output["execution_allowed"] is False
    assert output["sealed_holdout_opened"] is False


def test_phase6_handles_empty_selection_evidence():
    output = phase6_nested_oos_failure_attribution(
        selection=SimpleNamespace(ranked_results=[], nested_walk_forward=None),
        parameter_stability={"families": {}},
    )
    assert output["candidate_rows"] == []
    assert output["nested_windows"] == []
    assert output["sealed_holdout_opened"] is False
