import pytest

from app.research_trial_registry import (
    build_trial_registry_snapshot,
    statistical_trial_count,
)


def test_trial_count_is_cumulative_across_research_profiles():
    assert statistical_trial_count("strategy_research_v5") == 8
    assert statistical_trial_count("strategy_research_v6") == 14
    assert statistical_trial_count("strategy_research_v7") == 20


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


def test_v7_snapshot_keeps_20_trial_burden_with_only_six_new_hypotheses():
    current_ids = [
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
        "sma-crossover-15-45-risk-v7",
        "sma-crossover-30-90-risk-v7",
        "trend-following-15-60-risk-v7",
        "trend-following-40-160-risk-v7",
        "breakout-15-60-risk-v7",
        "mean-reversion-5-30-risk-v7",
    ]
    snapshot = build_trial_registry_snapshot(
        profile_id="strategy_research_v7",
        candidate_ids=current_ids,
        dataset_fingerprint="v7-data",
    )

    assert snapshot["current_candidate_count"] == 10
    assert snapshot["statistical_trial_count"] == 20
    assert len(snapshot["control_ids"]) == 4
    assert len(snapshot["new_hypothesis_ids"]) == 6
    assert set(snapshot["new_hypothesis_ids"]) == set(current_ids[4:])


def test_registry_fails_closed_for_unregistered_strategy_identity():
    with pytest.raises(RuntimeError, match="unregistered candidate"):
        build_trial_registry_snapshot(
            profile_id="strategy_research_v7",
            candidate_ids=[
                "sma-crossover-15-45-risk-v7",
                "unregistered-grid-search-999",
            ],
            dataset_fingerprint="abc123",
        )
