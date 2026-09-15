"""Diagnostic serialization only: never participates in strategy selection."""


def execution_costs(result, request):
    trades = getattr(result, "trades", None)
    return {
        "fee_bps_per_side": request.fee_bps,
        "slippage_bps_per_side": request.slippage_bps,
        "market_impact_bps": request.market_impact_bps,
        "fees_paid": round(sum(trade.fees for trade in trades), 2) if trades is not None else None,
        "fill_count": len(trades) if trades is not None else None,
        "fills_status": "recorded" if trades is not None else "not_recorded",
        "slippage_amount": None,
        "slippage_amount_status": "not_recorded_separately_in_fill_contract",
        "return_includes_costs": True,
    }


def dump(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def training_evidence(selection, request, required_gates):
    rows = []
    for item in selection.ranked_results:
        gates = item.gates
        missing = [name for name in required_gates if name not in gates]
        failed = [name for name in required_gates if gates.get(name) is not True]
        metrics = dump(item.metrics)
        statistical = dump(getattr(item, "statistical_evidence", None)) or {}
        criteria = request.selection_criteria
        values = {
            "trade_count": (metrics.get("trade_count"), criteria.min_trades, ">="),
            "annualized_return": (metrics.get("annualized_return"), criteria.min_annualized_return, ">="),
            "sharpe_ratio": (metrics.get("sharpe_ratio"), criteria.min_sharpe_ratio, ">="),
            "profit_factor": (metrics.get("profit_factor"), criteria.min_profit_factor, ">="),
            "max_drawdown": (metrics.get("max_drawdown"), criteria.max_drawdown_floor, ">="),
            "excess_return": (metrics.get("excess_return_pct"), criteria.min_excess_return, ">="),
            "kill_switch_safety": (metrics.get("kill_switch_events"), criteria.max_kill_switch_events, "<="),
            "statistical_observation_count": (statistical.get("observation_count"), request.statistical_criteria.min_observations, ">="),
            "statistical_trade_count": (statistical.get("trade_count"), request.statistical_criteria.min_trades, ">="),
        }
        rows.append({
            "strategy_id": item.strategy_id,
            "effective_parameters": getattr(item, "effective_parameters", {}),
            "metrics": dump(item.metrics),
            "execution_costs": getattr(item, "execution_costs", {}),
            "statistical_evidence": dump(getattr(item, "statistical_evidence", None)),
            "inner_required_gates": {name: gates.get(name) for name in required_gates},
            "all_diagnostic_gates": dict(gates),
            "failed_inner_gates": failed,
            "missing_gate_fields": missing,
            "rejection_category": "contract_failure" if missing else
                                  "policy_rejection" if failed else None,
            "thresholds": {
                "trade_count_min": request.selection_criteria.min_trades,
                "max_drawdown_floor": request.selection_criteria.max_drawdown_floor,
                "max_kill_switch_events": request.selection_criteria.max_kill_switch_events,
                "statistical_criteria": dump(request.statistical_criteria),
            },
            "ranking_score": item.score,
            "actual_gate_values": {name: {"observed": observed, "threshold": threshold,
                "operator": operator, "passed": gates.get(name),
                "required_for_inner_selection": name in required_gates}
                for name, (observed, threshold, operator) in values.items()},
            "sample_diagnostics": {
                "sparse_training_trades": metrics.get("trade_count", 0) < criteria.min_trades,
                "trade_shortfall": max(0, criteria.min_trades - metrics.get("trade_count", 0)),
                "observation_count": statistical.get("observation_count"),
                "effective_sample_size": statistical.get("effective_sample_size"),
                "oos_evaluated": False,
            },
        })
    return rows
