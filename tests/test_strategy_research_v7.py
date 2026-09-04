import pytest
from pydantic import ValidationError

from app.pre_holdout_research import _cost_stress_multipliers
from app.research_candidate_profiles import (
    strategy_research_v5_candidates,
    strategy_research_v7_candidates,
)
from app.research_overfit import MAX_RESEARCH_PBO, PBOCriteria


def test_strategy_research_v7_is_sparse_and_preregistered():
    candidates = strategy_research_v7_candidates()
    ids = [candidate.strategy_id for candidate in candidates]

    assert ids[:4] == [
        candidate.strategy_id for candidate in strategy_research_v5_candidates()[:4]
    ]
    assert ids[4:] == [
        "sma-crossover-15-45-risk-v7",
        "sma-crossover-30-90-risk-v7",
        "trend-following-15-60-risk-v7",
        "trend-following-40-160-risk-v7",
        "breakout-15-60-risk-v7",
        "mean-reversion-5-30-risk-v7",
    ]
    assert len(candidates) == 10
    assert len(set(ids)) == 10
    assert all(candidate.fast_window < candidate.slow_window for candidate in candidates)
    hypotheses = candidates[4:]
    assert all((candidate.max_position_pct or 1.0) <= 0.05 for candidate in hypotheses)
    assert {candidate.strategy for candidate in hypotheses} == {
        "sma_crossover",
        "trend_following",
        "breakout",
        "mean_reversion",
    }


def test_v7_pbo_limit_cannot_be_relaxed_above_point_20():
    assert MAX_RESEARCH_PBO == 0.20
    assert PBOCriteria().max_probability_of_backtest_overfit == 0.20
    with pytest.raises(ValidationError):
        PBOCriteria(max_probability_of_backtest_overfit=0.200001)


def test_v7_cost_stress_requires_two_x_scenario(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1.0,1.5,2.0")
    assert _cost_stress_multipliers() == (1.0, 1.5, 2.0)

    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1.0,1.5")
    with pytest.raises(RuntimeError, match="mandatory 2.0x"):
        _cost_stress_multipliers()
