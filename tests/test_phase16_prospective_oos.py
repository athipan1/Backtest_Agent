"""Prospective OOS audit never promotes Strategy v8 or opens sealed holdout."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.phase16_prospective_oos import (
    phase16_prospective_oos_evidence, prospective_oos_document_from_env,
)
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


RESEARCH_END = "2026-01-10T16:00:00Z"
SEALED_END = "2026-01-31T16:00:00Z"


def _data():
    locked_a, locked_b = "a" * 64, "b" * 64
    prereg = {
        "schema_version": "phase15-preregistered-v8-hypotheses.v1",
        "registered_at": "2026-01-07T09:00:00Z",
        "maximum_hypotheses": 2,
        "familywise_alpha": 0.05,
        "hypotheses": [
            {"hypothesis_id": "trend-bull", "strategy_id": "trend-v8",
             "regime": "BULL", "minimum_oos_folds": 3,
             "metric": "simulated_fold_net_pnl_after_costs",
             "expected_direction": "positive",
             "strategy_definition_sha256": locked_a},
            {"hypothesis_id": "breakout-bear", "strategy_id": "breakout-v8",
             "regime": "BEAR", "minimum_oos_folds": 3,
             "metric": "simulated_fold_net_pnl_after_costs",
             "expected_direction": "positive",
             "strategy_definition_sha256": locked_b},
        ],
    }
    registry = {
        "hypotheses": {"status": "digest_and_schema_valid",
                       "sha256": "c" * 64, "data": prereg},
    }
    packet = {
        "schema_version": "phase16-prospective-oos-evidence.v1",
        "hypothesis_registry_sha256": "c" * 64,
        "source_research_dataset_fingerprint": "original-selected-fingerprint",
        "source_reserved_holdout_id": "sealed-final-holdout-existing",
        "dataset_identity": {
            "source_id": "new-independent-forward-source",
            "dataset_sha256": "d" * 64,
            "data_feed": "paper-observation-research",
            "sampling_frequency": "1d",
            "first_collected_at": "2026-02-01T09:00:00Z",
        },
        "folds": [
            {"fold_id": f"forward-{day}",
             "start": f"2026-02-{day:02d}T09:30:00Z",
             "end": f"2026-02-{day:02d}T16:00:00Z"}
            for day in (2, 3, 4)
        ],
        "evaluations": [],
    }
    for day in (2, 3, 4):
        packet["evaluations"].append({
            "fold_id": f"forward-{day}", "hypothesis_id": "trend-bull",
            "strategy_id": "trend-v8", "regime": "BULL",
            "strategy_definition_sha256": locked_a,
            "decision": "TRADE",
            "trade_ledger_fingerprint": f"sha256:simulated-only-{day}",
            "reference_price_gross_pnl": 10.0,
            "modeled_slippage_cost": 1.0,
            "modeled_impact_cost": 1.0,
            "modeled_half_spread_cost": 1.0,
            "recorded_fees": 1.0, "simulated_net_pnl": 6.0,
        })
        packet["evaluations"].append({
            "fold_id": f"forward-{day}", "hypothesis_id": "breakout-bear",
            "strategy_id": "breakout-v8", "regime": "BEAR",
            "strategy_definition_sha256": locked_b,
            "decision": "NO_TRADE", "reference_price_gross_pnl": 0.0,
            "modeled_slippage_cost": 0.0,
            "modeled_impact_cost": 0.0,
            "modeled_half_spread_cost": 0.0,
            "recorded_fees": 0.0, "simulated_net_pnl": 0.0,
        })
    return registry, {"status": "digest_and_schema_valid",
                      "sha256": "e" * 64, "data": packet}


def _run(registry=None, packet=None, *,
         research_end=RESEARCH_END, sealed_end=SEALED_END, phase15=True):
    defaults = _data()
    return phase16_prospective_oos_evidence(
        registry if registry is not None else defaults[0],
        {"auxiliary_documents_contract_consistent": phase15},
        packet if packet is not None else defaults[1],
        research_end=research_end, reserved_holdout_end=sealed_end,
    )


def test_complete_forward_matrix_is_arithmetic_consistent_but_not_verified_profit():
    result = _run()
    assert result["prospective_packet_contract_consistent"] is True
    assert result["validated_forward_fold_count"] == 3
    assert result["registered_hypothesis_count"] == 2
    cash, trade = result["fold_hypothesis_diagnostics"]
    # Sorted alphabetically by hypothesis id.
    assert cash["hypothesis_id"] == "breakout-bear"
    assert cash["cash_abstention_fold_count"] == 3
    assert cash["total_reported_simulated_net_pnl"] == 0
    assert trade["hypothesis_id"] == "trend-bull"
    assert trade["positive_net_fold_count"] == 3
    assert trade["total_reported_simulated_net_pnl"] == 18.0
    assert trade["outcome"] == "forward_packet_arithmetic_consistent_not_confirmatory"
    for blocked in (
        "external_prospective_dataset_independence_verified",
        "pre_registration_externally_attested", "broker_order_and_fill_provenance_verified",
        "independent_confirmatory_test_completed", "statistical_significance_claimed",
        "net_profitability_proven", "strategy_v8_promotion_ready",
        "used_for_selection", "promotion_allowed", "execution_allowed",
        "sealed_holdout_opened",
    ):
        assert result[blocked] is False
    assert result["new_strategy_evaluations_run"] == 0


def test_missing_documents_and_missing_boundaries_fail_closed():
    result = phase16_prospective_oos_evidence(
        None, None, None, research_end=None, reserved_holdout_end=None,
    )
    assert not result["prospective_packet_contract_consistent"]
    assert result["fold_hypothesis_diagnostics"] == []
    assert "phase15_evidence_contract_incomplete" in result["error_codes"]
    assert "prospective_oos_document_missing_or_invalid" in result["error_codes"]
    assert "research_and_sealed_holdout_boundaries_missing" in result["error_codes"]


@pytest.mark.parametrize("start", [
    "2026-01-08T09:30:00Z",  # old selected research
    "2026-01-20T09:30:00Z",  # reserved sealed final holdout
    "2026-01-31T16:00:00Z",  # touching reserved final holdout
    "2026-02-02T09:30:00",  # naive timestamp
])
def test_research_or_sealed_holdout_dates_never_accepted(start):
    registry, document = _data()
    document["data"]["folds"][0]["start"] = start
    result = _run(registry, document)
    assert "duplicate_or_nonprospective_fold" in result["error_codes"]
    assert result["fold_hypothesis_diagnostics"] == []
    assert result["sealed_holdout_opened"] is False


def test_overlapping_forward_folds_and_duplicate_fold_id_fail_closed():
    registry, document = _data()
    document["data"]["folds"][1]["start"] = "2026-02-02T15:00:00Z"
    result = _run(registry, document)
    assert "overlapping_forward_oos_folds" in result["error_codes"]
    registry, document = _data()
    document["data"]["folds"][1]["fold_id"] = "forward-2"
    assert "duplicate_or_nonprospective_fold" in _run(
        registry, document
    )["error_codes"]


def test_registry_link_and_strategy_parameter_hash_must_match():
    registry, document = _data()
    document["data"]["hypothesis_registry_sha256"] = "f" * 64
    assert "prospective_dataset_identity_or_registry_link_invalid" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["evaluations"][0]["strategy_definition_sha256"] = "0" * 64
    assert "unregistered_strategy_or_invalid_decision" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    registry["hypotheses"]["data"]["hypotheses"][0].pop(
        "strategy_definition_sha256"
    )
    assert "invalid_or_duplicated_registered_hypothesis" in _run(
        registry, document
    )["error_codes"]


def test_missing_or_duplicate_hypothesis_fold_matrix_is_rejected():
    registry, document = _data()
    document["data"]["evaluations"].pop()
    assert "incomplete_preregistered_fold_matrix" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["evaluations"][1] = deepcopy(document["data"]["evaluations"][0])
    assert "unknown_or_duplicate_forward_evaluation" in _run(
        registry, document
    )["error_codes"]


def test_abstention_is_never_fabricated_as_profitable_trade():
    registry, document = _data()
    cash = document["data"]["evaluations"][1]
    cash["simulated_net_pnl"] = 1.0
    assert "cash_abstention_or_trade_ledger_evidence_invalid" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["evaluations"][0].pop("trade_ledger_fingerprint")
    assert "cash_abstention_or_trade_ledger_evidence_invalid" in _run(
        registry, document
    )["error_codes"]


def test_bad_net_cost_formula_negative_cost_and_nonfinite_value_fail():
    registry, document = _data()
    document["data"]["evaluations"][0]["simulated_net_pnl"] = 600
    assert "forward_gross_cost_net_reconciliation_failed" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["evaluations"][0]["modeled_impact_cost"] = -1
    assert "forward_gross_cost_net_reconciliation_failed" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["evaluations"][0]["recorded_fees"] = float("nan")
    assert "missing_or_nonfinite_forward_cost" in _run(
        registry, document
    )["error_codes"]


def test_nonidentical_research_fingerprint_and_future_collection_required():
    registry, document = _data()
    document["data"]["source_research_dataset_fingerprint"] = "d" * 64
    assert "prospective_dataset_identity_or_registry_link_invalid" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["data"]["dataset_identity"]["first_collected_at"] = \
        "2026-01-30T09:00:00Z"
    assert "forward_dataset_collection_started_in_sealed_or_research" in _run(
        registry, document
    )["error_codes"]


def test_registry_after_forward_start_or_invalid_budget_fails_closed():
    registry, document = _data()
    registry["hypotheses"]["data"]["registered_at"] = "2026-02-04T09:00:00Z"
    assert "duplicate_or_nonprospective_fold" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    registry["hypotheses"]["data"]["maximum_hypotheses"] = 1
    assert "preregistration_identity_or_budget_invalid" in _run(
        registry, document
    )["error_codes"]


def test_minimum_three_forward_folds_is_enforced_without_production_threshold_changes():
    registry, document = _data()
    registry["hypotheses"]["data"]["hypotheses"][0]["minimum_oos_folds"] = 4
    result = _run(registry, document)
    assert "insufficient_forward_fold_coverage" in result["error_codes"]
    assert result["thresholds_changed"] is False
    assert result["strategy_v8_promotion_ready"] is False


def test_explicit_document_loading_pins_bytes_and_schema(tmp_path, monkeypatch):
    _, document = _data()
    raw = json.dumps(document["data"], sort_keys=True).encode("utf-8")
    path = tmp_path / "forward.json"
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_FILE", str(path))
    monkeypatch.setenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_SHA256", sha)
    assert prospective_oos_document_from_env()["status"] == \
        "digest_and_schema_valid"
    path.write_bytes(raw + b"\n")
    assert prospective_oos_document_from_env()["status"] == "sha256_mismatch"


def test_missing_env_never_synthesizes_future_evidence(monkeypatch):
    monkeypatch.delenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_FILE", raising=False)
    monkeypatch.delenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_SHA256", raising=False)
    assert prospective_oos_document_from_env()["status"] == "not_configured"


def test_integrated_phase9_diagnostics_without_future_source_stay_blocked():
    result = phase9_oos_fill_evidence(None)
    phase16 = result["phase16_prospective_oos_evidence"]
    assert phase16["prospective_packet_contract_consistent"] is False
    assert phase16["fold_hypothesis_diagnostics"] == []
    assert phase16["new_strategy_evaluations_run"] == 0
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False


@pytest.mark.parametrize("corrupt", [None, [], {}, "not_a_dict", 123])
def test_malformed_documents_do_not_grant_promotion(corrupt):
    result = phase16_prospective_oos_evidence(
        corrupt, corrupt, corrupt,
        research_end=RESEARCH_END, reserved_holdout_end=SEALED_END,
    )
    assert result["prospective_packet_contract_consistent"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_timezone_aware_datetime_boundaries_supported():
    now = datetime(2026, 1, 10, 16, tzinfo=timezone.utc)
    seal = datetime(2026, 1, 31, 16, tzinfo=timezone.utc)
    assert _run(research_end=now, sealed_end=seal)[
        "prospective_packet_contract_consistent"
    ] is True


def test_corrupt_registry_and_document_status_are_explicit():
    registry, document = _data()
    registry["hypotheses"]["status"] = "sha256_mismatch"
    assert "phase15_hypothesis_registry_missing" in _run(
        registry, document
    )["error_codes"]
    registry, document = _data()
    document["status"] = "sha256_mismatch"
    assert "prospective_oos_document_missing_or_invalid" in _run(
        registry, document
    )["error_codes"]


def test_false_phase15_contract_cannot_be_upgraded_by_positive_forward_packet():
    result = _run(phase15=False)
    assert "phase15_evidence_contract_incomplete" in result["error_codes"]
    assert result["fold_hypothesis_diagnostics"] == []
    assert result["external_prospective_dataset_independence_verified"] is False
