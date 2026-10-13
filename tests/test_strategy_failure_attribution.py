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


def test_jfin_research_failure_diagnostics_preserve_gates_and_sealed_holdout():
    report = {"data": {"items": [{
        "symbol": "JFIN", "status": "no_eligible_strategy",
        "selected_strategy_id": None,
        "selection": {
            "best_overall": {
                "strategy_id": "sma-crossover-balanced-v1",
                "strategy": "sma_crossover",
                "disqualification_reasons": [
                    "nested_outer_oos: walk_forward_profitable_window_rate gate failed"
                ],
                "effective_parameters": {
                    "fee_bps": 10, "slippage_bps": 5, "market_impact_bps": 0,
                },
            },
            "ranked_results": [],
            "walk_forward_criteria": {"min_profitable_window_rate": 0.6},
            "nested_walk_forward": {
                "profitable_window_rate": 0.333333,
                "median_sharpe_ratio": 0.308988,
                "median_profit_factor": 1.071975,
                "evaluated_windows": 6,
                "gates": {"profitable_window_rate": False},
            },
        },
    }]}}
    result = build_failure_attribution(report)
    row = result["symbol_diagnostics"][0]
    assert row["symbol"] == "JFIN"
    assert row["best_candidate_family"] == "sma_crossover"
    assert row["nested_oos"]["profitable_window_rate"] == 0.333333
    assert row["registered_walk_forward_criteria"]["min_profitable_window_rate"] == 0.6
    assert row["nested_failed_gates"] == ["profitable_window_rate"]
    assert row["assumed_execution_cost_bps"] == {
        "fee_bps": 10, "slippage_bps": 5, "market_impact_bps": 0
    }
    assert row["trade_authorized"] is False
    assert row["sealed_holdout_opened"] is False
    assert result["promotion_allowed"] is False


def test_no_best_candidate_remains_ineligible_without_invented_metrics():
    result = build_failure_attribution({"data": {"items": [
        {"symbol": "AAA", "selection": {"ranked_results": []}}
    ]}})
    row = result["symbol_diagnostics"][0]
    assert row["best_candidate_id"] is None
    assert row["nested_oos"]["median_profit_factor"] is None
    assert row["trade_authorized"] is False
