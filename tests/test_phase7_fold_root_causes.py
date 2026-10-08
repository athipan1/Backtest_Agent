from app.phase7_fold_root_causes import phase7_fold_root_causes


def test_phase7_diagnostic_flags_and_no_authority():
    evidence = {
        "candidate_rows": [{"nested_failed_gates": ["nested_oos_median_sharpe_ratio"]}],
        "nested_windows": [{
            "window": 1, "oos_trade_count": 0, "oos_sharpe_ratio": -0.5,
            "oos_profit_factor": 0.4, "oos_return_pct": -0.1,
            "train_selection_eligible": False, "capital_deployed": False,
        }],
    }
    result = phase7_fold_root_causes(evidence)
    assert result["candidate_count"] == 1
    assert result["fold_count"] == 1
    assert "zero_trades" in result["fold_rows"][0]["observed_flags"]
    assert result["nested_gate_failure_counts"]["nested_oos_median_sharpe_ratio"] == 1
    assert result["diagnostic_only"] is True
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_phase7_empty_payload_is_safe():
    result = phase7_fold_root_causes({})
    assert result["fold_rows"] == []
    assert result["trade_level_causality_verified"] is False
