from app.research_strategy_expansion_policy import (
    EXPLORATORY_BUCKET,
    apply_research_strategy_expansion_policy,
    expanded_balanced_candidates,
)


def test_expanded_suite_adds_parameter_diversity_without_changing_families():
    candidates = expanded_balanced_candidates()
    assert len(candidates) == 12
    assert len({candidate.strategy_id for candidate in candidates}) == 12
    assert {candidate.strategy for candidate in candidates} == {
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    }
    for family in {candidate.strategy for candidate in candidates}:
        assert sum(candidate.strategy == family for candidate in candidates) == 3


def test_policy_adds_exploratory_bucket_and_preserves_fail_closed_authority():
    policy = apply_research_strategy_expansion_policy()
    assert policy["candidate_count"] == 12
    assert EXPLORATORY_BUCKET in policy["supported_buckets"]
    assert policy["selection_thresholds_relaxed"] is False
    assert policy["nested_oos_required"] is True
    assert policy["sealed_holdout_required"] is True
    assert policy["production_authority_granted"] is False
    assert policy["risk_execution_authority_granted"] is False
    assert policy["broker_order_authorized"] is False

    from app import strategy_bucket_candidate_policy as bucket_policy

    assert EXPLORATORY_BUCKET in bucket_policy.SUPPORTED_BUCKETS
    assert len(bucket_policy.BUCKET_STRATEGY_IDS[EXPLORATORY_BUCKET]) == 12
    assert len(bucket_policy.BUCKET_STRATEGY_IDS["value_rebound"]) == 6
    assert len(bucket_policy.BUCKET_STRATEGY_IDS["news_momentum"]) == 6
