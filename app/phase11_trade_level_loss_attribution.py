"""Phase 11: descriptive trade-level fee drag and loss patterns, research only.

Recorded execution prices ALREADY contain modeled slippage and market impact.
This module neither reverse-engineers those costs nor claims market-regime
causality from aggregate OOS performance.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from typing import Any


def _money(value: Any, *, nonnegative: bool = False) -> bool:
    return type(value) in (int, float) and isfinite(value) and (
        not nonnegative or value >= 0
    )


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _regime_note(
    trade: dict[str, Any], observations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Check supplied provenance fields only, not the truth of a market regime."""
    if observations is None:
        return {"status": "not_supplied", "label": None}
    matches = [
        row for row in observations if isinstance(row, dict)
        and all(row.get(key) == trade.get(key) for key in (
            "fold_id", "strategy_id", "symbol", "entry_timestamp"
        ))
    ]
    if not matches:
        return {"status": "missing_trade_matched_observation", "label": None}
    if len(matches) != 1:
        return {"status": "ambiguous_trade_matched_observation", "label": None}
    row = matches[0]
    asof = _when(row.get("regime_asof_timestamp"))
    available = _when(row.get("regime_available_at_timestamp"))
    entry = _when(trade["entry_timestamp"])
    if (asof is None or available is None or entry is None
            or not asof <= available <= entry):
        return {"status": "unverified_or_lookahead_timestamp", "label": None}
    if (row.get("source") != "historical_point_in_time_observation"
            or not isinstance(row.get("dataset_fingerprint"), str)
            or not row["dataset_fingerprint"]
            or not isinstance(row.get("regime"), str)
            or not row["regime"]):
        return {"status": "missing_observation_provenance", "label": None}
    return {
        "status": "timestamps_and_metadata_consistent_not_independently_verified",
        "label": row["regime"],
        "source": row["source"],
        "dataset_fingerprint": row["dataset_fingerprint"],
        "regime_asof_timestamp": row["regime_asof_timestamp"],
        "regime_available_at_timestamp": row["regime_available_at_timestamp"],
    }


def phase11_trade_level_loss_attribution(
    closed_evidence: dict[str, Any] | None,
    *,
    regime_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe observed P&L/fees by trade and fold only after upstream reconciliation.

    The optional regime feed requires explicit trade-matched, publication-time
    provenance; passing its schema checks does not prove historical correctness.
    """
    upstream = closed_evidence if isinstance(closed_evidence, dict) else {}
    closed = upstream.get("closed_positions")
    rows = closed if isinstance(closed, list) else []
    errors: list[str] = []
    if upstream.get("paired_closeout_reconciliation_verified") is not True:
        errors.append("upstream_closeout_reconciliation_unverified")
    if not rows or upstream.get("closed_position_count") != len(rows):
        errors.append("missing_or_inconsistent_closed_position_count")
    if regime_observations is not None and not isinstance(regime_observations, list):
        errors.append("invalid_regime_observation_collection")

    items: list[dict[str, Any]] = []
    for index, position in enumerate(rows):
        if not isinstance(position, dict):
            errors.append(f"invalid_closed_position:{index}")
            continue
        gross = position.get("executed_price_gross_pnl")
        fees = position.get("total_fees")
        net = position.get("fee_adjusted_net_pnl")
        engine_net = position.get("engine_realized_net_pnl")
        qty = position.get("closed_quantity")
        entry = _when(position.get("entry_timestamp"))
        exit_ = _when(position.get("exit_timestamp"))
        identity = (position.get("fold_id"), position.get("strategy_id"),
                    position.get("symbol"))
        if (any(not isinstance(key, str) or not key for key in identity)
                or entry is None or exit_ is None or entry > exit_
                or not _money(gross) or not _money(fees, nonnegative=True)
                or not _money(net) or not _money(engine_net)
                or not _money(qty) or qty <= 0):
            errors.append(f"invalid_closed_position_fields:{index}")
            continue
        if (abs(gross - fees - net) > 0.021
                or abs(net - engine_net) > 0.03 + qty * 0.00006):
            errors.append(f"pnl_or_fee_reconciliation_failed:{index}")
            continue
        if net < -0.005:
            pattern = ("fee_drag_flipped_nonnegative_executed_gross_to_loss"
                       if gross >= -0.005 else "negative_executed_gross_plus_fee_drag")
        elif net > 0.005:
            pattern = "positive_after_recorded_fees"
        else:
            pattern = "approximately_breakeven_after_recorded_fees"
        exit_reasons = position.get("reported_exit_reasons")
        if (exit_reasons is not None
                and (not isinstance(exit_reasons, list)
                     or any(not isinstance(x, str) for x in exit_reasons))):
            errors.append(f"invalid_exit_reason_evidence:{index}")
            continue
        items.append({
            "fold_id": identity[0],
            "strategy_id": identity[1],
            "symbol": identity[2],
            "entry_timestamp": position["entry_timestamp"],
            "exit_timestamp": position["exit_timestamp"],
            "closed_quantity": qty,
            "executed_price_gross_pnl": gross,
            "recorded_fees": fees,
            "fee_adjusted_net_pnl": net,
            "observed_loss_pattern": pattern,
            "reported_exit_reasons": exit_reasons,
            "exit_reason_provenance": "simulated_fill_reason" if exit_reasons else "unavailable",
            "market_regime_evidence": _regime_note(
                position,
                regime_observations if isinstance(regime_observations, list) else None,
            ),
            "separate_slippage_amount": None,
            "separate_market_impact_amount": None,
            "root_cause_confirmed": False,
        })

    valid = not errors and len(items) == len(rows)
    if not valid:
        # No partial observations may be displayed as aggregate research truth.
        items = []

    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "trade_count": 0, "loss_count": 0, "win_count": 0,
        "fee_flipped_loss_count": 0, "executed_gross_pnl": 0.0,
        "recorded_fees": 0.0, "fee_adjusted_net_pnl": 0.0,
    })
    for item in items:
        key = (item["fold_id"], item["strategy_id"])
        group = groups[key]
        group["trade_count"] += 1
        group["loss_count"] += int(item["fee_adjusted_net_pnl"] < -0.005)
        group["win_count"] += int(item["fee_adjusted_net_pnl"] > 0.005)
        group["fee_flipped_loss_count"] += int(
            item["observed_loss_pattern"]
            == "fee_drag_flipped_nonnegative_executed_gross_to_loss"
        )
        group["executed_gross_pnl"] += item["executed_price_gross_pnl"]
        group["recorded_fees"] += item["recorded_fees"]
        group["fee_adjusted_net_pnl"] += item["fee_adjusted_net_pnl"]
    fold_summaries = [{
        "fold_id": fold, "strategy_id": strategy,
        **{key: round(val, 2) if key in (
            "executed_gross_pnl", "recorded_fees", "fee_adjusted_net_pnl"
        ) else val for key, val in group.items()},
    } for (fold, strategy), group in sorted(groups.items())]
    regime_consistent = bool(items) and all(
        item["market_regime_evidence"]["status"]
        == "timestamps_and_metadata_consistent_not_independently_verified"
        for item in items
    )
    return {
        "schema_version": "phase11-trade-level-loss-attribution.v1",
        "observed_fee_and_loss_accounting_verified": valid,
        "attributed_trade_count": len(items),
        "trades": items,
        "fold_strategy_summaries": fold_summaries,
        "error_codes": sorted(errors),
        "regime_observation_metadata_consistent": regime_consistent,
        "point_in_time_regime_independently_verified": False,
        "separate_slippage_and_impact_verified": False,
        "trade_level_causal_attribution_verified": False,
        "missing_required_evidence": [
            "independently_verified_point_in_time_regime_feed",
            "separately_measured_slippage_and_market_impact_amounts",
            "independent_closed_trade_ledger_reconciliation",
        ],
        "strategy_v8_hypothesis_ready": False,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
