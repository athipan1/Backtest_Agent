from __future__ import annotations

from copy import deepcopy

import pytest

from app.promotion_lifecycle import (
    BACKTEST_OWNED_TRANSITIONS,
    PromotionLifecycleError,
    create_and_advance_backtest_promotion,
)


class FakePromotionClient:
    def __init__(self, *, initial_state: str = "GENERATED", run_id: str = "run-1"):
        self.record = {
            "promotion_id": "promotion-1",
            "run_id": run_id,
            "state": initial_state,
            "version": {
                "GENERATED": 1,
                "VALIDATED": 2,
                "OOS_PASSED": 3,
                "ROBUSTNESS_PASSED": 4,
                "APPROVED_FOR_PAPER": 5,
                "PAPER_OBSERVING": 6,
                "FAILED": 2,
                "REVOKED": 6,
            }.get(initial_state, 1),
        }
        self.created_payloads: list[dict] = []
        self.transitions: list[dict] = []

    def create_backtest_promotion(self, payload, *, correlation_id=None):
        self.created_payloads.append(deepcopy(payload))
        return {"status": "success", "data": deepcopy(self.record)}

    def transition_backtest_promotion(
        self,
        promotion_id,
        payload,
        *,
        correlation_id=None,
    ):
        assert promotion_id == self.record["promotion_id"]
        assert payload["expected_state"] == self.record["state"]
        assert payload["expected_version"] == self.record["version"]
        assert payload["evidence_run_id"] == self.record["run_id"]
        self.transitions.append(deepcopy(payload))
        self.record = {
            **self.record,
            "state": payload["next_state"],
            "version": self.record["version"] + 1,
        }
        return {"status": "success", "data": deepcopy(self.record)}


def _advance(client: FakePromotionClient):
    return create_and_advance_backtest_promotion(
        client,
        account_id="account-1",
        run_id="run-1",
        skill_id="skill-1",
        strategy_id="strategy-1",
        symbol="AAPL",
        timeframe="1d",
        dataset_fingerprint="a" * 64,
        engine_version="backtest-agent-0.7.0",
        validation_profile="nested_walk_forward_v2",
        correlation_id="corr-1",
    )


def test_backtest_advances_only_owned_states_in_order():
    client = FakePromotionClient()
    result = _advance(client)

    assert result["state"] == "ROBUSTNESS_PASSED"
    assert result["version"] == 4
    assert [item["next_state"] for item in client.transitions] == [
        "VALIDATED",
        "OOS_PASSED",
        "ROBUSTNESS_PASSED",
    ]
    assert client.created_payloads[0]["metadata"]["maximum_owned_state"] == (
        "ROBUSTNESS_PASSED"
    )
    assert all(item.get("approver") is None for item in client.transitions)


def test_retry_resumes_from_validated_without_duplicate_earlier_transition():
    client = FakePromotionClient(initial_state="VALIDATED")
    result = _advance(client)

    assert result["state"] == "ROBUSTNESS_PASSED"
    assert [item["next_state"] for item in client.transitions] == [
        "OOS_PASSED",
        "ROBUSTNESS_PASSED",
    ]


@pytest.mark.parametrize("state", ["ROBUSTNESS_PASSED", "APPROVED_FOR_PAPER", "PAPER_OBSERVING"])
def test_downstream_state_is_returned_without_backtest_mutation(state):
    client = FakePromotionClient(initial_state=state)
    result = _advance(client)

    assert result["state"] == state
    assert client.transitions == []


@pytest.mark.parametrize("state", ["FAILED", "REVOKED"])
def test_terminal_state_fails_closed(state):
    client = FakePromotionClient(initial_state=state)
    with pytest.raises(PromotionLifecycleError, match="terminal state"):
        _advance(client)


def test_mismatched_run_id_and_malformed_response_are_blocked():
    client = FakePromotionClient(run_id="different-run")
    with pytest.raises(PromotionLifecycleError, match="run_id"):
        _advance(client)

    client = FakePromotionClient()
    client.record.pop("version")
    with pytest.raises(PromotionLifecycleError, match="invalid version"):
        _advance(client)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda document: document.pop("data"), "missing data"),
        (lambda document: document["data"].pop("state"), "missing state"),
        (
            lambda document: document["data"].pop("promotion_id"),
            "missing promotion_id",
        ),
        (lambda document: document["data"].pop("run_id"), "missing run_id"),
    ],
)
def test_create_response_requires_complete_promotion_identity(mutator, message):
    client = FakePromotionClient()
    original = client.create_backtest_promotion

    def malformed(*args, **kwargs):
        document = original(*args, **kwargs)
        mutator(document)
        return document

    client.create_backtest_promotion = malformed
    with pytest.raises(PromotionLifecycleError, match=message):
        _advance(client)


def test_unknown_nonterminal_state_is_not_authorized():
    client = FakePromotionClient(initial_state="MANUAL_REVIEW")
    with pytest.raises(PromotionLifecycleError, match="not authorized"):
        _advance(client)


def test_transition_cannot_change_promotion_or_evidence_identity():
    client = FakePromotionClient()
    original = client.transition_backtest_promotion
    call_count = 0

    def changed_promotion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        document = original(*args, **kwargs)
        if call_count == 1:
            document["data"]["promotion_id"] = "promotion-different"
        return document

    client.transition_backtest_promotion = changed_promotion
    with pytest.raises(PromotionLifecycleError, match="identity changed"):
        _advance(client)

    client = FakePromotionClient()
    original = client.transition_backtest_promotion

    def changed_evidence(*args, **kwargs):
        document = original(*args, **kwargs)
        document["data"]["run_id"] = "run-different"
        return document

    client.transition_backtest_promotion = changed_evidence
    with pytest.raises(PromotionLifecycleError, match="evidence changed"):
        _advance(client)


def test_backtest_owned_transition_table_cannot_approve_paper():
    next_states = {next_state for _, next_state, _ in BACKTEST_OWNED_TRANSITIONS}
    assert next_states == {"VALIDATED", "OOS_PASSED", "ROBUSTNESS_PASSED"}
    assert "APPROVED_FOR_PAPER" not in next_states
    assert "PAPER_OBSERVING" not in next_states
