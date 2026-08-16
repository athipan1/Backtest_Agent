from __future__ import annotations

import pytest

from app.research_candidate_profiles import (
    BULL_RESEARCH_PROFILE_ID,
    bull_research_v1_candidates,
    research_profile,
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


def test_research_profile_dispatches_by_explicit_id_only():
    candidates = research_profile(BULL_RESEARCH_PROFILE_ID)

    assert len(candidates) == 6
    with pytest.raises(ValueError, match="Unknown research candidate profile"):
        research_profile("production")
