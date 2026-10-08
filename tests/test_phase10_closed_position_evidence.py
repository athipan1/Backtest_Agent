"""Phase 10 closeout reconstruction is strictly research-only and fail-closed."""
from copy import deepcopy

from app.phase10_closed_position_evidence import phase10_closed_position_evidence


def _row(index, side, quantity, price, fees, realized, *, closed=False, round_trip=None,
         timestamp=None, fold="nested-oos-1", symbol="AAPL"):
    return {
        "fold_id": fold, "strategy_id": "candidate-a", "fill_index": index,
        "source": "BacktestRunResult.trades",
        "fill": {
            "symbol": symbol, "side": side, "quantity": quantity,
            "price": price, "fees": fees,
            "timestamp": timestamp or f"2026-01-02T{10+index:02d}:00:00Z",
            "realized_pnl": realized, "position_closed": closed,
            "round_trip_realized_pnl": round_trip,
        },
    }


def _report(records):
    return {
        "oos_fill_coverage_verified": True,
        "observed_fill_count": len(records),
        "raw_oos_fills": records,
    }


def _partial_closeouts():
    return [
        _row(0, "buy", 10, 100, 1, 0),
        _row(1, "sell", 4, 110, 0.4, 39.2),
        _row(2, "sell", 6, 90, 0.6, -61.2, closed=True, round_trip=-22),
    ]


def test_partial_sells_reconcile_engine_and_keep_cost_provenance_unverified():
    result = phase10_closed_position_evidence(_report(_partial_closeouts()))
    assert result["paired_closeout_reconciliation_verified"] is True
    assert result["closed_position_count"] == 1
    trade = result["closed_positions"][0]
    assert trade["entry_fill_indices"] == [0]
    assert trade["exit_fill_indices"] == [1, 2]
    assert trade["executed_price_gross_pnl"] == -20
    assert trade["total_fees"] == 2
    assert trade["fee_adjusted_net_pnl"] == -22
    assert result["independent_closed_trade_ledger_verified"] is False
    assert result["strategy_v8_hypothesis_ready"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_multiple_entry_fills_moving_average_basis():
    records = [
        _row(0, "buy", 2, 100, 0.2, 0),
        _row(1, "buy", 2, 110, 0.2, 0),
        _row(2, "sell", 4, 120, 0.4, 59.2, closed=True, round_trip=59.2),
    ]
    report = phase10_closed_position_evidence(_report(records))
    assert report["paired_closeout_reconciliation_verified"] is True
    assert report["closed_positions"][0]["executed_price_gross_pnl"] == 60


def test_missing_source_open_positions_and_orphan_sells_fail_closed():
    missing = phase10_closed_position_evidence(None)
    assert missing["paired_closeout_reconciliation_verified"] is False
    assert "upstream_oos_fill_coverage_unverified" in missing["error_counts"]
    open_only = phase10_closed_position_evidence(_report(_partial_closeouts()[:2]))
    assert open_only["error_counts"]["unclosed_position"] == 1
    assert open_only["paired_closeout_reconciliation_verified"] is False
    orphan = phase10_closed_position_evidence(_report([_partial_closeouts()[1]]))
    assert orphan["error_counts"]["sell_without_entry"] == 1


def test_mismatched_pnl_oversell_and_duplicate_fill_index_fail_closed():
    rows = _partial_closeouts()
    rows[1]["fill"]["realized_pnl"] = 100
    rows.append(deepcopy(rows[2]))
    report = phase10_closed_position_evidence(_report(rows))
    assert report["error_counts"]["engine_realized_pnl_mismatch"] == 1
    assert report["error_counts"]["duplicate_fill_index"] == 1
    assert report["paired_closeout_reconciliation_verified"] is False

    oversold = [_row(0, "buy", 1, 100, 0, 0),
                _row(1, "sell", 2, 110, 0, 20, closed=True, round_trip=20)]
    assert phase10_closed_position_evidence(_report(oversold))["error_counts"]["oversold_position"] == 1


def test_unverified_upstream_never_becomes_valid_from_synthetic_trade_pair():
    report = _report(_partial_closeouts())
    report["oos_fill_coverage_verified"] = False
    outcome = phase10_closed_position_evidence(report)
    assert outcome["paired_closeout_reconciliation_verified"] is False
    assert outcome["closed_position_count"] == 1


def test_naive_and_backward_time_or_bad_closure_flag_rejected():
    rows = _partial_closeouts()
    rows[1]["fill"]["timestamp"] = "2026-01-02T11:00:00"
    report = phase10_closed_position_evidence(_report(rows))
    assert report["error_counts"]["invalid_execution_fill"] == 1
    assert report["paired_closeout_reconciliation_verified"] is False
    assert report["error_counts"]["position_closed_flag_mismatch"] == 1


def test_phase10_is_nested_in_existing_phase9_research_artifact():
    from types import SimpleNamespace
    from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence

    observed = _partial_closeouts()
    fills = [item["fill"] for item in observed]
    window = SimpleNamespace(
        window=1, decision="TRADE", selected_strategy_id="candidate-a",
        test_start="2026-01-02T09:30:00Z",
        test_end="2026-01-02T16:00:00Z",
        oos_fill_evidence={"source": "BacktestRunResult.trades", "recorded": True,
                           "fills": fills},
        oos_execution_costs={"fill_count": 3, "fees_paid": 2.0},
    )
    artifact = phase9_oos_fill_evidence(SimpleNamespace(windows=[window]))
    assert artifact["oos_fill_coverage_verified"] is True
    phase10 = artifact["phase10_closed_position_evidence"]
    assert phase10["paired_closeout_reconciliation_verified"] is True
    assert phase10["closed_position_count"] == 1
    assert phase10["strategy_v8_hypothesis_ready"] is False
    assert phase10["promotion_allowed"] is False
