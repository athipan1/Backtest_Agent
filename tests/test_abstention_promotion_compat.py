from app import hourly_promotion_runner as hourly


def test_legacy_walk_forward_evidence_derives_abstention_safely():
    derived = hourly._abstention_policy_evidence(
        {
            "train_eligible_window_rate": 0.75,
            "gates": {},
        },
        {
            "min_eligible_selection_rate": 0.50,
            "max_abstention_rate": 0.50,
        },
    )

    assert derived == {
        "eligible_selection_rate": 0.75,
        "abstention_rate": 0.25,
        "capital_deployed_rate": 0.75,
        "abstention_policy_passed": True,
        "eligible_selection_policy_passed": True,
    }


def test_explicit_v2_abstention_gates_override_derived_rates():
    derived = hourly._abstention_policy_evidence(
        {
            "eligible_selection_rate": 0.90,
            "abstention_rate": 0.10,
            "capital_deployed_rate": 0.90,
            "gates": {
                "eligible_selection_rate": False,
                "max_abstention_rate": False,
            },
        },
        {
            "min_eligible_selection_rate": 0.50,
            "max_abstention_rate": 0.50,
        },
    )

    assert derived["abstention_policy_passed"] is False
    assert derived["eligible_selection_policy_passed"] is False


def test_malformed_legacy_abstention_evidence_fails_closed():
    derived = hourly._abstention_policy_evidence(
        {
            "train_eligible_window_rate": "not-a-rate",
            "abstention_rate": 9,
            "capital_deployed_rate": True,
            "gates": {},
        },
        {
            "min_eligible_selection_rate": 0.50,
            "max_abstention_rate": 0.50,
        },
    )

    assert derived["eligible_selection_rate"] is None
    assert derived["abstention_rate"] is None
    assert derived["capital_deployed_rate"] is None
    assert derived["abstention_policy_passed"] is False
    assert derived["eligible_selection_policy_passed"] is False
