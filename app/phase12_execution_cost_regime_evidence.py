"""Phase 12: replay the execution model's recorded cost assumptions.

All amounts are simulated model costs, NOT measured broker slippage or market
impact. Market-regime snapshots are optional and never synthesized from folds.
No promotion, execution, strategy selection or sealed-holdout authority.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from typing import Any


def _finite(value: Any, *, positive: bool = False) -> bool:
    return type(value) in (int, float) and isfinite(value) and (
        value > 0 if positive else value >= 0
    )


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.utcoffset() is not None:
            return value
    except ValueError:
        pass
    return None


def _regime_at_entry(
    position: dict[str, Any], snapshots: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate source and availability metadata, never infer a regime label."""
    if snapshots is None:
        return {"status": "historical_regime_source_not_connected", "regime": None}
    matches = [
        s for s in snapshots if isinstance(s, dict)
        and all(s.get(k) == position.get(k) for k in (
            "fold_id", "strategy_id", "symbol", "entry_timestamp"
        ))
    ]
    if not matches:
        return {"status": "no_matching_point_in_time_snapshot", "regime": None}
    if len(matches) != 1:
        return {"status": "ambiguous_snapshot_identity", "regime": None}
    s = matches[0]
    entry, asof, available = (
        _utc(position.get("entry_timestamp")),
        _utc(s.get("regime_asof_timestamp")),
        _utc(s.get("regime_available_at_timestamp")),
    )
    if entry is None or asof is None or available is None or not asof <= available <= entry:
        return {"status": "lookahead_or_invalid_snapshot_availability", "regime": None}
    if (s.get("source") != "historical_point_in_time_observation"
            or not isinstance(s.get("dataset_fingerprint"), str)
            or not s["dataset_fingerprint"]
            or not isinstance(s.get("regime"), str) or not s["regime"]):
        return {"status": "missing_historical_source_provenance", "regime": None}
    return {
        "status": "timestamp_and_provenance_contract_consistent",
        "regime": s["regime"],
        "dataset_fingerprint": s["dataset_fingerprint"],
        "regime_asof_timestamp": s["regime_asof_timestamp"],
        "regime_available_at_timestamp": s["regime_available_at_timestamp"],
        "historical_source_independently_audited": False,
    }


def phase12_execution_cost_regime_evidence(
    fill_evidence: dict[str, Any] | None,
    closed_evidence: dict[str, Any] | None,
    *,
    regime_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate decomposition at original fill time, roll up closed positions.

    The ideal reference-price round-trip P&L minus recorded fees and the three
    modeled price penalties must reconcile with Phase 10 executed-price net P&L.
    Cost components are diagnostics and MUST NOT change BacktestRunResult.
    """
    fills_report = fill_evidence if isinstance(fill_evidence, dict) else {}
    closed_report = closed_evidence if isinstance(closed_evidence, dict) else {}
    errors: list[str] = []
    if fills_report.get("oos_fill_coverage_verified") is not True:
        errors.append("oos_fill_coverage_not_verified")
    if closed_report.get("paired_closeout_reconciliation_verified") is not True:
        errors.append("closed_position_reconciliation_not_verified")
    if regime_snapshots is not None and not isinstance(regime_snapshots, list):
        errors.append("invalid_regime_snapshots_collection")
        regime_snapshots = None

    raw = fills_report.get("raw_oos_fills")
    fills = raw if isinstance(raw, list) else []
    positions = closed_report.get("closed_positions")
    positions = positions if isinstance(positions, list) else []
    if (not fills or fills_report.get("observed_fill_count") != len(fills)
            or not positions
            or closed_report.get("closed_position_count") != len(positions)):
        errors.append("missing_or_inconsistent_upstream_records")

    fill_by_id: dict[tuple[str, int], dict[str, Any]] = {}
    cost_by_id: dict[tuple[str, int], dict[str, Any]] = {}
    for number, record in enumerate(fills):
        if not isinstance(record, dict):
            errors.append(f"invalid_fill_record:{number}")
            continue
        fid, idx = record.get("fold_id"), record.get("fill_index")
        key = (fid, idx)
        if (not isinstance(fid, str) or not fid or type(idx) is not int or idx < 0
                or key in fill_by_id or record.get("source") != "BacktestRunResult.trades"):
            errors.append(f"invalid_or_duplicate_fill_identity:{number}")
            continue
        fill_by_id[key] = record
        fill = record.get("fill")
        if not isinstance(fill, dict):
            errors.append(f"invalid_fill_payload:{number}")
            continue
        qty, price, reference = (
            fill.get("quantity"), fill.get("price"),
            fill.get("execution_reference_price")
        )
        slip, impact, spread, fee = (
            fill.get("modeled_slippage_bps"), fill.get("market_impact_bps"),
            fill.get("modeled_half_spread_bps"), fill.get("fees")
        )
        if (fill.get("side") not in ("buy", "sell") or _utc(fill.get("timestamp")) is None
                or not _finite(qty, positive=True)
                or not _finite(price, positive=True)
                or not _finite(reference, positive=True)
                or any(not _finite(value) for value in (slip, impact, spread, fee))):
            errors.append(f"cost_source_fields_unavailable_or_invalid:{number}")
            continue
        # Execution price and all simulated components originate from the
        # same reference. Quantization of execution prices to 4 decimals is
        # a known serialization residual, not independent measured slippage.
        direction = 1 if fill["side"] == "buy" else -1
        actual_price_penalty = direction * (price - reference) * qty
        simulated = {
            "modeled_slippage_cost": reference * qty * slip / 10000.0,
            "modeled_impact_cost": reference * qty * impact / 10000.0,
            "modeled_half_spread_cost": reference * qty * spread / 10000.0,
            "recorded_fees": fee,
        }
        model_price_penalty = sum(
            simulated[k] for k in (
                "modeled_slippage_cost", "modeled_impact_cost",
                "modeled_half_spread_cost"
            )
        )
        tolerance = 0.000052 * qty + 1e-6
        if abs(actual_price_penalty - model_price_penalty) > tolerance:
            errors.append(f"execution_model_price_reconciliation_failed:{number}")
            continue
        cost_by_id[key] = {
            "fold_id": fid, "strategy_id": record.get("strategy_id"),
            "symbol": fill.get("symbol"), "fill_index": idx,
            "side": fill["side"], "quantity": qty,
            "execution_reference_price": reference, "executed_price": price,
            "modeled_price_penalty": round(model_price_penalty, 6),
            "rounding_residual": round(actual_price_penalty - model_price_penalty, 6),
            **{k: round(v, 6) for k, v in simulated.items()},
        }

    used: set[tuple[str, int]] = set()
    ledger: list[dict[str, Any]] = []
    for number, position in enumerate(positions):
        if not isinstance(position, dict):
            errors.append(f"invalid_closed_position:{number}")
            continue
        fold = position.get("fold_id")
        entries, exits = position.get("entry_fill_indices"), position.get("exit_fill_indices")
        if (not isinstance(fold, str) or not fold
                or not isinstance(entries, list) or not entries
                or not isinstance(exits, list) or not exits):
            errors.append(f"missing_closeout_fill_links:{number}")
            continue
        selected = []
        for side, indices in (("buy", entries), ("sell", exits)):
            for index in indices:
                key = (fold, index)
                if type(index) is not int or key in used or key not in cost_by_id:
                    errors.append(f"missing_reused_or_invalid_fill_link:{number}")
                    continue
                record, cost = fill_by_id[key], cost_by_id[key]
                fill = record["fill"]
                if (fill["side"] != side or record.get("strategy_id") != position.get("strategy_id")
                        or fill.get("symbol", "").upper() != position.get("symbol")):
                    errors.append(f"closed_position_fill_identity_mismatch:{number}")
                    continue
                used.add(key)
                selected.append(cost)
        if len(selected) != len(entries) + len(exits):
            continue
        components = {
            name: sum(item[name] for item in selected)
            for name in (
                "modeled_slippage_cost", "modeled_impact_cost",
                "modeled_half_spread_cost", "recorded_fees"
            )
        }
        baseline = sum(
            (1 if item["side"] == "sell" else -1)
            * item["execution_reference_price"] * item["quantity"]
            for item in selected
        )
        # Reference-basis P&L is hypothetical, not actual realized P&L.
        implied_net = baseline - sum(components.values())
        net = position.get("fee_adjusted_net_pnl")
        qty = position.get("closed_quantity")
        if (not _finite(net) or not _finite(qty, positive=True)
                or abs(implied_net - net) > 0.04 + qty * 0.00006):
            errors.append(f"closed_trade_cost_decomposition_mismatch:{number}")
            continue
        entry_qty = sum(item["quantity"] for item in selected if item["side"] == "buy")
        exit_qty = sum(item["quantity"] for item in selected if item["side"] == "sell")
        if abs(entry_qty - exit_qty) > 1e-9 or abs(exit_qty - qty) > 1e-9:
            errors.append(f"closed_trade_fill_quantities_mismatch:{number}")
            continue
        ledger.append({
            "fold_id": fold, "strategy_id": position["strategy_id"],
            "symbol": position["symbol"], "entry_timestamp": position["entry_timestamp"],
            "closed_quantity": qty,
            "reference_price_gross_pnl": round(baseline, 2),
            **{k: round(v, 2) for k, v in components.items()},
            "reference_basis_implied_net_pnl": round(implied_net, 2),
            "engine_executed_net_pnl": net,
            "historical_regime": _regime_at_entry(position, regime_snapshots),
            "cost_amounts_are_modeled_not_broker_measured": True,
        })

    valid = not errors and len(ledger) == len(positions)
    if not valid:
        ledger = []
    fold_groups: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {
        "modeled_slippage_cost": 0.0, "modeled_impact_cost": 0.0,
        "modeled_half_spread_cost": 0.0, "recorded_fees": 0.0,
        "engine_executed_net_pnl": 0.0,
    })
    for trade in ledger:
        group = fold_groups[(trade["fold_id"], trade["strategy_id"])]
        for k in group:
            group[k] += trade[k]
    return {
        "schema_version": "phase12-execution-cost-regime-evidence.v1",
        "simulated_execution_cost_decomposition_verified": valid,
        "attributed_closed_position_count": len(ledger),
        "closed_positions": ledger,
        "fold_strategy_totals": [
            {"fold_id": fid, "strategy_id": strategy,
             **{k: round(v, 2) for k, v in amounts.items()}}
            for (fid, strategy), amounts in sorted(fold_groups.items())
        ],
        "error_codes": sorted(errors),
        "historical_regime_snapshot_count": (
            len(regime_snapshots) if regime_snapshots is not None else 0
        ),
        "historical_regime_feed_connected": regime_snapshots is not None,
        "historical_regime_independently_verified": False,
        "broker_measured_slippage_or_impact": False,
        "trade_level_causality_verified": False,
        "strategy_v8_hypothesis_ready": False,
        "missing_required_evidence": [
            "independently_verifiable_point_in_time_regime_snapshots",
            "broker_measured_execution_costs",
            "independent_closed_trade_ledger",
        ],
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
