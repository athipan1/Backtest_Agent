"""Phase 13: optional, checksum-pinned historical-regime observations.

A historical feed is NOT reconstructed from current Manager state, full-sample
returns, or sealed holdout. Every observation needs an explicit time at which
it was available, never merely the timestamp of the market bar.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any


SCHEMA = "phase13-historical-regime-feed.v1"
MAX_FILE_BYTES = 4_000_000
# Research diagnostics only, not a new strategy-promotion threshold.
MAX_AGE = timedelta(days=7)


def _instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None and value.utcoffset() is not None else None


def _blank(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "status": reason,
        "contract_verified": False,
        "source_id": None,
        "source_sha256": None,
        "dataset_fingerprint": None,
        "observations": [],
        "observation_count": 0,
        "historical_source_independently_audited": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }


def read_historical_regime_feed(
    path: Path | None,
    expected_sha256: str | None,
    *,
    research_end: datetime | str,
) -> dict[str, Any]:
    """Read only a locally supplied, digest-pinned source with pre-holdout bounds."""
    if path is None and not expected_sha256:
        return _blank("historical_feed_not_configured")
    if path is None or not expected_sha256:
        return _blank("file_or_checksum_missing")
    expected = expected_sha256.lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        return _blank("invalid_expected_sha256")
    cutoff = _instant(research_end) if isinstance(research_end, str) else research_end
    if cutoff is None or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return _blank("research_end_unverified")
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return _blank("historical_feed_file_unavailable_or_oversized")
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            return _blank("historical_feed_file_unavailable_or_oversized")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            return _blank("historical_feed_digest_mismatch")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError):
        return _blank("historical_feed_unreadable")
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA:
        return _blank("invalid_historical_feed_schema")
    source_id, fingerprint = payload.get("source_id"), payload.get("dataset_fingerprint")
    rows = payload.get("observations")
    if (not isinstance(source_id, str) or not source_id.strip()
            or not isinstance(fingerprint, str) or not fingerprint.strip()
            or not isinstance(rows, list) or not rows or len(rows) > 20000):
        return _blank("historical_feed_metadata_missing")
    seen: set[tuple[str, str]] = set()
    safe: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            return _blank("historical_observation_invalid")
        symbol, regime, event_id = (
            row.get("symbol"), row.get("regime"), row.get("source_observation_id")
        )
        asof = _instant(row.get("regime_asof_timestamp"))
        available = _instant(row.get("regime_available_at_timestamp"))
        if (not all(isinstance(x, str) and x.strip() for x in (symbol, regime, event_id))
                or asof is None or available is None
                or asof > available or available > cutoff
                or row.get("source") != "historical_point_in_time_observation"
                or row.get("dataset_fingerprint") != fingerprint):
            # A future observation is rejected even if it would not be joined.
            return _blank("historical_observation_invalid_or_outside_research")
        identity = (symbol.upper(), event_id)
        if identity in seen:
            return _blank("duplicate_historical_observation_id")
        seen.add(identity)
        safe.append({
            "symbol": symbol.upper(), "regime": regime,
            "source_observation_id": event_id,
            "regime_asof_timestamp": row["regime_asof_timestamp"],
            "regime_available_at_timestamp": row["regime_available_at_timestamp"],
            "source": row["source"], "dataset_fingerprint": fingerprint,
        })
    return {
        "schema_version": SCHEMA, "status": "checksum_and_contract_valid",
        "contract_verified": True, "source_id": source_id,
        "source_sha256": digest, "dataset_fingerprint": fingerprint,
        "observations": safe, "observation_count": len(safe),
        "historical_source_independently_audited": False,
        "used_for_selection": False, "promotion_allowed": False,
        "execution_allowed": False, "sealed_holdout_opened": False,
    }


def historical_regime_feed_from_env(*, research_end: datetime | str) -> dict[str, Any]:
    filename = os.getenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_FILE", "").strip()
    digest = os.getenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_SHA256", "").strip()
    return read_historical_regime_feed(
        Path(filename) if filename else None, digest or None, research_end=research_end
    )


def bind_regime_at_entry(
    closed_evidence: dict[str, Any] | None,
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    """As-of join only: latest snapshot whose availability precedes the entry.

    Fully isolate from selection and return no label for stale or ambiguous
    history. The source checksum proves exact bytes, not provider truth.
    """
    evidence = closed_evidence if isinstance(closed_evidence, dict) else {}
    feed = source if isinstance(source, dict) else _blank("historical_feed_not_configured")
    positions = evidence.get("closed_positions")
    positions = positions if isinstance(positions, list) else []
    labels: list[dict[str, Any]] = []
    missing = []
    if not evidence.get("paired_closeout_reconciliation_verified") or not positions:
        missing.append("closed_position_evidence_unverified")
    if feed.get("contract_verified") is not True:
        missing.append("historical_feed_not_verified")
    if not missing:
        for position in positions:
            if not isinstance(position, dict):
                missing.append("invalid_closed_position")
                continue
            timestamp = _instant(position.get("entry_timestamp"))
            if timestamp is None:
                missing.append("invalid_entry_timestamp")
                continue
            candidates = []
            for item in feed["observations"]:
                if item["symbol"] != position.get("symbol"):
                    continue
                available = _instant(item["regime_available_at_timestamp"])
                asof = _instant(item["regime_asof_timestamp"])
                if available is not None and asof is not None and asof <= available <= timestamp:
                    candidates.append((available, asof, item))
            if not candidates:
                missing.append("entry_missing_prior_pit_regime")
                continue
            candidates.sort(key=lambda item: (item[0], item[1]))
            picked_time, _, selected = candidates[-1]
            if sum(item[0] == picked_time for item in candidates) != 1:
                missing.append("ambiguous_latest_regime_observation")
                continue
            if timestamp - picked_time > MAX_AGE:
                missing.append("stale_pit_regime_observation")
                continue
            labels.append({
                **{key: position[key] for key in (
                    "fold_id", "strategy_id", "symbol", "entry_timestamp"
                )},
                "regime": selected["regime"],
                "regime_asof_timestamp": selected["regime_asof_timestamp"],
                "regime_available_at_timestamp": selected["regime_available_at_timestamp"],
                "source": selected["source"],
                "dataset_fingerprint": selected["dataset_fingerprint"],
                "source_observation_id": selected["source_observation_id"],
                "age_seconds": (timestamp - picked_time).total_seconds(),
            })
    complete = bool(positions) and len(labels) == len(positions) and not missing
    return {
        "schema_version": "phase13-asof-regime-join.v1",
        "source_status": feed.get("status"),
        "source_sha256": feed.get("source_sha256"),
        "closed_position_count": len(positions),
        "matched_count": len(labels),
        "pit_join_contract_complete": complete,
        "matched_snapshots": labels if complete else [],
        "missing_or_rejected": sorted(set(missing)),
        "independently_verified_market_regime": False,
        "used_for_selection": False, "promotion_allowed": False,
        "execution_allowed": False, "sealed_holdout_opened": False,
    }


def phase13_v8_preparation(
    phase12: dict[str, Any] | None,
    joined: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pre-register research questions, not post-hoc winning strategies."""
    cost = phase12 if isinstance(phase12, dict) else {}
    labels = joined if isinstance(joined, dict) else {}
    validated = (
        cost.get("simulated_execution_cost_decomposition_verified") is True
        and labels.get("pit_join_contract_complete") is True
    )
    trades = cost.get("closed_positions") or []
    groups: dict[tuple[str, str, str], dict[str, float | int]] = {}
    if validated:
        for trade in trades:
            regime = trade.get("historical_regime") or {}
            if regime.get("status") != "timestamp_and_provenance_contract_consistent":
                validated = False
                break
            key = (trade["fold_id"], trade["strategy_id"], regime["regime"])
            entry = groups.setdefault(key, {
                "closed_trade_count": 0, "net_pnl": 0.0,
                "modeled_slippage_cost": 0.0, "modeled_impact_cost": 0.0,
                "modeled_half_spread_cost": 0.0, "recorded_fees": 0.0,
            })
            entry["closed_trade_count"] += 1
            entry["net_pnl"] += trade["engine_executed_net_pnl"]
            for name in ("modeled_slippage_cost", "modeled_impact_cost",
                         "modeled_half_spread_cost", "recorded_fees"):
                entry[name] += trade[name]
    if not validated:
        groups.clear()
    return {
        "schema_version": "phase13-v8-preparation.v1",
        "descriptive_regime_cost_evidence_available": validated,
        "fold_regime_summaries": [
            {"fold_id": fold, "strategy_id": strategy, "regime": regime,
             **{name: round(value, 2) if name != "closed_trade_count" else value
                for name, value in group.items()}}
            for (fold, strategy, regime), group in sorted(groups.items())
        ],
        "preregistered_research_questions": [
            "Does net return after modeled execution costs persist across independent OOS folds?",
            "Does fee and impact drag vary by independently validated entry-time market regime?",
            "Does the observed effect survive unchanged nested OOS and multiplicity controls?",
        ],
        "readiness_blockers": [
            "historical_source_not_independently_verified",
            "independent_closed_trade_ledger_unavailable",
            "broker_measured_execution_costs_unavailable",
            "strategy_v8_hypotheses_require_preregistration_before_new_trial",
        ] + ([] if validated else ["incomplete_regime_join_or_cost_evidence"]),
        "strategy_v8_ready_for_promotion": False,
        "new_strategy_evaluations_run": 0,
        "sealed_holdout_opened": False,
        "thresholds_changed": False,
        "diagnostic_only": True, "used_for_selection": False,
        "promotion_allowed": False, "execution_allowed": False,
    }
