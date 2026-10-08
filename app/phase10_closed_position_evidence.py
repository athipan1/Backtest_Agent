"""Phase 10: reconstruct simulated OOS closed positions from observed fills only.

This is diagnostic evidence, not the independent closed trade ledger required
for strategy promotion. Executed prices already embed slippage and impact.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
from typing import Any


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _number(value: Any, *, positive: bool = False) -> bool:
    return type(value) in (int, float) and isfinite(value) and (
        value > 0 if positive else value >= 0
    )


def phase10_closed_position_evidence(fill_report: dict[str, Any] | None) -> dict[str, Any]:
    """Reconcile long-only fill closeouts with engine reported realized P&L.

    One position can contain many partial exit fills. The moving-average book
    matches the current engine cost-basis convention; it is not an independent
    fee/slippage/market-impact measurement.
    """
    report = fill_report if isinstance(fill_report, dict) else {}
    raw = report.get("raw_oos_fills")
    records = raw if isinstance(raw, list) else []
    errors: Counter[str] = Counter()
    if report.get("oos_fill_coverage_verified") is not True:
        errors["upstream_oos_fill_coverage_unverified"] += 1
    if not records:
        errors["no_observed_fills"] += 1
    if report.get("observed_fill_count") != len(records):
        errors["observed_fill_count_mismatch"] += 1

    positions: dict[tuple[str, str, str], dict[str, Any]] = {}
    last_times: dict[tuple[str, str, str], datetime] = {}
    seen_indices: set[tuple[str, int]] = set()
    completed: list[dict[str, Any]] = []

    for row in records:
        if not isinstance(row, dict):
            errors["invalid_fill_record"] += 1
            continue
        fold_id, strategy_id, index = (
            row.get("fold_id"), row.get("strategy_id"), row.get("fill_index")
        )
        fill = row.get("fill")
        if (not isinstance(fold_id, str) or not fold_id
                or not isinstance(strategy_id, str) or not strategy_id
                or type(index) is not int or index < 0
                or row.get("source") != "BacktestRunResult.trades"
                or not isinstance(fill, dict)):
            errors["invalid_fill_provenance"] += 1
            continue
        index_key = (fold_id, index)
        if index_key in seen_indices:
            errors["duplicate_fill_index"] += 1
            continue
        seen_indices.add(index_key)

        symbol = fill.get("symbol")
        side = fill.get("side")
        stamp = _aware(fill.get("timestamp"))
        qty, price, fees = fill.get("quantity"), fill.get("price"), fill.get("fees")
        if (not isinstance(symbol, str) or not symbol
                or side not in ("buy", "sell") or stamp is None
                or not _number(qty, positive=True)
                or not _number(price, positive=True) or not _number(fees)):
            errors["invalid_execution_fill"] += 1
            continue
        if not _number(fill.get("realized_pnl")) and not (
            type(fill.get("realized_pnl")) in (int, float)
            and isfinite(fill["realized_pnl"])
        ):
            errors["missing_or_invalid_realized_pnl"] += 1
            continue

        key = (fold_id, strategy_id, symbol.upper())
        previous = last_times.get(key)
        if previous is not None and stamp < previous:
            errors["non_monotonic_fill_timestamp"] += 1
        last_times[key] = stamp
        position = positions.get(key)

        if side == "buy":
            if abs(fill["realized_pnl"]) > 0.011:
                errors["buy_has_realized_pnl"] += 1
            if position is None:
                position = {
                    "open_qty": 0.0, "open_cost": 0.0, "open_entry_fees": 0.0,
                    "entry_timestamp": fill["timestamp"], "entry_fill_indices": [],
                    "exit_fill_indices": [], "gross_pnl": 0.0, "fees": 0.0,
                    "net_pnl": 0.0, "engine_net_pnl": 0.0,
                    "closed_quantity": 0.0, "max_open_quantity": 0.0,
                }
                positions[key] = position
            position["open_qty"] += qty
            position["open_cost"] += qty * price
            position["open_entry_fees"] += fees
            position["fees"] += fees
            position["entry_fill_indices"].append(index)
            position["max_open_quantity"] = max(
                position["max_open_quantity"], position["open_qty"]
            )
            continue

        if position is None or position["open_qty"] <= 1e-9:
            errors["sell_without_entry"] += 1
            continue
        if qty > position["open_qty"] + 1e-9:
            errors["oversold_position"] += 1
            continue
        ratio = min(1.0, qty / position["open_qty"])
        attributed_cost = position["open_cost"] * ratio
        attributed_fees = position["open_entry_fees"] * ratio
        gross = qty * price - attributed_cost
        net = gross - attributed_fees - fees
        # Engine stores executed prices at 4 decimals, and rounds realized
        # P&L/fees to cents. Scale tolerance only by recorded fill quantity.
        tolerance = 0.03 + qty * 0.00006
        if abs(net - fill["realized_pnl"]) > tolerance:
            errors["engine_realized_pnl_mismatch"] += 1

        position["gross_pnl"] += gross
        position["net_pnl"] += net
        position["engine_net_pnl"] += fill["realized_pnl"]
        position["fees"] += fees
        position["closed_quantity"] += qty
        position["exit_fill_indices"].append(index)
        position["open_qty"] -= qty
        position["open_cost"] -= attributed_cost
        position["open_entry_fees"] -= attributed_fees
        closed = position["open_qty"] <= 1e-9
        if type(fill.get("position_closed")) is not bool or fill["position_closed"] != closed:
            errors["position_closed_flag_mismatch"] += 1
        if not closed:
            continue
        engine_round_trip = fill.get("round_trip_realized_pnl")
        if type(engine_round_trip) not in (int, float) or not isfinite(engine_round_trip):
            errors["round_trip_realized_pnl_unavailable"] += 1
        elif abs(engine_round_trip - position["engine_net_pnl"]) > 0.015:
            errors["round_trip_realized_pnl_mismatch"] += 1
        if abs(position["net_pnl"] - position["engine_net_pnl"]) > (
            0.03 * len(position["exit_fill_indices"])
            + position["closed_quantity"] * 0.00006
        ):
            errors["closed_position_net_pnl_mismatch"] += 1
        completed.append({
            "fold_id": fold_id,
            "strategy_id": strategy_id,
            "symbol": key[2],
            "entry_timestamp": position["entry_timestamp"],
            "exit_timestamp": fill["timestamp"],
            "entry_fill_indices": list(position["entry_fill_indices"]),
            "exit_fill_indices": list(position["exit_fill_indices"]),
            "closed_quantity": position["closed_quantity"],
            "max_open_quantity": position["max_open_quantity"],
            "executed_price_gross_pnl": round(position["gross_pnl"], 2),
            "total_fees": round(position["fees"], 2),
            "fee_adjusted_net_pnl": round(position["net_pnl"], 2),
            "engine_realized_net_pnl": round(position["engine_net_pnl"], 2),
            "cost_basis": "moving_average_executed_fill_price",
            "execution_price_embeds_slippage_and_market_impact": True,
            "slippage_amount": None,
            "market_impact_amount": None,
            "point_in_time_market_regime": None,
        })
        del positions[key]

    open_positions = [{
        "fold_id": key[0], "strategy_id": key[1], "symbol": key[2],
        "remaining_quantity": round(state["open_qty"], 10),
        "entry_fill_indices": list(state["entry_fill_indices"]),
    } for key, state in sorted(positions.items()) if state["open_qty"] > 1e-9]
    if open_positions:
        errors["unclosed_position"] += len(open_positions)
    if not completed:
        errors["no_closed_positions"] += 1

    verified = (
        report.get("oos_fill_coverage_verified") is True
        and bool(completed) and not errors
    )
    return {
        "schema_version": "phase10-closed-position-evidence.v1",
        "source": "phase9_actual_nested_oos_simulated_fills",
        "observed_fill_count": len(records),
        "closed_position_count": len(completed),
        "closed_positions": completed,
        "open_positions": open_positions,
        "paired_closeout_reconciliation_verified": verified,
        "error_counts": dict(sorted(errors.items())),
        "independent_closed_trade_ledger_verified": False,
        "separate_slippage_and_impact_verified": False,
        "point_in_time_regime_verified": False,
        "trade_level_causality_verified": False,
        "strategy_v8_hypothesis_ready": False,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
