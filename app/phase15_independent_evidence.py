"""Phase 15: corroborate PIT records with a separately pinned archive, not hindsight.

The auxiliary archive and hypothesis registry can have consistent BYTES and
timestamps while still being self-asserted. Never claim cryptographic identity
proof, an independently attested provider, statistical power, or trading safety.
All results stay descriptive. No new strategy run or sealed holdout access.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any

MAX_DOCUMENT_BYTES = 2_000_000
ARCHIVE_SCHEMA = "phase15-archived-provider-records.v1"
REGISTRY_SCHEMA = "phase15-preregistered-v8-hypotheses.v1"


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: Any) -> bool:
    return (_str(value) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value.lower()))


def _read_json(path: Path | None, digest: str | None, schema: str) -> dict[str, Any]:
    if path is None and digest is None:
        return {"status": "not_configured", "data": None, "sha256": None}
    if path is None or not _digest(digest):
        return {"status": "path_or_digest_invalid", "data": None, "sha256": None}
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
            return {"status": "file_missing_or_oversized", "data": None, "sha256": None}
        contents = path.read_bytes()
        if len(contents) > MAX_DOCUMENT_BYTES:
            return {"status": "file_missing_or_oversized", "data": None, "sha256": None}
        actual = hashlib.sha256(contents).hexdigest()
        if actual != digest.lower():
            return {"status": "sha256_mismatch", "data": None, "sha256": None}
        data = json.loads(contents.decode("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {"status": "unreadable_document", "data": None, "sha256": None}
    if not isinstance(data, dict) or data.get("schema_version") != schema:
        return {"status": "schema_mismatch", "data": None, "sha256": None}
    return {"status": "digest_and_schema_valid", "data": data, "sha256": actual}


def load_phase15_documents(
    *,
    archive_file: Path | None = None,
    archive_sha256: str | None = None,
    hypothesis_file: Path | None = None,
    hypothesis_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "archive": _read_json(archive_file, archive_sha256, ARCHIVE_SCHEMA),
        "hypotheses": _read_json(hypothesis_file, hypothesis_sha256, REGISTRY_SCHEMA),
    }


def phase15_documents_from_env() -> dict[str, Any]:
    def path(name: str) -> Path | None:
        value = os.getenv(name, "").strip()
        return Path(value) if value else None

    def digest(name: str) -> str | None:
        return os.getenv(name, "").strip() or None

    return load_phase15_documents(
        archive_file=path("BACKTEST_RESEARCH_V8_ARCHIVE_FILE"),
        archive_sha256=digest("BACKTEST_RESEARCH_V8_ARCHIVE_SHA256"),
        hypothesis_file=path("BACKTEST_RESEARCH_V8_HYPOTHESES_FILE"),
        hypothesis_sha256=digest("BACKTEST_RESEARCH_V8_HYPOTHESES_SHA256"),
    )


def phase15_v8_evidence_validation(
    fills: dict[str, Any] | None,
    phase13: dict[str, Any] | None,
    phase14: dict[str, Any] | None,
    source: dict[str, Any] | None,
    documents: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare independent *documents*, not independently authenticated facts.

    Only the existing Phase 14 OOS summaries are examined. No hypothesis is
    fitted, no backtest rerun, and no significance test is inferred from
    OOS windows that have already participated in candidate selection.
    """
    f = fills if isinstance(fills, dict) else {}
    p13 = phase13 if isinstance(phase13, dict) else {}
    p14 = phase14 if isinstance(phase14, dict) else {}
    src = source if isinstance(source, dict) else {}
    docs = documents if isinstance(documents, dict) else {}
    archive = docs.get("archive") if isinstance(docs.get("archive"), dict) else {}
    registry = docs.get("hypotheses") if isinstance(docs.get("hypotheses"), dict) else {}
    reasons: set[str] = set()

    if p14.get("oos_fold_and_regime_accounting_verified") is not True:
        reasons.add("phase14_cross_fold_integrity_unverified")
    if p13.get("pit_join_contract_complete") is not True:
        reasons.add("phase13_pit_join_incomplete")
    if src.get("contract_verified") is not True:
        reasons.add("phase13_source_contract_unverified")
    if archive.get("status") != "digest_and_schema_valid":
        reasons.add("independent_archive_document_not_verified")
    if registry.get("status") != "digest_and_schema_valid":
        reasons.add("preregistered_hypothesis_document_not_verified")

    # Validate entire archive, not only the cherry-picked matched record IDs.
    archive_data = archive.get("data")
    archived: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(archive_data, dict):
        records = archive_data.get("records")
        if (archive_data.get("historical_feed_sha256") != src.get("source_sha256")
                or archive_data.get("source_dataset_fingerprint")
                != src.get("dataset_fingerprint")
                or not _str(archive_data.get("independent_archive_id"))
                or archive_data.get("independent_archive_id") == src.get("source_id")
                or not isinstance(records, list) or not records or len(records) > 20000):
            reasons.add("archive_source_identity_or_dataset_mismatch")
        else:
            for row in records:
                if not isinstance(row, dict):
                    reasons.add("invalid_archive_record")
                    continue
                symbol, oid = row.get("symbol"), row.get("source_observation_id")
                asof = _instant(row.get("regime_asof_timestamp"))
                available = _instant(row.get("regime_available_at_timestamp"))
                publisher = _instant(row.get("publisher_first_seen_at"))
                archiver = _instant(row.get("archive_first_seen_at"))
                if (not _str(symbol) or not _str(oid) or not _str(row.get("regime"))
                        or not _str(row.get("publisher_record_id"))
                        or asof is None or available is None
                        or publisher is None or archiver is None
                        or not asof <= publisher <= archiver
                        or not asof <= available
                        or row.get("source_dataset_fingerprint")
                        != src.get("dataset_fingerprint")):
                    reasons.add("invalid_archive_record")
                    continue
                key = (symbol.upper(), oid)
                if key in archived:
                    reasons.add("duplicate_archive_record_identity")
                archived[key] = row
    elif archive.get("status") == "digest_and_schema_valid":
        reasons.add("archive_document_schema_invalid")

    # Require byte-level cross-document agreement for every matched entry.
    source_by_id = {
        (r["symbol"], r["source_observation_id"]): r
        for r in src.get("observations", []) if isinstance(r, dict)
        and _str(r.get("symbol")) and _str(r.get("source_observation_id"))
    }
    matches = p13.get("matched_snapshots")
    if not isinstance(matches, list) or not matches:
        reasons.add("missing_pit_matched_entries")
        matches = []
    verified_rows = 0
    for matched in matches:
        if not isinstance(matched, dict):
            reasons.add("invalid_matched_trade")
            continue
        key = (matched.get("symbol"), matched.get("source_observation_id"))
        archive_row = archived.get(key)
        source_row = source_by_id.get(key)
        entry = _instant(matched.get("entry_timestamp"))
        if archive_row is None or source_row is None or entry is None:
            reasons.add("missing_archive_correspondence")
            continue
        fixed = ("regime", "regime_asof_timestamp", "regime_available_at_timestamp")
        publisher = _instant(archive_row.get("publisher_first_seen_at"))
        archiver = _instant(archive_row.get("archive_first_seen_at"))
        if (any(archive_row.get(field) != source_row.get(field) or
                matched.get(field) != source_row.get(field) for field in fixed)
                or publisher is None or archiver is None or publisher > entry
                or archiver > entry):
            reasons.add("archive_mismatch_or_post_entry_first_seen")
            continue
        verified_rows += 1
    if not matches or verified_rows != len(matches):
        reasons.add("archival_trade_coverage_incomplete")

    # Registry timestamps are self-asserted until an external timestamping
    # authority attests the hash. Requiring pre-OOS still catches obvious leaks.
    folds = f.get("folds")
    windows = []
    for fold in folds if isinstance(folds, list) else []:
        if isinstance(fold, dict):
            when = _instant(fold.get("oos_start"))
            if when is not None:
                windows.append(when)
    hypotheses: list[dict[str, Any]] = []
    if not windows:
        reasons.add("missing_nested_oos_start_times")
    registry_data = registry.get("data")
    if isinstance(registry_data, dict):
        registered = _instant(registry_data.get("registered_at"))
        max_trials = registry_data.get("maximum_hypotheses")
        family_alpha = registry_data.get("familywise_alpha")
        items = registry_data.get("hypotheses")
        if (registered is None or not windows or registered >= min(windows)
                or type(max_trials) is not int or not 1 <= max_trials <= 100
                or type(family_alpha) not in (int, float)
                or not isfinite(family_alpha) or not 0 < family_alpha <= 0.05
                or not isinstance(items, list) or not items
                or len(items) > max_trials):
            reasons.add("hypothesis_preregistration_contract_invalid_or_post_oos")
        else:
            identifiers: set[str] = set()
            for item in items:
                if (not isinstance(item, dict)
                        or not all(_str(item.get(k)) for k in (
                            "hypothesis_id", "strategy_id", "regime"))
                        or item.get("metric") != "simulated_fold_net_pnl_after_costs"
                        or item.get("expected_direction") != "positive"
                        or type(item.get("minimum_oos_folds")) is not int
                        or item["minimum_oos_folds"] < 3
                        or item["hypothesis_id"] in identifiers):
                    reasons.add("invalid_or_duplicate_preregistered_hypothesis")
                    continue
                identifiers.add(item["hypothesis_id"])
                hypotheses.append(item)
    elif registry.get("status") == "digest_and_schema_valid":
        reasons.add("hypothesis_document_schema_invalid")

    summaries = p14.get("fold_regime_cost_summaries")
    if not isinstance(summaries, list):
        reasons.add("invalid_phase14_fold_cost_summaries")
        summaries = []
    fold_net: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in summaries:
        if not isinstance(row, dict):
            reasons.add("invalid_phase14_fold_cost_summaries")
            continue
        key = (row.get("strategy_id"), row.get("regime"), row.get("fold_id"))
        net = row.get("simulated_net_pnl")
        if (any(not _str(k) for k in key) or type(net) not in (int, float)
                or not isfinite(net)):
            reasons.add("invalid_phase14_fold_cost_summaries")
            continue
        fold_net[key] += net

    reports: list[dict[str, Any]] = []
    if not reasons:
        for item in hypotheses:
            values = [
                value for (strategy, regime, _fold), value in sorted(fold_net.items())
                if strategy == item["strategy_id"] and regime == item["regime"]
            ]
            enough = len(values) >= item["minimum_oos_folds"]
            reports.append({
                "hypothesis_id": item["hypothesis_id"],
                "strategy_id": item["strategy_id"],
                "regime": item["regime"],
                "distinct_research_oos_folds": len(values),
                "minimum_oos_folds": item["minimum_oos_folds"],
                "fold_coverage_sufficient_for_description": enough,
                "positive_net_fold_count": sum(v > 0 for v in values),
                "negative_net_fold_count": sum(v < 0 for v in values),
                "total_simulated_net_pnl": round(sum(values), 2),
                "outcome": (
                    "descriptive_only_no_independent_hypothesis_test"
                    if enough else "insufficient_distinct_oos_folds"
                ),
                "pre_registration_externally_timestamped": False,
                "independent_oos_validation": False,
                "statistically_significant": None,
            })
    contract_consistent = (
        not reasons and bool(reports)
        and all(x["fold_coverage_sufficient_for_description"] for x in reports)
    )
    if reasons:
        reports = []
    return {
        "schema_version": "phase15-independent-pit-and-v8-hypothesis.v1",
        "auxiliary_documents_contract_consistent": contract_consistent,
        "archived_observations_matched": verified_rows if not reasons else 0,
        "auxiliary_archive_sha256": archive.get("sha256"),
        "hypothesis_registry_sha256": registry.get("sha256"),
        "archive_document_status": archive.get("status", "not_configured"),
        "hypothesis_document_status": registry.get("status", "not_configured"),
        "registered_hypothesis_count": len(hypotheses),
        "descriptive_hypothesis_diagnostics": reports,
        "error_codes": sorted(reasons),
        "external_archive_authenticity_verified": False,
        "external_preregistration_timestamp_verified": False,
        "independent_oos_hypothesis_validation_completed": False,
        "statistical_significance_claimed": False,
        "broker_measured_execution_costs_verified": False,
        "profitability_proven": False,
        "strategy_v8_promotion_ready": False,
        "new_strategy_evaluations_run": 0,
        "sealed_holdout_opened": False,
        "thresholds_changed": False,
        "diagnostic_only": True,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "remaining_blockers": [
            "independent_provider_archive_authenticity",
            "externally_timestamped_hypothesis_registration",
            "new_independent_oos_with_unmodified_preregistered_strategy",
            "validated_multiplicity_control_and_broker_costs",
        ] + ([] if contract_consistent else ["incomplete_phase15_evidence_contract"]),
    }
