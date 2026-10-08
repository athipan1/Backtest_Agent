from app.phase9_trade_ledger_audit import phase9_trade_ledger_audit


def _trade():
    return {
        "trade_id": "t1", "entry_timestamp": "2026-01-01T10:00:00+00:00",
        "exit_timestamp": "2026-01-02T10:00:00+00:00",
        "regime_asof_timestamp": "2026-01-01T09:00:00+00:00",
        "gross_pnl": 10, "fees": 1, "slippage": 2, "impact": 1,
        "net_pnl": 6, "position_size": 100, "market_regime": "bull",
    }


def test_complete_ledger_still_has_no_execution_authority():
    result = phase9_trade_ledger_audit([_trade()])
    assert result["evidence_complete"] is True
    assert result["trade_level_causality_verified"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False


def test_empty_and_bad_ledger_fail_closed():
    assert phase9_trade_ledger_audit(None)["evidence_complete"] is False
    trade = _trade()
    trade["regime_asof_timestamp"] = "2026-01-02T12:00:00+00:00"
    trade["net_pnl"] = 10
    result = phase9_trade_ledger_audit([trade, trade])
    assert result["evidence_complete"] is False
    assert result["error_counts"]["duplicate_trade_id"] == 1
    assert result["error_counts"]["net_pnl_reconciliation_failed"] == 2
    assert result["error_counts"]["point_in_time_or_trade_chronology_violation"] == 2
