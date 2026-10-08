"""Phase 12 cost decomposition is modeled research evidence, never broker fills."""
from copy import deepcopy
from types import SimpleNamespace

from app.phase12_execution_cost_regime_evidence import phase12_execution_cost_regime_evidence
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


def _data():
    raw = [
        {"fold_id": "nested-oos-1", "strategy_id": "sma", "fill_index": 0,
         "source": "BacktestRunResult.trades",
         "fill": {
             "symbol": "AAPL", "side": "buy", "quantity": 2, "price": 100.15,
             "execution_reference_price": 100, "modeled_slippage_bps": 10,
             "market_impact_bps": 5, "modeled_half_spread_bps": 0,
             "fees": 0.1, "timestamp": "2026-01-02T10:00:00Z",
             "realized_pnl": 0, "position_closed": False,
             "reason": "sma",
         }},
        {"fold_id": "nested-oos-1", "strategy_id": "sma", "fill_index": 1,
         "source": "BacktestRunResult.trades",
         "fill": {
             "symbol": "AAPL", "side": "sell", "quantity": 2, "price": 109.78,
             "execution_reference_price": 110, "modeled_slippage_bps": 10,
             "market_impact_bps": 10, "modeled_half_spread_bps": 0,
             "fees": 0.1, "timestamp": "2026-01-02T15:00:00Z",
             "realized_pnl": 19.06, "position_closed": True,
             "round_trip_realized_pnl": 19.06, "reason": "take_profit",
         }},
    ]
    closed = [{
        "fold_id": "nested-oos-1", "strategy_id": "sma", "symbol": "AAPL",
        "entry_timestamp": "2026-01-02T10:00:00Z",
        "exit_timestamp": "2026-01-02T15:00:00Z",
        "entry_fill_indices": [0], "exit_fill_indices": [1],
        "closed_quantity": 2, "fee_adjusted_net_pnl": 19.06,
    }]
    return (
        {"oos_fill_coverage_verified": True, "raw_oos_fills": raw,
         "observed_fill_count": 2},
        {"paired_closeout_reconciliation_verified": True,
         "closed_positions": closed, "closed_position_count": 1},
    )


def _snapshot(**kwargs):
    row = {
        "fold_id": "nested-oos-1", "strategy_id": "sma", "symbol": "AAPL",
        "entry_timestamp": "2026-01-02T10:00:00Z",
        "regime": "BULL",
        "regime_asof_timestamp": "2026-01-02T09:30:00Z",
        "regime_available_at_timestamp": "2026-01-02T09:40:00Z",
        "source": "historical_point_in_time_observation",
        "dataset_fingerprint": "sha256:fixture",
    }
    row.update(kwargs)
    return row


def test_reference_price_model_costs_and_fee_adjusted_net_reconcile():
    output = phase12_execution_cost_regime_evidence(*_data())
    assert output["simulated_execution_cost_decomposition_verified"] is True
    assert output["attributed_closed_position_count"] == 1
    one = output["closed_positions"][0]
    assert one["reference_price_gross_pnl"] == 20
    assert one["modeled_slippage_cost"] == 0.42
    assert one["modeled_impact_cost"] == 0.32
    assert one["recorded_fees"] == 0.2
    assert one["reference_basis_implied_net_pnl"] == 19.06
    assert one["engine_executed_net_pnl"] == 19.06
    assert one["historical_regime"]["status"] == "historical_regime_source_not_connected"
    assert output["broker_measured_slippage_or_impact"] is False
    assert output["historical_regime_independently_verified"] is False
    assert output["trade_level_causality_verified"] is False
    assert output["strategy_v8_hypothesis_ready"] is False
    assert output["execution_allowed"] is False
    assert output["sealed_holdout_opened"] is False


def test_missing_model_source_fails_closed_not_inferred_from_executed_price():
    fills, closed = _data()
    fills["raw_oos_fills"][0]["fill"].pop("execution_reference_price")
    result = phase12_execution_cost_regime_evidence(fills, closed)
    assert not result["simulated_execution_cost_decomposition_verified"]
    assert any("cost_source_fields_unavailable" in e for e in result["error_codes"])
    assert result["closed_positions"] == []
    assert result["fold_strategy_totals"] == []


def test_modified_price_and_missing_bps_are_detected():
    fills, closed = _data()
    fills["raw_oos_fills"][0]["fill"]["price"] = 100.6
    report = phase12_execution_cost_regime_evidence(fills, closed)
    assert "execution_model_price_reconciliation_failed:0" in report["error_codes"]
    fills, closed = _data()
    fills["raw_oos_fills"][1]["fill"]["modeled_half_spread_bps"] = None
    report = phase12_execution_cost_regime_evidence(fills, closed)
    assert "cost_source_fields_unavailable_or_invalid:1" in report["error_codes"]


def test_missing_or_wrong_links_and_quantity_fail_closed():
    fills, closed = _data()
    closed["closed_positions"][0]["exit_fill_indices"] = [0]
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert "missing_reused_or_invalid_fill_link:0" in output["error_codes"]
    fills, closed = _data()
    closed["closed_positions"][0]["closed_quantity"] = 5
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert "closed_trade_fill_quantities_mismatch:0" in output["error_codes"]


def test_invalid_fee_or_net_reconciliation_rejected():
    fills, closed = _data()
    fills["raw_oos_fills"][0]["fill"]["fees"] = -1
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert "cost_source_fields_unavailable_or_invalid:0" in output["error_codes"]
    fills, closed = _data()
    closed["closed_positions"][0]["fee_adjusted_net_pnl"] = 500
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert "closed_trade_cost_decomposition_mismatch:0" in output["error_codes"]


def test_invalid_upstream_and_duplicate_fill_cannot_be_rehabilitated():
    fills, closed = _data()
    fills["oos_fill_coverage_verified"] = False
    closed["paired_closeout_reconciliation_verified"] = False
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert not output["simulated_execution_cost_decomposition_verified"]
    assert "oos_fill_coverage_not_verified" in output["error_codes"]
    assert "closed_position_reconciliation_not_verified" in output["error_codes"]
    fills, closed = _data()
    fills["raw_oos_fills"][1]["fill_index"] = 0
    output = phase12_execution_cost_regime_evidence(fills, closed)
    assert "invalid_or_duplicate_fill_identity:1" in output["error_codes"]


def test_future_regime_snapshot_is_marked_lookahead_and_never_claims_authority():
    fills, closed = _data()
    report = phase12_execution_cost_regime_evidence(
        fills, closed,
        regime_snapshots=[_snapshot(regime_available_at_timestamp="2026-01-02T11:00:00Z")],
    )
    assert report["simulated_execution_cost_decomposition_verified"] is True
    assert report["closed_positions"][0]["historical_regime"]["regime"] is None
    assert report["closed_positions"][0]["historical_regime"]["status"] == \
        "lookahead_or_invalid_snapshot_availability"
    assert not report["historical_regime_independently_verified"]


def test_valid_snapshot_contract_does_not_claim_independent_historical_proof():
    fills, closed = _data()
    result = phase12_execution_cost_regime_evidence(fills, closed, regime_snapshots=[_snapshot()])
    note = result["closed_positions"][0]["historical_regime"]
    assert note["regime"] == "BULL"
    assert note["status"] == "timestamp_and_provenance_contract_consistent"
    assert note["historical_source_independently_audited"] is False
    assert result["historical_regime_feed_connected"] is True
    assert result["historical_regime_independently_verified"] is False


def test_duplicate_missing_and_unproven_regime_observations():
    fills, closed = _data()
    duplicate = phase12_execution_cost_regime_evidence(
        fills, closed, regime_snapshots=[_snapshot(), deepcopy(_snapshot())],
    )
    assert duplicate["closed_positions"][0]["historical_regime"]["status"] == \
        "ambiguous_snapshot_identity"
    missing = phase12_execution_cost_regime_evidence(fills, closed, regime_snapshots=[])
    assert missing["closed_positions"][0]["historical_regime"]["status"] == \
        "no_matching_point_in_time_snapshot"
    bad = phase12_execution_cost_regime_evidence(
        fills, closed, regime_snapshots=[_snapshot(dataset_fingerprint="")],
    )
    assert bad["closed_positions"][0]["historical_regime"]["status"] == \
        "missing_historical_source_provenance"
    invalid = phase12_execution_cost_regime_evidence(fills, closed, regime_snapshots="invalid")
    assert "invalid_regime_snapshots_collection" in invalid["error_codes"]
    assert invalid["closed_positions"] == []


def test_real_phase9_phase10_phase11_phase12_research_artifact_integration():
    fills, _ = _data()
    raw = [r["fill"] for r in fills["raw_oos_fills"]]
    nested = SimpleNamespace(windows=[SimpleNamespace(
        window=1, decision="TRADE", selected_strategy_id="sma",
        test_start="2026-01-02T09:30:00Z", test_end="2026-01-02T16:00:00Z",
        oos_fill_evidence={
            "source": "BacktestRunResult.trades", "recorded": True, "fills": raw,
        },
        oos_execution_costs={"fill_count": 2, "fees_paid": 0.2},
    )])
    report = phase9_oos_fill_evidence(nested)
    assert report["phase10_closed_position_evidence"]["paired_closeout_reconciliation_verified"]
    assert report["phase11_trade_level_loss_attribution"]["observed_fee_and_loss_accounting_verified"]
    assert report["phase12_execution_cost_regime_evidence"][
        "simulated_execution_cost_decomposition_verified"
    ]
    assert report["phase12_execution_cost_regime_evidence"]["execution_allowed"] is False


def test_engine_records_reference_for_buy_exit_and_half_spread_without_price_changes():
    from datetime import datetime, timedelta
    from app.engine import run_backtest
    from app.execution_policy import ExecutionRealismPolicy, execution_policy_context
    from app.models import PriceBar, BacktestRunRequest

    values = [100, 101, 103, 110]
    bars = [PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=i),
        open=float(p), high=p + 2, low=p - 1, close=float(p), volume=10000,
    ) for i, p in enumerate(values)]
    request = BacktestRunRequest(
        symbols=["AAPL"], bars={"AAPL": bars}, strategy="breakout",
        initial_equity=10000, fast_window=1, slow_window=2,
        max_position_pct=0.1, use_risk_agent=False, fee_bps=0,
        slippage_bps=5, market_impact_bps=0, force_close_at_end=True,
    )
    with execution_policy_context(ExecutionRealismPolicy(bid_ask_spread_bps=10)):
        result = run_backtest(request)
    assert result.trades
    for fill in result.trades:
        assert fill.execution_reference_price is not None
        assert fill.modeled_slippage_bps == 5
        assert fill.modeled_half_spread_bps == 5
        assert fill.price > 0
