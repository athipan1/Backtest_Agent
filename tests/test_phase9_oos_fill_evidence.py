"""Phase 9 real nested OOS fill evidence must stay diagnostic and fail closed."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


def _fill(timestamp="2026-01-02T10:00:00Z", *, side="buy", fees=1.25):
    return {
        "symbol": "AAPL",
        "side": side,
        "timestamp": timestamp,
        "quantity": 2,
        "price": 100.0,
        "fees": fees,
        "market_impact_bps": 2.0,
        "realized_pnl": 0.0,
    }


def _fold(*, fills=None, recorded=True, decision="TRADE", window=1):
    if fills is None:
        fills = [_fill()]
    return SimpleNamespace(
        window=window,
        test_start="2026-01-02T09:30:00Z",
        test_end="2026-01-02T16:00:00Z",
        selected_strategy_id="strategy-a" if decision == "TRADE" else None,
        decision=decision,
        oos_fill_evidence={
            "source": "BacktestRunResult.trades",
            "recorded": recorded,
            "fills": fills,
        } if decision == "TRADE" else {},
        oos_execution_costs={
            "fill_count": len(fills),
            "fees_paid": round(sum(f["fees"] for f in fills), 2),
        },
    )


def test_real_oos_fills_are_preserved_without_claiming_trade_profit_causality():
    fill = _fill()
    result = phase9_oos_fill_evidence(SimpleNamespace(windows=[_fold(fills=[fill])]))

    assert result["oos_fill_coverage_verified"] is True
    assert result["observed_fill_count"] == 1
    assert result["raw_oos_fills"][0]["fill"] == fill
    assert result["raw_oos_fills"][0]["fold_id"] == "nested-oos-1"
    assert result["folds"][0]["oos_start"] == "2026-01-02T09:30:00Z"
    assert result["error_counts"] == {}
    assert result["closed_trade_ledger_available"] is False
    assert result["gross_net_cost_decomposition_verified"] is False
    assert result["point_in_time_regime_verified"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_missing_ledger_or_no_trades_cannot_be_misreported_as_verified():
    absent = phase9_oos_fill_evidence(None)
    assert absent["oos_fill_coverage_verified"] is False
    assert absent["error_counts"]["nested_oos_evidence_unavailable"] == 1

    no_capture = phase9_oos_fill_evidence(
        SimpleNamespace(windows=[_fold(recorded=False)])
    )
    assert no_capture["oos_fill_coverage_verified"] is False
    assert no_capture["error_counts"]["oos_fill_source_unavailable"] == 1

    no_fills = phase9_oos_fill_evidence(
        SimpleNamespace(windows=[_fold(fills=[])])
    )
    assert no_fills["oos_fill_coverage_verified"] is False
    assert no_fills["error_counts"]["no_observed_oos_fills"] == 1


def test_cash_abstention_is_recorded_without_synthetic_trades():
    result = phase9_oos_fill_evidence(
        SimpleNamespace(windows=[_fold(decision="NO_TRADE")])
    )
    assert result["cash_abstention_windows"] == 1
    assert result["trade_windows"] == 0
    assert result["raw_oos_fills"] == []
    assert result["folds"][0]["status"] == "cash_abstention"
    assert result["oos_fill_coverage_verified"] is False


def test_bad_fill_time_and_fee_mismatch_fail_closed():
    fold = _fold(fills=[_fill("2026-01-03T10:00:00Z")])
    fold.oos_execution_costs["fees_paid"] = 0.0
    report = phase9_oos_fill_evidence(SimpleNamespace(windows=[fold]))
    assert report["oos_fill_coverage_verified"] is False
    assert report["error_counts"]["fill_outside_oos_window_or_naive_timestamp"] == 1
    assert report["error_counts"]["oos_fees_reconciliation_failed"] == 1


def test_invalid_fill_quantity_and_missing_fold_fields_fail_closed():
    fold = _fold(fills=[{**_fill(), "quantity": 0, "price": float("nan")}])
    fold.window = -1
    fold.selected_strategy_id = ""
    result = phase9_oos_fill_evidence(SimpleNamespace(windows=[fold]))
    assert result["oos_fill_coverage_verified"] is False
    assert result["error_counts"]["invalid_fill_quantity"] == 1
    assert result["error_counts"]["invalid_fill_price"] == 1
    assert result["error_counts"]["invalid_or_duplicate_fold_id"] == 1
    assert result["error_counts"]["missing_selected_strategy_id"] == 1


def test_naive_timestamp_and_duplicate_fold_ids_cannot_pass():
    one = _fold(fills=[_fill("2026-01-02T10:00:00")])
    two = _fold(fills=[_fill(side="sell")])
    result = phase9_oos_fill_evidence(SimpleNamespace(windows=[one, two]))
    assert result["error_counts"]["fill_outside_oos_window_or_naive_timestamp"] == 1
    assert result["error_counts"]["invalid_or_duplicate_fold_id"] == 1
    assert result["oos_fill_coverage_verified"] is False


def test_genuine_pydantic_datetime_serialization_contract():
    assert datetime.fromisoformat(
        _fill()["timestamp"].replace("Z", "+00:00")
    ).tzinfo == timezone.utc
