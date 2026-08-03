from __future__ import annotations

from typing import Any, Dict

from app.database_client import DatabaseAgentClient


BACKTEST_TARGET_STATE = "ROBUSTNESS_PASSED"
BACKTEST_OWNED_TRANSITIONS = (
    ("GENERATED", "VALIDATED", "evidence_contract_validated"),
    ("VALIDATED", "OOS_PASSED", "nested_walk_forward_passed"),
    ("OOS_PASSED", "ROBUSTNESS_PASSED", "robustness_policy_passed"),
)
DOWNSTREAM_STATES = {
    "ROBUSTNESS_PASSED",
    "APPROVED_FOR_PAPER",
    "PAPER_OBSERVING",
}
TERMINAL_STATES = {"REJECTED", "FAILED", "EXPIRED", "REVOKED"}


class PromotionLifecycleError(RuntimeError):
    pass


def _promotion_data(document: Dict[str, Any]) -> Dict[str, Any]:
    data = document.get("data")
    if not isinstance(data, dict):
        raise PromotionLifecycleError("promotion response is missing data")
    state = data.get("state")
    version = data.get("version")
    promotion_id = data.get("promotion_id")
    run_id = data.get("run_id")
    if not isinstance(state, str) or not state:
        raise PromotionLifecycleError("promotion response is missing state")
    if not isinstance(version, int) or version < 1:
        raise PromotionLifecycleError("promotion response has an invalid version")
    if not isinstance(promotion_id, str) or not promotion_id:
        raise PromotionLifecycleError("promotion response is missing promotion_id")
    if not isinstance(run_id, str) or not run_id:
        raise PromotionLifecycleError("promotion response is missing run_id")
    return data


def _transition_reason(next_state: str) -> str:
    reasons = {
        "VALIDATED": "Stored immutable Backtest evidence passed the strict identity and schema contract.",
        "OOS_PASSED": "Nested train-selection and untouched future test windows passed all statistical gates.",
        "ROBUSTNESS_PASSED": "Parameter, cost, spread, slippage, liquidity, and drawdown stress gates passed.",
    }
    return reasons[next_state]


def create_and_advance_backtest_promotion(
    client: DatabaseAgentClient,
    *,
    account_id: str,
    run_id: str,
    skill_id: str,
    strategy_id: str,
    symbol: str,
    timeframe: str,
    dataset_fingerprint: str,
    engine_version: str,
    validation_profile: str,
    correlation_id: str,
    evidence_version: int = 1,
) -> Dict[str, Any]:
    """Create and attest a promotion through ROBUSTNESS_PASSED.

    The function can resume an idempotent retry from any Backtest-owned state.
    It never calls an approval or paper-observation endpoint and treats terminal
    states as blocking failures.
    """

    created = client.create_backtest_promotion(
        {
            "account_id": account_id,
            "run_id": run_id,
            "skill_id": skill_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "dataset_fingerprint": dataset_fingerprint,
            "engine_version": engine_version,
            "validation_profile": validation_profile,
            "evidence_version": evidence_version,
            "reason_code": "backtest_evidence_published",
            "reason": "Immutable Backtest evidence was stored before lifecycle attestation.",
            "correlation_id": correlation_id,
            "metadata": {
                "source_agent": "backtest-agent",
                "immutable_evidence_snapshot": True,
                "maximum_owned_state": BACKTEST_TARGET_STATE,
            },
        },
        correlation_id=correlation_id,
    )
    current = _promotion_data(created)
    if current["run_id"] != run_id:
        raise PromotionLifecycleError("promotion run_id does not match published evidence")

    while current["state"] not in DOWNSTREAM_STATES:
        state = current["state"]
        if state in TERMINAL_STATES:
            raise PromotionLifecycleError(
                f"promotion is blocked in terminal state {state}"
            )
        transition = next(
            (item for item in BACKTEST_OWNED_TRANSITIONS if item[0] == state),
            None,
        )
        if transition is None:
            raise PromotionLifecycleError(
                f"Backtest_Agent is not authorized to advance state {state}"
            )
        expected_state, next_state, reason_code = transition
        document = client.transition_backtest_promotion(
            current["promotion_id"],
            {
                "expected_state": expected_state,
                "expected_version": current["version"],
                "next_state": next_state,
                "reason_code": reason_code,
                "reason": _transition_reason(next_state),
                "evidence_run_id": run_id,
                "correlation_id": correlation_id,
                "evidence_version": evidence_version,
                "metadata": {
                    "attestation_source": "backtest-agent",
                    "immutable_evidence_snapshot": True,
                },
            },
            correlation_id=correlation_id,
        )
        next_record = _promotion_data(document)
        if next_record["promotion_id"] != current["promotion_id"]:
            raise PromotionLifecycleError("promotion identity changed during transition")
        if next_record["run_id"] != run_id:
            raise PromotionLifecycleError("promotion evidence changed during transition")
        current = next_record

    return current
