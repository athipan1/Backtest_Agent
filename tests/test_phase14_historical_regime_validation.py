"""Phase 14 independent cross-fold/revision audit is research-only and fail closed."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.phase14_historical_regime_validation import phase14_historical_regime_validation
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


def _source():
    return {
        "schema_version": "phase13-historical-regime-feed.v1",
        "status": "checksum_and_contract_valid",
        "contract_verified": True,
        "source_id": "external_archive_reference",
        "source_sha256": "a" * 64,
        "dataset_fingerprint": "immutable-source-dataset",
        "observation_count": 1,
        "observations": [{
            "symbol": "AAPL",
            "regime": "BULL",
            "source_observation_id": "entry-regime-1",
            "regime_asof_timestamp": "2026-01-02T09:30:00Z",
            "regime_available_at_timestamp": "2026-01-02T09:40:00Z",
            "dataset_fingerprint": "immutable-source-dataset",
            "source": "historical_point_in_time_observation",
        }],
    }


def _window():
    return SimpleNamespace(
        window=1, decision="TRADE", selected_strategy_id="candidate-a",
        test_start="2026-01-02T09:30:00Z",
        test_end="2026-01-02T16:00:00Z",
        oos_fill_evidence={
            "source": "BacktestRunResult.trades",
            "recorded": True,
            "fills": [
                {"symbol": "AAPL", "side": "buy", "quantity": 2,
                 "price": 100.15, "fees": 0.1,
                 "timestamp": "2026-01-02T10:00:00Z",
                 "execution_reference_price": 100,
                 "modeled_slippage_bps": 10,
                 "modeled_half_spread_bps": 0,
                 "market_impact_bps": 5,
                 "realized_pnl": 0, "position_closed": False},
                {"symbol": "AAPL", "side": "sell", "quantity": 2,
                 "price": 109.78, "fees": 0.1,
                 "timestamp": "2026-01-02T15:00:00Z",
                 "execution_reference_price": 110,
                 "modeled_slippage_bps": 10,
                 "modeled_half_spread_bps": 0,
                 "market_impact_bps": 10,
                 "realized_pnl": 19.06, "position_closed": True,
                 "round_trip_realized_pnl": 19.06, "reason": "take_profit"},
            ],
        },
        oos_execution_costs={"fill_count": 2, "fees_paid": 0.2},
    )


def _report(source=None):
    return phase9_oos_fill_evidence(
        SimpleNamespace(windows=[_window()]),
        historical_regime_source=source if source is not None else _source(),
    )


def _inputs(report=None, source=None):
    s = source if source is not None else _source()
    p = report if report is not None else _report(s)
    return (p, p["phase12_execution_cost_regime_evidence"],
            p["phase13_historical_regime_evidence"], s)


def _validate(report=None, source=None):
    return phase14_historical_regime_validation(*_inputs(report, source))


def test_full_integrated_phase14_fold_accounting_and_readiness_remains_false():
    artifact = _report()
    result = artifact["phase14_historical_regime_validation"]
    assert result["oos_fold_and_regime_accounting_verified"] is True
    assert result["trade_fold_count"] == 1
    assert result["covered_trade_fold_count"] == 1
    assert result["regime_trade_count"] == 1
    trade = result["fold_regime_cost_summaries"][0]
    assert trade["fold_id"] == "nested-oos-1"
    assert trade["regime"] == "BULL"
    assert trade["simulated_net_pnl"] == 19.06
    assert trade["closed_trade_count"] == 1
    assert trade["positive_net_trade_count"] == 1
    assert result["descriptive_fold_stability"]["positive_net_fold_fraction"] == 1
    assert result["external_provider_authenticity_verified"] is False
    assert result["net_profitability_proven"] is False
    assert result["strategy_v8_validation_ready"] is False
    assert result["strategy_v8_hypotheses_tested"] == 0
    assert result["promotion_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["sealed_holdout_opened"] is False


def test_absent_feed_never_claims_regime_validation():
    report = phase9_oos_fill_evidence(None)
    audit = report["phase14_historical_regime_validation"]
    assert audit["oos_fold_and_regime_accounting_verified"] is False
    assert audit["fold_regime_cost_summaries"] == []
    assert "historical_feed_checksum_or_contract_unverified" in audit["error_codes"]
    assert "upstream_pit_asof_join_incomplete" in audit["error_codes"]


def test_tampered_source_id_checksum_count_and_fingerprint_detected():
    for mutate in [
        lambda s: s.update(source_sha256="not-a-sha"),
        lambda s: s.update(source_id=""),
        lambda s: s.update(observation_count=2),
        lambda s: s.update(dataset_fingerprint=""),
        lambda s: s.update(contract_verified=False),
    ]:
        source = _source()
        mutate(source)
        report = _report()
        out = _validate(report, source)
        assert not out["oos_fold_and_regime_accounting_verified"]
        assert out["fold_regime_cost_summaries"] == []


def test_same_asof_regime_revision_blocks_entire_research_evidence():
    source = _source()
    revised = deepcopy(source["observations"][0])
    revised.update(source_observation_id="revision-2", regime="BEAR",
                   regime_available_at_timestamp="2026-01-02T09:55:00Z")
    source["observations"].append(revised)
    source["observation_count"] = 2
    report = _report(source)
    assert report["phase13_historical_regime_evidence"]["pit_join_contract_complete"]
    audit = report["phase14_historical_regime_validation"]
    assert "conflicting_historical_regime_revision" in audit["error_codes"]
    assert not audit["oos_fold_and_regime_accounting_verified"]


def test_latest_observation_and_timestamp_are_rechecked():
    p, c, j, s = _inputs()
    newer = deepcopy(s["observations"][0])
    newer.update(source_observation_id="second", regime="BULL",
                 regime_asof_timestamp="2026-01-02T09:50:00Z",
                 regime_available_at_timestamp="2026-01-02T09:55:00Z")
    s["observations"].append(newer)
    s["observation_count"] = 2
    assert "historical_regime_not_latest_available_at_entry" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    j["matched_snapshots"][0]["regime_available_at_timestamp"] = "2026-01-02T10:30:00Z"
    out = phase14_historical_regime_validation(p, c, j, s)
    assert "regime_observation_provenance_mismatch_or_lookahead" in out["error_codes"]


def test_missing_trade_fold_and_no_trade_cash_fold_are_not_cherry_picked():
    report = _report()
    report["folds"].append({
        "fold_id": "nested-oos-2", "decision": "TRADE",
        "status": "recorded", "observed_fill_count": 2,
        "oos_start": "2026-01-03T09:30:00Z",
        "oos_end": "2026-01-03T16:00:00Z", "errors": [],
    })
    report["fold_count"] = 2
    assert "trade_fold_closed_position_coverage_incomplete" in _validate(report)["error_codes"]

    # NO_TRADE windows are accounted for, not treated as fake zero-cost wins.
    report["folds"][-1].update(
        decision="NO_TRADE", status="cash_abstention", observed_fill_count=0
    )
    ok = _validate(report)
    assert ok["oos_fold_and_regime_accounting_verified"]
    assert ok["research_fold_count"] == 2
    assert ok["trade_fold_count"] == 1


def test_overlapping_fold_windows_are_rejected_even_with_valid_trade():
    report = _report()
    report["folds"].append({
        "fold_id": "nested-oos-2", "decision": "NO_TRADE",
        "status": "cash_abstention", "observed_fill_count": 0,
        "oos_start": "2026-01-02T15:00:00Z",
        "oos_end": "2026-01-03T16:00:00Z", "errors": [],
    })
    report["fold_count"] = 2
    out = _validate(report)
    assert "overlapping_or_touching_oos_fold_boundaries" in out["error_codes"]
    assert not out["oos_fold_and_regime_accounting_verified"]


def test_wrong_fold_id_and_outside_fold_trade_are_rejected():
    p, c, j, s = _inputs()
    c["closed_positions"][0]["fold_id"] = "nested-oos-999"
    assert "unmatched_trade_or_nontrade_fold" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]

    p, c, j, s = _inputs()
    c["closed_positions"][0]["entry_timestamp"] = "2026-01-03T10:00:00Z"
    j["matched_snapshots"][0]["entry_timestamp"] = "2026-01-03T10:00:00Z"
    assert "trade_outside_research_oos_fold" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]


def test_duplicate_closeouts_and_unmatched_regime_identity_fail_closed():
    p, c, j, s = _inputs()
    c["closed_positions"].append(deepcopy(c["closed_positions"][0]))
    j["matched_snapshots"].append(deepcopy(j["matched_snapshots"][0]))
    j["closed_position_count"] = j["matched_count"] = 2
    out = phase14_historical_regime_validation(p, c, j, s)
    assert "duplicate_or_invalid_cost_trade_identity" in out["error_codes"]
    p, c, j, s = _inputs()
    j["matched_snapshots"][0]["entry_timestamp"] = "2026-01-02T11:00:00Z"
    assert "unmatched_trade_or_nontrade_fold" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]


def test_cost_identity_and_accounting_mismatches_are_rejected():
    p, c, j, s = _inputs()
    c["closed_positions"][0]["modeled_impact_cost"] = 5
    assert "reference_cost_net_pnl_reconciliation_failed" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    c["closed_positions"][0]["recorded_fees"] = -1
    assert "reference_cost_net_pnl_reconciliation_failed" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    c["closed_positions"][0]["engine_executed_net_pnl"] = float("nan")
    assert "nonfinite_trade_cost_component" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]


def test_invalid_fold_metadata_and_incomplete_join_fail_closed():
    report = _report()
    report["folds"][0]["oos_start"] = "2026-01-02T09:30:00"
    assert "invalid_or_duplicate_oos_fold" in _validate(report)["error_codes"]
    p, c, j, s = _inputs()
    j["pit_join_contract_complete"] = False
    assert "upstream_pit_asof_join_incomplete" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    c["simulated_execution_cost_decomposition_verified"] = False
    assert "upstream_simulated_cost_decomposition_unverified" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    p["oos_fill_coverage_verified"] = False
    assert "upstream_oos_fill_coverage_unverified" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]


@pytest.mark.parametrize("bad", [None, [], "wrong", {"raw_oos_fills": []}])
def test_malformed_inputs_never_grant_authority(bad):
    audit = phase14_historical_regime_validation(bad, bad, bad, bad)
    assert audit["oos_fold_and_regime_accounting_verified"] is False
    assert audit["fold_regime_cost_summaries"] == []
    assert audit["strategy_v8_validation_ready"] is False
    assert audit["promotion_allowed"] is False
    assert audit["execution_allowed"] is False


def test_repeated_observation_ids_and_bad_source_rows_cannot_pass():
    p, c, j, s = _inputs()
    s["observations"].append(deepcopy(s["observations"][0]))
    s["observation_count"] = 2
    assert "duplicate_source_observation_identity" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    s["observations"][0]["regime_asof_timestamp"] = "2026-01-02T09:30:00"
    assert "malformed_historical_observation" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]


def test_wrong_observation_id_and_fingerprint_blocks_join():
    p, c, j, s = _inputs()
    j["matched_snapshots"][0]["source_observation_id"] = "missing"
    assert "regime_observation_provenance_mismatch_or_lookahead" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
    p, c, j, s = _inputs()
    j["matched_snapshots"][0]["dataset_fingerprint"] = "wrong-fingerprint"
    assert "regime_observation_provenance_mismatch_or_lookahead" in \
        phase14_historical_regime_validation(p, c, j, s)["error_codes"]
