from app.phase9_fold_ledger_integrity import phase9_fold_ledger_integrity


def _trade():
    return {
        "trade_id": "t1", "fold_id": "f1", "strategy_id": "sma",
        "entry_timestamp": "2026-01-02T10:00:00Z",
        "exit_timestamp": "2026-01-02T11:00:00Z",
        "regime_asof_timestamp": "2026-01-02T09:00:00Z",
        "gross_pnl": 10, "fees": 1, "slippage": 1, "impact": 0,
        "net_pnl": 8, "position_size": 1, "market_regime": "bull",
    }


def _fold():
    return {"fold_id": "f1", "selected_strategy_id": "sma",
            "oos_start": "2026-01-02T09:30:00Z",
            "oos_end": "2026-01-02T16:00:00Z"}


def test_matching_trade_and_fold():
    result = phase9_fold_ledger_integrity([_trade()], [_fold()])
    assert result["join_verified"] is True
    assert result["execution_allowed"] is False


def test_outside_fold_rejected():
    trade = _trade()
    trade["exit_timestamp"] = "2026-01-03T11:00:00Z"
    result = phase9_fold_ledger_integrity([trade], [_fold()])
    assert result["join_verified"] is False
    assert result["error_counts"]["trade_outside_oos_window"] == 1


def test_strategy_mismatch_rejected():
    trade = _trade()
    trade["strategy_id"] = "mean_reversion"
    result = phase9_fold_ledger_integrity([trade], [_fold()])
    assert result["error_counts"]["strategy_mismatch"] == 1


def test_no_ledger_never_claims_verified():
    result = phase9_fold_ledger_integrity(None, None)
    assert result["join_verified"] is False
    assert result["error_counts"]["trade_ledger_unavailable"] == 1
    assert result["sealed_holdout_opened"] is False


def test_duplicate_fold_id_rejected():
    result = phase9_fold_ledger_integrity([_trade()], [_fold(), _fold()])
    assert result["error_counts"]["duplicate_fold_id"] == 1
