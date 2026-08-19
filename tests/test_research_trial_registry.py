import pytest

from app.research_trial_registry import build_trial_registry_snapshot, statistical_trial_count


def test_v6_trial_count_is_cumulative_across_research_profiles():
    assert statistical_trial_count("strategy_research_v5") == 8
    assert statistical_trial_count("strategy_research_v6") == 14


def test_v6_snapshot_distinguishes_controls_from_new_hypotheses():
    current_ids = [
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "trend-following-30-120-risk-v6",
        "trend-following-50-150-risk-v6",
        "breakout-20-80-risk-v6",
        "breakout-30-120-risk-v6",
        "mean-reversion-3-15-risk-v6",
        "mean-reversion-10-40-risk-v6",
    ]
    snapshot = build_trial_registry_snapshot(
        profile_id="strategy_research_v6",
        candidate_ids=current_ids,
        dataset_fingerprint="abc123",
    )

    assert snapshot["current_candidate_count"] == 10
    assert snapshot["statistical_trial_count"] == 14
    assert len(snapshot["control_ids"]) == 4
    assert len(snapshot["new_hypothesis_ids"]) == 6
    assert snapshot["dataset_fingerprint"] == "abc123"


def test_registry_fails_closed_for_unregistered_strategy_identity():
    with pytest.raises(RuntimeError, match="unregistered candidate"):
        build_trial_registry_snapshot(
            profile_id="strategy_research_v6",
            candidate_ids=[
                "trend-following-30-120-risk-v6",
                "unregistered-grid-search-999",
            ],
            dataset_fingerprint="abc123",
        )
