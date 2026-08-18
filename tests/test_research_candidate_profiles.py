from __future__ import annotations

import pytest

from app.research_candidate_profiles import (
    BULL_RESEARCH_PROFILE_ID,
    STRATEGY_RESEARCH_V5_PROFILE_ID,
    bull_research_v1_candidates,
    research_profile,
    strategy_research_v5_candidates,
)


def test_bull_research_profile_is_deterministic_and_research_only():
    candidates = bull_research_v1_candidates()

    assert [candidate.strategy_id for candidate in candidates] == [
        "sma-crossover-bull-fast-v1",
        "sma-crossover-balanced-v1",
        "trend-following-bull-fast-v1",
        "trend-following-balanced-v1",
        "breakout-bull-fast-v1",
        "breakout-balanced-v1",
    ]
    assert [candidate.strategy for candidate in candidates] == [
        "sma_crossover",
        "sma_crossover",
        "trend_following",
        "trend_following",
        "breakout",
        "breakout",
    ]
    assert all(candidate.fast_window < candidate.slow_window for candidate in candidates)
    assert all(candidate.strategy != "mean_reversion" for candidate in candidates)


def test_bull_research_profile_keeps_existing_balanced_baselines_for_comparison():
    ids = {candidate.strategy_id for candidate in bull_research_v1_candidates()}

    assert "sma-crossover-balanced-v1" in ids
    assert "trend-following-balanced-v1" in ids
    assert "breakout-balanced-v1" in ids


def test_strategy_research_v5_is_preregistered_and_keeps_four_controls():
    candidates = strategy_research_v5_candidates()
    ids = [candidate.strategy_id for candidate in candidates]

    assert ids == [
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "trend-following-10-50-risk-v5",
        "trend-following-20-100-risk-v5",
        "breakout-10-40-risk-v5",
        "breakout-20-55-risk-v5",
    ]
    assert len(set(ids)) == 8
    assert all(candidate.fast_window < candidate.slow_window for candidate in candidates)

    controls = candidates[:4]
    assert all(candidate.max_position_pct is None for candidate in controls)
    assert all(candidate.stop_loss_pct is None for candidate in controls)
    assert all(candidate.reward_risk_ratio is None for candidate in controls)

    hypotheses = candidates[4:]
    assert all(candidate.max_position_pct == 0.08 for candidate in hypotheses)
    assert [candidate.stop_loss_pct for candidate in hypotheses] == [
        0.035,
        0.04,
        0.035,
        0.04,
    ]
    assert [candidate.reward_risk_ratio for candidate in hypotheses] == [
        2.5,
        3.0,
        2.5,
        3.0,
    ]
    assert {candidate.strategy for candidate in hypotheses} == {
        "trend_following",
        "breakout",
    }


def test_research_profile_dispatches_by_explicit_id_only():
    legacy = research_profile(BULL_RESEARCH_PROFILE_ID)
    v5 = research_profile(STRATEGY_RESEARCH_V5_PROFILE_ID)

    assert len(legacy) == 6
    assert len(v5) == 8
    with pytest.raises(ValueError, match="Unknown research candidate profile"):
        research_profile("production")
