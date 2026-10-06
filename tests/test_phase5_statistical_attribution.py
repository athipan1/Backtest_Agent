from app.phase5_statistical_attribution import phase5_statistical_failure_attribution


def test_phase5_attributes_failed_statistics_without_changing_authority():
    stability = {
        "families": {
            "sma_crossover": {"plateau_observed": True},
            "mean_reversion": {"plateau_observed": False},
        }
    }
    statistical = {
        "adjusted_p_value": 0.87,
        "probabilistic_sharpe_ratio": 0.93,
        "deflated_sharpe_ratio": 0.40,
        "bootstrap_lower_bound": -0.01,
        "block_bootstrap_lower_bound": -0.02,
        "hac_positive_probability": 0.94,
        "criteria": {
            "max_adjusted_p_value": 0.05,
            "min_probabilistic_sharpe_ratio": 0.95,
            "min_deflated_sharpe_ratio": 0.50,
            "min_bootstrap_lower_bound": 0.0,
            "min_block_bootstrap_lower_bound": 0.0,
            "min_hac_positive_probability": 0.95,
        },
    }

    output = phase5_statistical_failure_attribution(
        parameter_stability=stability,
        statistical_evidence=statistical,
        selected_strategy_id="sma-crossover-15-45-risk-v7",
    )

    assert output["stable_parameter_families"] == ["sma_crossover"]
    assert output["stable_family_observed"] is True
    assert output["statistical_evidence_present"] is True
    assert set(output["failed_checks"]) == {
        "adjusted_p_value",
        "probabilistic_sharpe_ratio",
        "deflated_sharpe_ratio",
        "bootstrap_lower_bound",
        "block_bootstrap_lower_bound",
        "hac_positive_probability",
    }
    assert output["diagnostic_only"] is True
    assert output["thresholds_changed"] is False
    assert output["used_for_selection"] is False
    assert output["promotion_allowed"] is False
    assert output["execution_allowed"] is False
    assert output["sealed_holdout_opened"] is False


def test_phase5_handles_nested_selection_rejection_without_statistical_evidence():
    output = phase5_statistical_failure_attribution(
        parameter_stability={"families": {"sma_crossover": {"plateau_observed": True}}},
        statistical_evidence=None,
        selected_strategy_id=None,
    )
    assert output["statistical_evidence_present"] is False
    assert output["failed_checks"] == []
    assert output["sealed_holdout_opened"] is False
