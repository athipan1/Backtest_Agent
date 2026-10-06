from types import SimpleNamespace

from app.parameter_stability import parameter_stability_diagnostics
from app.research_candidate_profiles import strategy_research_v7_candidates


def _result(strategy_id, ret, sharpe, pf):
    return SimpleNamespace(
        strategy_id=strategy_id,
        eligible=False,
        metrics=SimpleNamespace(
            return_pct=ret,
            sharpe_ratio=sharpe,
            profit_factor=pf,
            max_drawdown=-0.08,
            trade_count=40,
        ),
    )


def test_parameter_stability_is_observational_only_and_detects_plateau():
    candidates = strategy_research_v7_candidates()
    results = [
        _result("sma-crossover-balanced-v1", 0.03, 0.5, 1.1),
        _result("sma-crossover-15-45-risk-v7", 0.05, 0.8, 1.3),
        _result("sma-crossover-20-60-risk-v7", 0.04, 0.7, 1.2),
        _result("mean-reversion-balanced-v1", -0.01, -0.2, 0.9),
        _result("mean-reversion-5-30-risk-v7", 0.01, 0.1, 1.02),
        _result("mean-reversion-8-35-risk-v7", -0.02, -0.3, 0.8),
    ]

    evidence = parameter_stability_diagnostics(
        candidates=candidates,
        ranked_results=results,
    )

    assert evidence["families"]["sma_crossover"]["plateau_observed"] is True
    assert evidence["families"]["mean_reversion"]["plateau_observed"] is False
    assert evidence["diagnostic_only"] is True
    assert evidence["thresholds_changed"] is False
    assert evidence["used_for_selection"] is False
    assert evidence["promotion_allowed"] is False
    assert evidence["execution_allowed"] is False
    assert evidence["sealed_holdout_opened"] is False
