"""Phase 8 evidence-coverage audit; never infers trade-level causality from fold aggregates."""
from __future__ import annotations

from typing import Any


def phase8_evidence_coverage(phase7: dict[str, Any]) -> dict[str, Any]:
    """Inventory observable fold failures and explicitly missing causal evidence."""
    folds = phase7.get("fold_rows") or []
    records: list[dict[str, Any]] = []
    for fold in folds:
        flags = fold.get("observed_flags") or []
        records.append({
            "window": fold.get("window"),
            "strategy_id": fold.get("selected_strategy_id"),
            "observed_flags": list(flags),
            "trade_level_data_available": False,
            "gross_pnl_available": False,
            "net_pnl_available": False,
            "fee_slippage_breakdown_available": False,
            "market_regime_label_available": False,
            "entry_exit_timestamps_available": False,
            "position_size_history_available": False,
            "root_cause_confirmed": False,
        })
    return {
        "schema_version": "phase8-evidence-coverage.v1",
        "fold_count": len(records),
        "fold_evidence": records,
        "missing_required_evidence": [
            "per_trade_entry_exit_timestamps",
            "per_trade_gross_and_net_pnl",
            "per_trade_fees_slippage_and_impact",
            "per_trade_position_size",
            "point_in_time_market_regime_labels",
        ],
        "research_next_step": "Collect timestamp-aligned, point-in-time trade ledger and cost decomposition in existing research pipeline before proposing preregistered v8 hypotheses.",
        "causal_conclusions_supported": False,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
