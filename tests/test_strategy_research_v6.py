from app.research_candidate_profiles import strategy_research_v5_candidates, strategy_research_v6_candidates


def test_strategy_research_v6_is_sparse_and_preregistered():
    candidates = strategy_research_v6_candidates()
    ids = [candidate.strategy_id for candidate in candidates]
    assert ids[:4] == [candidate.strategy_id for candidate in strategy_research_v5_candidates()[:4]]
    assert ids[4:] == [
        "trend-following-30-120-risk-v6",
        "trend-following-50-150-risk-v6",
        "breakout-20-80-risk-v6",
        "breakout-30-120-risk-v6",
        "mean-reversion-3-15-risk-v6",
        "mean-reversion-10-40-risk-v6",
    ]
    assert len(candidates) == 10
    assert len(set(ids)) == 10
    assert all(candidate.fast_window < candidate.slow_window for candidate in candidates)
    hypotheses = candidates[4:]
    assert all((candidate.max_position_pct or 1.0) <= 0.06 for candidate in hypotheses)
    assert {candidate.strategy for candidate in hypotheses} == {
        "trend_following",
        "breakout",
        "mean_reversion",
    }
