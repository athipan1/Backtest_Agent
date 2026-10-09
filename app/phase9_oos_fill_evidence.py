"""Research-only provenance and integrity checks for actual nested OOS simulation fills.

Fills are not closed trades. Do not infer entry-to-exit P&L, point-in-time market
regimes, separate slippage costs, or promotion authority from this evidence.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
from typing import Any

from app.phase10_closed_position_evidence import phase10_closed_position_evidence
from app.phase11_trade_level_loss_attribution import phase11_trade_level_loss_attribution
from app.phase12_execution_cost_regime_evidence import phase12_execution_cost_regime_evidence
from app.phase14_historical_regime_validation import phase14_historical_regime_validation
from app.phase15_independent_evidence import phase15_v8_evidence_validation
from app.phase13_historical_regime import (
    bind_regime_at_entry,
    phase13_v8_preparation,
)


def _aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _finite_number(value: Any, *, strictly_positive: bool = False) -> bool:
    return (
        type(value) in (int, float)
        and isfinite(value)
        and (value > 0 if strictly_positive else value >= 0)
    )


def phase9_oos_fill_evidence(
    nested: Any, *, historical_regime_source: dict[str, Any] | None = None,
    phase15_documents: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export observed OOS fills without rerunning or influencing the backtest."""
    windows = getattr(nested, "windows", None)
    if not isinstance(windows, list):
        windows = []

    records: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    errors: Counter[str] = Counter()
    seen_folds: set[str] = set()
    trade_windows = 0
    abstention_windows = 0

    for window in windows:
        ordinal = getattr(window, "window", None)
        fold_id = f"nested-oos-{ordinal}" if type(ordinal) is int and ordinal > 0 else None
        start_text = getattr(window, "test_start", None)
        end_text = getattr(window, "test_end", None)
        start, end = _aware_time(start_text), _aware_time(end_text)
        strategy_id = getattr(window, "selected_strategy_id", None)
        decision = getattr(window, "decision", None)
        fold_errors: set[str] = set()
        if fold_id is None or fold_id in seen_folds:
            fold_errors.add("invalid_or_duplicate_fold_id")
        if fold_id is not None:
            seen_folds.add(fold_id)
        if start is None or end is None or start >= end:
            fold_errors.add("missing_or_invalid_oos_boundaries")

        if decision == "NO_TRADE":
            abstention_windows += 1
            abstention_evidence = getattr(window, "oos_fill_evidence", None) or {}
            if isinstance(abstention_evidence, dict) and abstention_evidence.get("fills"):
                fold_errors.add("abstention_has_fill_payload")
            if strategy_id is not None:
                fold_errors.add("abstention_has_selected_strategy")
            fold_rows.append({
                "fold_id": fold_id, "decision": decision,
                "selected_strategy_id": strategy_id,
                "oos_start": start_text, "oos_end": end_text,
                "status": "cash_abstention",
                "observed_fill_count": 0,
                "errors": sorted(fold_errors),
            })
        elif decision == "TRADE":
            trade_windows += 1
            evidence = getattr(window, "oos_fill_evidence", None) or {}
            raw = evidence.get("fills") if isinstance(evidence, dict) else None
            available = (
                isinstance(evidence, dict)
                and evidence.get("source") == "BacktestRunResult.trades"
                and evidence.get("recorded") is True
                and isinstance(raw, list)
            )
            if not available:
                fold_errors.add("oos_fill_source_unavailable")
            if not strategy_id:
                fold_errors.add("missing_selected_strategy_id")
            fills = raw if available else []
            costs = getattr(window, "oos_execution_costs", None) or {}
            expected_count = costs.get("fill_count") if isinstance(costs, dict) else None
            expected_fees = costs.get("fees_paid") if isinstance(costs, dict) else None
            if type(expected_count) is not int or expected_count != len(fills):
                fold_errors.add("oos_fill_count_mismatch")
            fees_total = 0.0
            for index, fill in enumerate(fills):
                if not isinstance(fill, dict):
                    fold_errors.add("invalid_fill_payload")
                    continue
                timestamp = _aware_time(fill.get("timestamp"))
                if timestamp is None or start is None or end is None or not start <= timestamp <= end:
                    fold_errors.add("fill_outside_oos_window_or_naive_timestamp")
                if fill.get("side") not in ("buy", "sell"):
                    fold_errors.add("invalid_fill_side")
                if not _finite_number(fill.get("quantity"), strictly_positive=True):
                    fold_errors.add("invalid_fill_quantity")
                if not _finite_number(fill.get("price"), strictly_positive=True):
                    fold_errors.add("invalid_fill_price")
                if not _finite_number(fill.get("fees")):
                    fold_errors.add("invalid_fill_fees")
                else:
                    fees_total += fill["fees"]
                records.append({
                    "fold_id": fold_id,
                    "strategy_id": strategy_id,
                    "fill_index": index,
                    "source": "BacktestRunResult.trades",
                    "fill": dict(fill),
                })
            if not _finite_number(expected_fees) or abs(fees_total - expected_fees) > 0.011:
                fold_errors.add("oos_fees_reconciliation_failed")
            fold_rows.append({
                "fold_id": fold_id, "decision": decision,
                "selected_strategy_id": strategy_id,
                "oos_start": start_text, "oos_end": end_text,
                "status": "recorded" if available else "unavailable",
                "observed_fill_count": len(fills),
                "errors": sorted(fold_errors),
            })
        else:
            fold_errors.add("unknown_fold_decision")
            fold_rows.append({
                "fold_id": fold_id, "decision": decision,
                "selected_strategy_id": strategy_id,
                "oos_start": start_text, "oos_end": end_text,
                "status": "unverifiable",
                "observed_fill_count": 0,
                "errors": sorted(fold_errors),
            })
        for name in fold_errors:
            errors[name] += 1

    if not windows:
        errors["nested_oos_evidence_unavailable"] += 1
    if trade_windows and not records:
        errors["no_observed_oos_fills"] += 1
    verified = bool(windows) and trade_windows > 0 and bool(records) and not errors
    evidence = {
        "schema_version": "phase9-oos-fill-evidence.v1",
        "source": "nested_v4_actual_oos_BacktestRunResult.trades",
        "fold_count": len(fold_rows),
        "trade_windows": trade_windows,
        "cash_abstention_windows": abstention_windows,
        "observed_fill_count": len(records),
        "oos_fill_coverage_verified": verified,
        "folds": fold_rows,
        "raw_oos_fills": records,
        "error_counts": dict(sorted(errors.items())),
        "closed_trade_ledger_available": False,
        "gross_net_cost_decomposition_verified": False,
        "point_in_time_regime_verified": False,
        "trade_level_causality_verified": False,
        "missing_required_evidence": [
            "paired_closed_trade_ledger",
            "separately_measured_slippage_and_impact_amounts",
            "point_in_time_market_regime_provenance",
        ],
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
    phase10 = phase10_closed_position_evidence(evidence)
    evidence["phase10_closed_position_evidence"] = phase10
    joined = bind_regime_at_entry(phase10, historical_regime_source)
    matched = joined["matched_snapshots"] if joined["pit_join_contract_complete"] else None
    evidence["phase11_trade_level_loss_attribution"] = phase11_trade_level_loss_attribution(
        phase10, regime_observations=matched
    )
    phase12 = phase12_execution_cost_regime_evidence(
        evidence, phase10, regime_snapshots=matched
    )
    evidence["phase12_execution_cost_regime_evidence"] = phase12
    evidence["phase13_historical_regime_evidence"] = joined
    evidence["phase13_strategy_research_v8_preparation"] = phase13_v8_preparation(
        phase12, joined
    )
    phase14 = phase14_historical_regime_validation(
        evidence, phase12, joined, historical_regime_source
    )
    evidence["phase14_historical_regime_validation"] = phase14
    evidence["phase15_independent_evidence"] = phase15_v8_evidence_validation(
        evidence, joined, phase14, historical_regime_source, phase15_documents
    )
    return evidence
