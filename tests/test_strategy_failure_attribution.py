from scripts.strategy_failure_attribution import build_failure_attribution


def test_failure_attribution_is_diagnostic_only():
    report = {
        "data": {
            "items": [
                {
                    "symbol": "AAA",
                    "selected_strategy_id": "sma-crossover-balanced-v1",
                    "selection": {
                        "ranked_results": [
                            {
                                "strategy": "sma_crossover",
                                "strategy_id": "sma-crossover-balanced-v1",
                                "eligible": False,
                                "nested_walk_forward": {
                                    "gates": {
                                        "median_sharpe_ratio": False,
                                        "profitable_window_rate": True,
                                    },
                                    "profitable_window_rate": 0.66,
                                    "median_sharpe_ratio": 0.4,
                                    "median_profit_factor": 1.2,
                                    "worst_max_drawdown": -0.05,
                                    "evaluated_windows": 6,
                                },
                            }
                        ]
                    },
                    "statistical_evidence": {
                        "passed": False,
                        "gates": {
                            "adjusted_p_value": False,
                            "trade_count": True,
                        },
                        "adjusted_p_value": 0.8,
                        "trade_count": 100,
                    },
                }
            ]
        }
    }

    result = build_failure_attribution(report)

    assert result["failure_gate_counts"] == {"median_sharpe_ratio": 1}
    assert result["statistical_failures"][0]["failed_gates"] == ["adjusted_p_value"]
    assert result["diagnostic_only"] is True
    assert result["thresholds_changed"] is False
    assert result["used_for_selection"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False
