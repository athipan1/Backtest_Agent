from app.challenger_evidence import build_challenger_evidence


def _selection(*, sharpe: bool, profit_factor: bool = True, safety: bool = True):
    return {
        "best_overall": {
            "strategy_id": "sma-crossover-balanced-v1",
            "strategy": "sma_crossover",
            "rank": 1,
            "score": 0.72,
            "gates": {
                "candidate_oos_kill_switch_safety": safety,
                "candidate_oos_window_count": safety,
                "candidate_oos_worst_max_drawdown": safety,
                "candidate_oos_median_profit_factor": profit_factor,
                "candidate_oos_profitable_window_rate": True,
                "candidate_oos_median_sharpe_ratio": sharpe,
            },
            "candidate_oos": {
                "median_sharpe_ratio": 0.61,
                "median_profit_factor": 1.24,
                "profitable_window_rate": 0.67,
                "worst_max_drawdown": -0.08,
                "evaluated_windows": 6,
            },
            "disqualification_reasons": ["candidate_oos_median_sharpe_ratio"],
        }
    }


def test_single_sharpe_near_miss_exports_observation_only_evidence():
    result = build_challenger_evidence(_selection(sharpe=False))

    assert result["observation_candidate"] is True
    assert result["strategy_id"] == "sma-crossover-balanced-v1"
    assert result["failed_candidate_oos_gates"] == [
        "candidate_oos_median_sharpe_ratio"
    ]
    assert result["safety"]["production_eligible"] is False
    assert result["safety"]["risk_execution_authorized"] is False
    assert result["safety"]["broker_order_authorized"] is False
    assert result["safety"]["thresholds_relaxed"] is False


def test_multiple_quality_failures_are_not_observation_candidate():
    result = build_challenger_evidence(
        _selection(sharpe=False, profit_factor=False)
    )
    assert result["observation_candidate"] is False


def test_safety_failure_is_never_observation_candidate():
    result = build_challenger_evidence(_selection(sharpe=False, safety=False))
    assert result["observation_candidate"] is False
    assert result["safety"]["safety_gates_passed"] is False
