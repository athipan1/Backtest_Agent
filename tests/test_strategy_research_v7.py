from app.research_candidate_profiles import (
    STRATEGY_RESEARCH_V7_PROFILE_ID,
    research_profile,
    strategy_research_v7_candidates,
)
from app.research_trial_registry import statistical_trial_count


def test_strategy_research_v7_is_sparse_preregistered_and_cumulative():
    candidates = strategy_research_v7_candidates()
    ids = [candidate.strategy_id for candidate in candidates]

    assert ids == [
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "sma-crossover-15-45-risk-v7",
        "sma-crossover-20-60-risk-v7",
        "mean-reversion-5-30-risk-v7",
        "mean-reversion-8-35-risk-v7",
    ]
    assert len(ids) == len(set(ids)) == 8
    assert research_profile(STRATEGY_RESEARCH_V7_PROFILE_ID) == candidates
    assert statistical_trial_count(STRATEGY_RESEARCH_V7_PROFILE_ID) == 18

    hypotheses = candidates[4:]
    assert {candidate.strategy for candidate in hypotheses} == {
        "sma_crossover",
        "mean_reversion",
    }
    assert all(candidate.fast_window < candidate.slow_window for candidate in hypotheses)
    assert all(candidate.max_position_pct <= 0.05 for candidate in hypotheses)


def test_strategy_research_v7_does_not_encode_a_regime_gate():
    candidates = strategy_research_v7_candidates()
    serialized = [candidate.model_dump(mode="json") for candidate in candidates]

    assert all("regime" not in key.lower() for row in serialized for key in row)
