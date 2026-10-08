from app.phase8_evidence_coverage import phase8_evidence_coverage


def test_phase8_does_not_claim_causality_from_aggregates():
    result = phase8_evidence_coverage({"fold_rows": [
        {"window": 1, "selected_strategy_id": "sma", "observed_flags": ["negative_oos_sharpe"]}
    ]})
    assert result["fold_count"] == 1
    assert result["fold_evidence"][0]["root_cause_confirmed"] is False
    assert result["fold_evidence"][0]["gross_pnl_available"] is False
    assert result["causal_conclusions_supported"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_phase8_empty_folds_fail_closed():
    result = phase8_evidence_coverage({})
    assert result["fold_count"] == 0
    assert result["missing_required_evidence"]
    assert result["thresholds_changed"] is False
