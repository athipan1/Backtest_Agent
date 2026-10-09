"""Phase 16: prospective OOS document contract, never an authorization gate.

Do not replay sealed final holdout or treat an externally supplied result packet
as independently observed fills. This only checks boundaries, completeness,
immutable preregistered identities and reported arithmetic for FUTURE windows
strictly after both the research slice and reserved sealed-holdout interval.
"""
from __future__ import annotations

import os
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any

from app.phase15_independent_evidence import _read_json, _digest

SCHEMA = "phase16-prospective-oos-evidence.v1"
COSTS = ("modeled_slippage_cost", "modeled_impact_cost",
         "modeled_half_spread_cost", "recorded_fees")


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: Any) -> bool:
    return type(value) in (int, float) and isfinite(value)


def prospective_oos_document_from_env() -> dict[str, Any]:
    filename = os.getenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_FILE", "").strip()
    digest = os.getenv("BACKTEST_RESEARCH_V8_FORWARD_OOS_SHA256", "").strip()
    return _read_json(Path(filename) if filename else None, digest or None, SCHEMA)


def phase16_prospective_oos_evidence(
    phase15_documents: dict[str, Any] | None,
    phase15_result: dict[str, Any] | None,
    oos_document: dict[str, Any] | None,
    *,
    research_end: datetime | str | None,
    reserved_holdout_end: datetime | str | None,
) -> dict[str, Any]:
    """Validate all registered hypotheses x prospective folds, without fitting.

    Result values, dataset independence, prereg times and all forward trade
    observations remain external assertions, not a broker audit. Never grant
    v8 eligibility even for mathematically positive results.
    """
    docs = phase15_documents if isinstance(phase15_documents, dict) else {}
    registry_doc = docs.get("hypotheses")
    registry_doc = registry_doc if isinstance(registry_doc, dict) else {}
    phase15 = phase15_result if isinstance(phase15_result, dict) else {}
    packet = oos_document if isinstance(oos_document, dict) else {}
    reasons: set[str] = set()
    if phase15.get("auxiliary_documents_contract_consistent") is not True:
        reasons.add("phase15_evidence_contract_incomplete")
    if registry_doc.get("status") != "digest_and_schema_valid":
        reasons.add("phase15_hypothesis_registry_missing")
    if packet.get("status") != "digest_and_schema_valid":
        reasons.add("prospective_oos_document_missing_or_invalid")
    research_cut = _time(research_end) if isinstance(research_end, str) else research_end
    sealed_cut = (
        _time(reserved_holdout_end)
        if isinstance(reserved_holdout_end, str) else reserved_holdout_end
    )
    if (research_cut is None or sealed_cut is None
            or research_cut.tzinfo is None or sealed_cut.tzinfo is None
            or research_cut.utcoffset() is None or sealed_cut.utcoffset() is None
            or not research_cut < sealed_cut):
        reasons.add("research_and_sealed_holdout_boundaries_missing")

    prereg = registry_doc.get("data")
    prereg = prereg if isinstance(prereg, dict) else {}
    registered = prereg.get("hypotheses")
    registered = registered if isinstance(registered, list) else []
    registry_sha = registry_doc.get("sha256")
    registration_time = _time(prereg.get("registered_at"))
    if (not registered or not _digest(registry_sha) or registration_time is None
            or type(prereg.get("maximum_hypotheses")) is not int
            or len(registered) > prereg["maximum_hypotheses"]):
        reasons.add("preregistration_identity_or_budget_invalid")

    declared: dict[str, dict[str, Any]] = {}
    for item in registered:
        if not isinstance(item, dict):
            reasons.add("invalid_registered_hypothesis")
            continue
        hid, sid, regime, locked = (
            item.get("hypothesis_id"), item.get("strategy_id"),
            item.get("regime"), item.get("strategy_definition_sha256"),
        )
        if (not all(_str(v) for v in (hid, sid, regime))
                or not _digest(locked)
                or item.get("metric") != "simulated_fold_net_pnl_after_costs"
                or item.get("expected_direction") != "positive"
                or type(item.get("minimum_oos_folds")) is not int
                or item["minimum_oos_folds"] < 3
                or hid in declared):
            reasons.add("invalid_or_duplicated_registered_hypothesis")
            continue
        declared[hid] = item

    payload = packet.get("data")
    payload = payload if isinstance(payload, dict) else {}
    identity = payload.get("dataset_identity")
    identity = identity if isinstance(identity, dict) else {}
    first_observed = _time(identity.get("first_collected_at"))
    if (not _str(identity.get("source_id"))
            or not _digest(identity.get("dataset_sha256"))
            or not _str(identity.get("data_feed"))
            or not _str(identity.get("sampling_frequency"))
            or first_observed is None
            or payload.get("hypothesis_registry_sha256") != registry_sha
            or payload.get("source_research_dataset_fingerprint")
            == identity.get("dataset_sha256")):
        reasons.add("prospective_dataset_identity_or_registry_link_invalid")
    if (not _str(payload.get("source_research_dataset_fingerprint"))
            or not _str(payload.get("source_reserved_holdout_id"))):
        reasons.add("missing_research_or_sealed_holdout_provenance")

    folds = payload.get("folds")
    folds = folds if isinstance(folds, list) else []
    if not folds or len(folds) > 300:
        reasons.add("missing_or_excessive_prospective_folds")
    fold_ids: set[str] = set()
    periods: list[tuple[datetime, datetime, str]] = []
    for row in folds:
        if not isinstance(row, dict):
            reasons.add("invalid_prospective_fold")
            continue
        fid = row.get("fold_id")
        start, end = _time(row.get("start")), _time(row.get("end"))
        if (not _str(fid) or fid in fold_ids or start is None or end is None
                or not start < end
                or sealed_cut is None or start <= sealed_cut
                or research_cut is None or start <= research_cut
                or registration_time is None or registration_time >= start):
            reasons.add("duplicate_or_nonprospective_fold")
            continue
        fold_ids.add(fid)
        periods.append((start, end, fid))
    periods.sort()
    if any(left[1] >= right[0] for left, right in zip(periods, periods[1:])):
        reasons.add("overlapping_forward_oos_folds")
    if periods and first_observed is not None and first_observed < periods[0][0]:
        # A feed can start before OOS, but the *declared* source identity alone
        # cannot prove its samples are genuinely out of selection history.
        # Do not accept a claimed new cohort whose collection starts in-sample.
        if sealed_cut is not None and first_observed <= sealed_cut:
            reasons.add("forward_dataset_collection_started_in_sealed_or_research")

    entries = payload.get("evaluations")
    entries = entries if isinstance(entries, list) else []
    if (not entries or len(entries) > 30000 or
            len(entries) != len(fold_ids) * len(declared)):
        reasons.add("incomplete_preregistered_fold_matrix")
    found: set[tuple[str, str]] = set()
    by_hypothesis: dict[str, dict[str, float | int]] = {
        hid: {
            "fold_count": 0, "trade_fold_count": 0, "cash_abstention_fold_count": 0,
            "positive_net_fold_count": 0, "negative_net_fold_count": 0,
            "total_reported_simulated_net_pnl": 0.0,
        }
        for hid in declared
    }
    for row in entries:
        if not isinstance(row, dict):
            reasons.add("malformed_forward_evaluation")
            continue
        fid, hid, decision = row.get("fold_id"), row.get("hypothesis_id"), row.get("decision")
        key = (fid, hid)
        if (not _str(fid) or not _str(hid) or fid not in fold_ids
                or hid not in declared or key in found):
            reasons.add("unknown_or_duplicate_forward_evaluation")
            continue
        found.add(key)
        meta = declared[hid]
        if (row.get("strategy_id") != meta["strategy_id"]
                or row.get("regime") != meta["regime"]
                or row.get("strategy_definition_sha256") != meta["strategy_definition_sha256"]
                or decision not in ("TRADE", "NO_TRADE")):
            reasons.add("unregistered_strategy_or_invalid_decision")
            continue
        numbers = ("reference_price_gross_pnl", *COSTS, "simulated_net_pnl")
        if any(not _number(row.get(k)) for k in numbers):
            reasons.add("missing_or_nonfinite_forward_cost")
            continue
        if (decision == "NO_TRADE" and any(abs(row[k]) > 1e-9 for k in numbers)
                or decision == "TRADE" and not _str(row.get("trade_ledger_fingerprint"))):
            reasons.add("cash_abstention_or_trade_ledger_evidence_invalid")
            continue
        gross, net = row["reference_price_gross_pnl"], row["simulated_net_pnl"]
        costs = sum(row[k] for k in COSTS)
        if any(row[k] < 0 for k in COSTS) or abs(gross - costs - net) > 0.015:
            reasons.add("forward_gross_cost_net_reconciliation_failed")
            continue
        group = by_hypothesis[hid]
        group["fold_count"] += 1
        group["trade_fold_count"] += int(decision == "TRADE")
        group["cash_abstention_fold_count"] += int(decision == "NO_TRADE")
        group["positive_net_fold_count"] += int(net > 0)
        group["negative_net_fold_count"] += int(net < 0)
        group["total_reported_simulated_net_pnl"] += net

    if len(found) != len(fold_ids) * len(declared):
        reasons.add("missing_registered_hypothesis_fold")
    for hid, item in declared.items():
        if by_hypothesis[hid]["fold_count"] < item["minimum_oos_folds"]:
            reasons.add("insufficient_forward_fold_coverage")
    verified = not reasons and bool(declared) and bool(periods)
    summaries = []
    if verified:
        for hid, item in sorted(declared.items()):
            d = by_hypothesis[hid]
            summaries.append({
                "hypothesis_id": hid,
                "strategy_id": item["strategy_id"],
                "regime": item["regime"],
                **{key: round(value, 2)
                   if key == "total_reported_simulated_net_pnl" else value
                   for key, value in d.items()},
                "outcome": "forward_packet_arithmetic_consistent_not_confirmatory",
                "statistical_significance": None,
            })
    return {
        "schema_version": "phase16-prospective-oos-evidence.v1",
        "prospective_packet_contract_consistent": verified,
        "packet_sha256": packet.get("sha256"),
        "registry_sha256": registry_sha,
        "research_end": research_cut.isoformat() if research_cut is not None else None,
        "reserved_holdout_end": sealed_cut.isoformat() if sealed_cut is not None else None,
        "validated_forward_fold_count": len(fold_ids) if verified else 0,
        "registered_hypothesis_count": len(declared),
        "fold_hypothesis_diagnostics": summaries,
        "error_codes": sorted(reasons),
        "external_prospective_dataset_independence_verified": False,
        "pre_registration_externally_attested": False,
        "broker_order_and_fill_provenance_verified": False,
        "independent_confirmatory_test_completed": False,
        "statistical_significance_claimed": False,
        "net_profitability_proven": False,
        "strategy_v8_promotion_ready": False,
        "new_strategy_evaluations_run": 0,
        "sealed_holdout_opened": False,
        "thresholds_changed": False,
        "diagnostic_only": True,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "remaining_blockers": [
            "independent_external_timestamp_attestation_for_preregistration",
            "verifiably_outside_selection_and_sealed_holdout_broker_quality_data",
            "replay_and_reconcile_independent_forward_execution_ledger",
            "preregistered_statistical_multiplicity_and_reliability_validation",
        ] + ([] if verified else ["forward_oos_contract_missing_or_invalid"]),
    }
