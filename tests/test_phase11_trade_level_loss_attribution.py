"""Phase 11: observed fee drag is not slippage, regime, or causal evidence."""
from copy import deepcopy
from types import SimpleNamespace

from app.phase11_trade_level_loss_attribution import phase11_trade_level_loss_attribution
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


def _position(gross=-20, fees=2, net=-22, fold="nested-oos-1"):
    return {
        "fold_id": fold, "strategy_id": "candidate-a", "symbol": "AAPL",
        "entry_timestamp": "2026-01-02T10:00:00Z",
        "exit_timestamp": "2026-01-02T15:00:00Z",
        "closed_quantity": 10,
        "executed_price_gross_pnl": gross, "total_fees": fees,
        "fee_adjusted_net_pnl": net, "engine_realized_net_pnl": net,
        "reported_exit_reasons": ["stop_loss"],
    }


def _phase10(positions):
    return {
        "paired_closeout_reconciliation_verified": True,
        "closed_position_count": len(positions),
        "closed_positions": positions,
    }


def _regime():
    return {
        "fold_id": "nested-oos-1", "strategy_id": "candidate-a",
        "symbol": "AAPL", "entry_timestamp": "2026-01-02T10:00:00Z",
        "regime": "bear",
        "regime_asof_timestamp": "2026-01-02T09:00:00Z",
        "regime_available_at_timestamp": "2026-01-02T09:01:00Z",
        "source": "historical_point_in_time_observation",
        "dataset_fingerprint": "sha256:historical-fixture",
    }


def test_loss_patterns_and_fold_summaries_are_observational():
    result = phase11_trade_level_loss_attribution(_phase10([
        _position(), _position(gross=1, fees=2, net=-1),
        _position(gross=10, fees=2, net=8, fold="nested-oos-2"),
    ]))
    assert result["observed_fee_and_loss_accounting_verified"] is True
    assert result["attributed_trade_count"] == 3
    assert result["trades"][0]["observed_loss_pattern"] == "negative_executed_gross_plus_fee_drag"
    assert result["trades"][1]["observed_loss_pattern"] == "fee_drag_flipped_nonnegative_executed_gross_to_loss"
    assert result["trades"][1]["separate_slippage_amount"] is None
    assert result["trades"][0]["reported_exit_reasons"] == ["stop_loss"]
    assert result["trades"][0]["root_cause_confirmed"] is False
    a, b = result["fold_strategy_summaries"]
    assert (a["trade_count"], a["loss_count"], a["fee_flipped_loss_count"]) == (2, 2, 1)
    assert (a["executed_gross_pnl"], a["recorded_fees"], a["fee_adjusted_net_pnl"]) == (-19, 4, -23)
    assert (b["trade_count"], b["win_count"], b["fee_adjusted_net_pnl"]) == (1, 1, 8)
    assert result["point_in_time_regime_independently_verified"] is False
    assert result["strategy_v8_hypothesis_ready"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_no_trades_or_invalid_upstream_fail_closed():
    missing = phase11_trade_level_loss_attribution(None)
    assert missing["observed_fee_and_loss_accounting_verified"] is False
    assert missing["fold_strategy_summaries"] == []
    assert "upstream_closeout_reconciliation_unverified" in missing["error_codes"]
    empty = phase11_trade_level_loss_attribution(_phase10([]))
    assert not empty["observed_fee_and_loss_accounting_verified"]
    bad = _phase10([_position()])
    bad["paired_closeout_reconciliation_verified"] = False
    assert phase11_trade_level_loss_attribution(bad)["trades"] == []


def test_reconciliation_error_blocks_all_partial_aggregation():
    bad = _phase10([_position(), _position(gross=2, fees=5, net=9)])
    outcome = phase11_trade_level_loss_attribution(bad)
    assert not outcome["observed_fee_and_loss_accounting_verified"]
    assert outcome["trades"] == []
    assert outcome["fold_strategy_summaries"] == []
    assert "pnl_or_fee_reconciliation_failed:1" in outcome["error_codes"]


def test_missing_fields_invalid_time_fee_and_exit_reason_fail_closed():
    invalid = _phase10([_position()])
    invalid["closed_positions"][0]["entry_timestamp"] = "2026-01-02T10:00:00"
    assert not phase11_trade_level_loss_attribution(invalid)["observed_fee_and_loss_accounting_verified"]
    invalid = _phase10([_position(fees=-2, net=-18)])
    assert "invalid_closed_position_fields:0" in phase11_trade_level_loss_attribution(invalid)["error_codes"]
    invalid = _phase10([_position()])
    invalid["closed_positions"][0]["reported_exit_reasons"] = [123]
    assert "invalid_exit_reason_evidence:0" in phase11_trade_level_loss_attribution(invalid)["error_codes"]
    invalid = _phase10([_position()])
    invalid["closed_positions"][0]["closed_quantity"] = 0
    assert not phase11_trade_level_loss_attribution(invalid)["observed_fee_and_loss_accounting_verified"]


def test_breakeven_missing_reasons_and_bad_count():
    x = _position(gross=2, fees=2, net=0)
    x.pop("reported_exit_reasons")
    result = phase11_trade_level_loss_attribution(_phase10([x]))
    assert result["trades"][0]["observed_loss_pattern"] == "approximately_breakeven_after_recorded_fees"
    assert result["trades"][0]["exit_reason_provenance"] == "unavailable"
    x = _phase10([_position()])
    x["closed_position_count"] = 2
    assert "missing_or_inconsistent_closed_position_count" in phase11_trade_level_loss_attribution(x)["error_codes"]


def test_regime_metadata_is_only_schema_consistency_not_independent_proof():
    reported = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations=[_regime()])
    note = reported["trades"][0]["market_regime_evidence"]
    assert note["label"] == "bear"
    assert reported["regime_observation_metadata_consistent"] is True
    assert reported["point_in_time_regime_independently_verified"] is False
    assert reported["trade_level_causal_attribution_verified"] is False
    assert reported["strategy_v8_hypothesis_ready"] is False


def test_future_or_bad_regime_cannot_be_joined_to_entry():
    future = _regime()
    future["regime_available_at_timestamp"] = "2026-01-02T11:00:00Z"
    got = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations=[future])
    assert got["trades"][0]["market_regime_evidence"]["label"] is None
    assert got["trades"][0]["market_regime_evidence"]["status"] == "unverified_or_lookahead_timestamp"
    assert got["regime_observation_metadata_consistent"] is False

    bad = _regime()
    bad.pop("dataset_fingerprint")
    got = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations=[bad])
    assert got["trades"][0]["market_regime_evidence"]["status"] == "missing_observation_provenance"


def test_duplicate_or_unmatched_regime_never_authoritative():
    duplicate = [_regime(), deepcopy(_regime())]
    result = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations=duplicate)
    assert result["trades"][0]["market_regime_evidence"]["status"] == "ambiguous_trade_matched_observation"
    missing = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations=[])
    assert missing["trades"][0]["market_regime_evidence"]["status"] == "missing_trade_matched_observation"
    assert missing["observed_fee_and_loss_accounting_verified"] is True


def test_no_regime_supplied_is_explicit_and_research_only():
    result = phase11_trade_level_loss_attribution(_phase10([_position()]))
    assert result["trades"][0]["market_regime_evidence"] == {"status": "not_supplied", "label": None}
    assert result["regime_observation_metadata_consistent"] is False
    assert result["promotion_allowed"] is False
    invalid = phase11_trade_level_loss_attribution(_phase10([_position()]), regime_observations="invalid")
    assert not invalid["observed_fee_and_loss_accounting_verified"]


def test_integration_into_existing_phase9_and_phase10_artifact():
    fills = [
        {"symbol": "AAPL", "side": "buy", "quantity": 10, "price": 100,
         "fees": 1, "timestamp": "2026-01-02T10:00:00Z", "realized_pnl": 0,
         "position_closed": False, "reason": "sma"},
        {"symbol": "AAPL", "side": "sell", "quantity": 10, "price": 98,
         "fees": 1, "timestamp": "2026-01-02T15:00:00Z", "realized_pnl": -22,
         "position_closed": True, "round_trip_realized_pnl": -22,
         "reason": "stop_loss"},
    ]
    window = SimpleNamespace(
        window=1, decision="TRADE", selected_strategy_id="candidate-a",
        test_start="2026-01-02T09:30:00Z", test_end="2026-01-02T16:00:00Z",
        oos_fill_evidence={"source": "BacktestRunResult.trades", "recorded": True, "fills": fills},
        oos_execution_costs={"fill_count": 2, "fees_paid": 2},
    )
    artifact = phase9_oos_fill_evidence(SimpleNamespace(windows=[window]))
    assert artifact["oos_fill_coverage_verified"] is True
    assert artifact["phase10_closed_position_evidence"]["paired_closeout_reconciliation_verified"] is True
    phase11 = artifact["phase11_trade_level_loss_attribution"]
    assert phase11["observed_fee_and_loss_accounting_verified"] is True
    assert phase11["trades"][0]["reported_exit_reasons"] == ["stop_loss"]
    assert phase11["fold_strategy_summaries"][0]["fee_adjusted_net_pnl"] == -22
    assert phase11["point_in_time_regime_independently_verified"] is False
