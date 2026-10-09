"""Phase 14: independent consistency audit of *research-only* PIT regime evidence.

A matching checksum/label and simulated net P&L are NOT independent provider
attestation, causal inference, broker execution proof, or promotion authority.
No new strategy is evaluated; sealed holdout remains untouched.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from typing import Any


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and isfinite(value)


def phase14_historical_regime_validation(
    fill_report: dict[str, Any] | None,
    phase12: dict[str, Any] | None,
    phase13_join: dict[str, Any] | None,
    historical_source: dict[str, Any] | None,
) -> dict[str, Any]:
    """Verify time boundaries, source identity and closed-trade fold accounting.

    This deliberately does not trust Phase 13's 'matched' flag on its own.
    Detecting missing folds prevents cherry-picked regime/return observations
    from being described as complete cross-fold research.
    """
    fills = fill_report if isinstance(fill_report, dict) else {}
    cost = phase12 if isinstance(phase12, dict) else {}
    joined = phase13_join if isinstance(phase13_join, dict) else {}
    feed = historical_source if isinstance(historical_source, dict) else {}
    reasons: set[str] = set()

    if fills.get("oos_fill_coverage_verified") is not True:
        reasons.add("upstream_oos_fill_coverage_unverified")
    if cost.get("simulated_execution_cost_decomposition_verified") is not True:
        reasons.add("upstream_simulated_cost_decomposition_unverified")
    if joined.get("pit_join_contract_complete") is not True:
        reasons.add("upstream_pit_asof_join_incomplete")
    if feed.get("contract_verified") is not True:
        reasons.add("historical_feed_checksum_or_contract_unverified")

    digest = feed.get("source_sha256")
    fingerprint = feed.get("dataset_fingerprint")
    origin = feed.get("source_id")
    observations = feed.get("observations")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(fingerprint, str) or not fingerprint
            or not isinstance(origin, str) or not origin
            or not isinstance(observations, list)
            or not observations or feed.get("observation_count") != len(observations)):
        reasons.add("historical_feed_identity_or_coverage_invalid")
        observations = []

    # A later revision of the same as-of time can otherwise silently rewrite
    # what a historical strategy would have known.
    by_asof: dict[tuple[str, datetime], str] = {}
    observation_ids: set[tuple[str, str]] = set()
    by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, dict):
            reasons.add("malformed_historical_observation")
            continue
        symbol = item.get("symbol")
        identity = item.get("source_observation_id")
        regime = item.get("regime")
        asof = _time(item.get("regime_asof_timestamp"))
        available = _time(item.get("regime_available_at_timestamp"))
        if (not isinstance(symbol, str) or not symbol
                or not isinstance(identity, str) or not identity
                or not isinstance(regime, str) or not regime
                or asof is None or available is None or asof > available
                or item.get("dataset_fingerprint") != fingerprint
                or item.get("source") != "historical_point_in_time_observation"):
            reasons.add("malformed_historical_observation")
            continue
        key = (symbol, identity)
        if key in observation_ids:
            reasons.add("duplicate_source_observation_identity")
        observation_ids.add(key)
        by_id[key] = item
        revision_key = (symbol, asof)
        if revision_key in by_asof and by_asof[revision_key] != regime:
            reasons.add("conflicting_historical_regime_revision")
        by_asof[revision_key] = regime

    folds = fills.get("folds")
    if (not isinstance(folds, list) or not folds
            or fills.get("fold_count") != len(folds)):
        reasons.add("missing_or_inconsistent_fold_coverage")
        folds = []
    intervals: list[tuple[datetime, datetime, str]] = []
    fold_by_id: dict[str, dict[str, Any]] = {}
    for row in folds:
        if not isinstance(row, dict):
            reasons.add("invalid_oos_fold")
            continue
        fid = row.get("fold_id")
        start, end = _time(row.get("oos_start")), _time(row.get("oos_end"))
        decision = row.get("decision")
        if (not isinstance(fid, str) or not fid or fid in fold_by_id
                or start is None or end is None or start >= end
                or decision not in ("TRADE", "NO_TRADE")
                or row.get("errors")):
            reasons.add("invalid_or_duplicate_oos_fold")
            continue
        if (decision == "NO_TRADE" and row.get("observed_fill_count") != 0
                or decision == "TRADE" and row.get("status") != "recorded"):
            reasons.add("invalid_fold_decision_evidence")
        intervals.append((start, end, fid))
        fold_by_id[fid] = row
    intervals.sort()
    for a, b in zip(intervals, intervals[1:]):
        if a[1] >= b[0]:
            reasons.add("overlapping_or_touching_oos_fold_boundaries")

    trades = cost.get("closed_positions")
    matches = joined.get("matched_snapshots")
    if (not isinstance(trades, list) or not trades
            or not isinstance(matches, list)
            or len(trades) != len(matches)
            or joined.get("closed_position_count") != len(trades)
            or joined.get("matched_count") != len(trades)):
        reasons.add("mismatched_closeout_regime_coverage")
        trades, matches = [], []
    by_entry: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for match in matches:
        if not isinstance(match, dict):
            reasons.add("malformed_regime_trade_match")
            continue
        key = tuple(match.get(k) for k in (
            "fold_id", "strategy_id", "symbol", "entry_timestamp"
        ))
        if any(not isinstance(x, str) or not x for x in key) or key in by_entry:
            reasons.add("duplicate_or_invalid_regime_trade_identity")
            continue
        by_entry[key] = match

    groups: dict[tuple[str, str, str], dict[str, float | int]] = defaultdict(
        lambda: {
            "closed_trade_count": 0,
            "positive_net_trade_count": 0,
            "negative_net_trade_count": 0,
            "reference_price_gross_pnl": 0.0,
            "modeled_slippage_cost": 0.0,
            "modeled_impact_cost": 0.0,
            "modeled_half_spread_cost": 0.0,
            "recorded_fees": 0.0,
            "simulated_net_pnl": 0.0,
        }
    )
    seen_trades: set[tuple[str, str, str, str]] = set()
    represented_folds: set[str] = set()
    for trade in trades:
        if not isinstance(trade, dict):
            reasons.add("malformed_cost_trade")
            continue
        key = tuple(trade.get(k) for k in (
            "fold_id", "strategy_id", "symbol", "entry_timestamp"
        ))
        if any(not isinstance(x, str) or not x for x in key) or key in seen_trades:
            reasons.add("duplicate_or_invalid_cost_trade_identity")
            continue
        seen_trades.add(key)
        matched = by_entry.get(key)
        fold = fold_by_id.get(key[0])
        entry = _time(key[3])
        if matched is None or fold is None or fold.get("decision") != "TRADE":
            reasons.add("unmatched_trade_or_nontrade_fold")
            continue
        start, end = _time(fold["oos_start"]), _time(fold["oos_end"])
        if start is None or end is None or entry is None or not start <= entry <= end:
            reasons.add("trade_outside_research_oos_fold")
            continue
        historical = trade.get("historical_regime")
        record_id = matched.get("source_observation_id")
        raw = by_id.get((key[2], record_id))
        asof, available = (
            _time(matched.get("regime_asof_timestamp")),
            _time(matched.get("regime_available_at_timestamp")),
        )
        if (not isinstance(historical, dict)
                or historical.get("status") != "timestamp_and_provenance_contract_consistent"
                or raw is None
                or asof is None or available is None
                or not asof <= available <= entry
                or historical.get("regime") != matched.get("regime")
                or matched.get("regime") != raw.get("regime")
                or matched.get("dataset_fingerprint") != fingerprint
                or matched.get("regime_asof_timestamp") != raw["regime_asof_timestamp"]
                or matched.get("regime_available_at_timestamp") != raw["regime_available_at_timestamp"]):
            reasons.add("regime_observation_provenance_mismatch_or_lookahead")
            continue
        # Ensure no matched observation is older than a more recent available
        # observation. This is independent of the Phase 13 join's reported flag.
        later = [
            other for other in observations if isinstance(other, dict)
            and other.get("symbol") == key[2]
            and other.get("source_observation_id") != record_id
            and (t := _time(other.get("regime_available_at_timestamp"))) is not None
            and available < t <= entry
        ]
        if later:
            reasons.add("historical_regime_not_latest_available_at_entry")
            continue
        components = (
            "reference_price_gross_pnl", "modeled_slippage_cost",
            "modeled_impact_cost", "modeled_half_spread_cost", "recorded_fees",
            "engine_executed_net_pnl"
        )
        if any(not _finite(trade.get(k)) for k in components):
            reasons.add("nonfinite_trade_cost_component")
            continue
        gross = trade["reference_price_gross_pnl"]
        net = trade["engine_executed_net_pnl"]
        total_cost = sum(trade[k] for k in components[1:5])
        if any(trade[k] < 0 for k in components[1:5]) or abs(gross - total_cost - net) > 0.065:
            reasons.add("reference_cost_net_pnl_reconciliation_failed")
            continue
        represented_folds.add(key[0])
        bucket = groups[(key[0], key[1], matched["regime"])]
        bucket["closed_trade_count"] += 1
        bucket["positive_net_trade_count"] += int(net > 0)
        bucket["negative_net_trade_count"] += int(net < 0)
        bucket["reference_price_gross_pnl"] += gross
        for field in components[1:5]:
            bucket[field] += trade[field]
        bucket["simulated_net_pnl"] += net

    trade_folds = {
        fid for fid, row in fold_by_id.items() if row["decision"] == "TRADE"
    }
    if not trade_folds or represented_folds != trade_folds:
        reasons.add("trade_fold_closed_position_coverage_incomplete")
    valid = not reasons and bool(groups)
    descriptive = [{
        "fold_id": fold, "strategy_id": strategy, "regime": regime,
        **{name: value if name.endswith("_count") else round(value, 2)
           for name, value in summary.items()},
    } for (fold, strategy, regime), summary in sorted(groups.items())] if valid else []
    fold_net = defaultdict(float)
    for row in descriptive:
        fold_net[row["fold_id"]] += row["simulated_net_pnl"]
    fold_count = len(fold_net)
    positive_folds = sum(v > 0 for v in fold_net.values())
    return {
        "schema_version": "phase14-historical-regime-validation.v1",
        "historical_source_id": origin if valid else None,
        "historical_source_sha256": digest if valid else None,
        "research_fold_count": len(fold_by_id),
        "trade_fold_count": len(trade_folds),
        "covered_trade_fold_count": len(represented_folds) if valid else 0,
        "regime_trade_count": len(trades) if valid else 0,
        "oos_fold_and_regime_accounting_verified": valid,
        "fold_regime_cost_summaries": descriptive,
        "descriptive_fold_stability": {
            "evaluated_fold_count": fold_count,
            "positive_net_fold_count": positive_folds,
            "negative_net_fold_count": sum(v < 0 for v in fold_net.values()),
            "positive_net_fold_fraction": (
                round(positive_folds / fold_count, 4) if fold_count else None
            ),
            "reliability_status": "descriptive_only_not_statistical_significance",
        },
        "error_codes": sorted(reasons),
        "external_provider_authenticity_verified": False,
        "independent_historical_regime_audit_complete": False,
        "actual_broker_execution_costs_verified": False,
        "net_profitability_proven": False,
        "strategy_v8_validation_ready": False,
        "strategy_v8_hypotheses_tested": 0,
        "sealed_holdout_opened": False,
        "thresholds_changed": False,
        "diagnostic_only": True,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "readiness_blockers": [
            "external_historical_archive_authenticity_not_independently_attested",
            "simulated_costs_are_not_measured_broker_costs",
            "insufficient_evidence_for_out_of_sample_positive_net_edge",
            "v8_preregistered_trials_and_multiplicity_controls_not_executed",
        ] + ([] if valid else ["fold_or_source_integrity_incomplete"]),
    }
