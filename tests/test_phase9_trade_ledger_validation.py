from app.phase9_trade_ledger_validation import phase9_trade_ledger_validation


def test_phase9_missing_ledger_fails_closed():
    result = phase9_trade_ledger_validation({"fold_count": 6})
    assert result["supplied_trade_count"] == 0
    assert result["trade_level_evidence_complete"] is False
    assert result["causal_conclusions_supported"] is False
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False


def test_phase9_reconciles_costs_without_authorizing_trading():
    trade = dict(strategy_id="sma", fold_id="fold1",
                 entry_time="2026-01-01T10:00:00Z", exit_time="2026-01-02T10:00:00Z",
                 quantity=2, gross_pnl=10, fees=1, slippage=2, impact=1,
                 net_pnl=6, market_regime="bull")
    result = phase9_trade_ledger_validation({"fold_count": 1}, [trade])
    assert result["valid_trade_count"] == 1
    assert result["trade_level_evidence_complete"] is True
    assert result["fold_coverage_verified"] is False
    assert result["promotion_allowed"] is False


def test_phase9_rejects_inconsistent_or_naive_timestamps():
    trade = dict(strategy_id="sma", fold_id="fold1",
                 entry_time="2026-01-01T10:00:00", exit_time="2026-01-02T10:00:00Z",
                 quantity=2, gross_pnl=10, fees=1, slippage=2, impact=1,
                 net_pnl=7, market_regime="bull")
    result = phase9_trade_ledger_validation({}, [trade])
    assert result["valid_trade_count"] == 0
    assert result["invalid_trades"]
