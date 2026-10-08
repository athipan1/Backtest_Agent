"""Phase 13 historical regime: no future labels or invented v8 research authority."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from app.phase13_historical_regime import (
    bind_regime_at_entry,
    historical_regime_feed_from_env,
    phase13_v8_preparation,
    read_historical_regime_feed,
)
from app.phase9_oos_fill_evidence import phase9_oos_fill_evidence


END = "2026-01-03T16:00:00Z"


def _observation(*, oid="A", asof="2026-01-02T09:30:00Z",
                 available="2026-01-02T09:40:00Z", regime="BULL"):
    return {
        "symbol": "AAPL", "regime": regime, "source_observation_id": oid,
        "regime_asof_timestamp": asof,
        "regime_available_at_timestamp": available,
        "source": "historical_point_in_time_observation",
        "dataset_fingerprint": "sha256:historical-dataset-provenance",
    }


def _payload(rows=None):
    return {
        "schema_version": "phase13-historical-regime-feed.v1",
        "source_id": "independent-history-archive-name",
        "dataset_fingerprint": "sha256:historical-dataset-provenance",
        "observations": [_observation()] if rows is None else rows,
    }


def _write(tmp_path, payload):
    path = tmp_path / "history.json"
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _read(tmp_path, payload, *, end=END):
    path, digest = _write(tmp_path, payload)
    return read_historical_regime_feed(path, digest, research_end=end)


def _closed():
    return {
        "paired_closeout_reconciliation_verified": True,
        "closed_position_count": 1,
        "closed_positions": [{
            "fold_id": "nested-oos-1", "strategy_id": "sma", "symbol": "AAPL",
            "entry_timestamp": "2026-01-02T10:00:00Z",
            "exit_timestamp": "2026-01-02T15:00:00Z",
        }],
    }


def test_unconfigured_and_wrong_checksum_fail_closed(tmp_path):
    source = read_historical_regime_feed(None, None, research_end=END)
    assert source["status"] == "historical_feed_not_configured"
    assert source["observations"] == []
    path, digest = _write(tmp_path, _payload())
    assert read_historical_regime_feed(path, None, research_end=END)["status"] == \
        "file_or_checksum_missing"
    assert read_historical_regime_feed(path, "x", research_end=END)["status"] == \
        "invalid_expected_sha256"
    assert read_historical_regime_feed(path, "0" * 64, research_end=END)["status"] == \
        "historical_feed_digest_mismatch"
    assert read_historical_regime_feed(path, digest, research_end=END)["contract_verified"]


def test_sha256_matches_exact_unchanged_file_bytes(tmp_path):
    path, digest = _write(tmp_path, _payload())
    feed = read_historical_regime_feed(
        path, digest.upper(), research_end=datetime(2026, 1, 3, 16, tzinfo=timezone.utc)
    )
    assert feed["status"] == "checksum_and_contract_valid"
    assert feed["source_sha256"] == digest
    assert feed["observation_count"] == 1
    assert feed["historical_source_independently_audited"] is False
    path.write_text(path.read_text() + " ")
    assert read_historical_regime_feed(path, digest, research_end=END)["contract_verified"] is False


def test_source_is_fully_rejected_if_any_observation_reaches_holdout(tmp_path):
    future = _observation(oid="FUTURE", available="2026-01-04T11:00:00Z")
    result = _read(tmp_path, _payload([_observation(), future]))
    assert result["status"] == "historical_observation_invalid_or_outside_research"
    assert result["observations"] == []
    assert result["contract_verified"] is False


def test_naive_or_inverted_provenance_timestamp_fails_closed(tmp_path):
    rows = [
        _observation(asof="2026-01-02T09:30:00",
                     available="2026-01-02T09:40:00Z"),
    ]
    assert not _read(tmp_path, _payload(rows))["contract_verified"]
    rows = [_observation(asof="2026-01-02T10:00:00Z",
                         available="2026-01-02T09:40:00Z")]
    assert not _read(tmp_path, _payload(rows))["contract_verified"]


def test_duplicate_provenance_ids_and_invalid_source_rejected(tmp_path):
    first = _observation()
    second = _observation(oid="A", asof="2026-01-02T09:45:00Z",
                          available="2026-01-02T09:50:00Z")
    assert _read(tmp_path, _payload([first, second]))["status"] == \
        "duplicate_historical_observation_id"
    invalid = _observation()
    invalid["source"] = "manager_current_state"
    assert not _read(tmp_path, _payload([invalid]))["contract_verified"]


def test_asof_join_selects_latest_known_before_entry_not_future(tmp_path):
    feed = _read(tmp_path, _payload([
        _observation(oid="early", available="2026-01-02T09:35:00Z"),
        _observation(oid="last", asof="2026-01-02T09:45:00Z",
                     available="2026-01-02T09:50:00Z", regime="BEAR"),
        _observation(oid="future_for_entry", asof="2026-01-02T10:20:00Z",
                     available="2026-01-02T10:25:00Z", regime="BULL"),
    ]))
    joined = bind_regime_at_entry(_closed(), feed)
    assert joined["pit_join_contract_complete"]
    assert joined["matched_count"] == 1
    assert joined["matched_snapshots"][0]["source_observation_id"] == "last"
    assert joined["matched_snapshots"][0]["regime"] == "BEAR"
    assert joined["matched_snapshots"][0]["age_seconds"] == 600
    assert joined["independently_verified_market_regime"] is False


def test_same_available_timestamp_ambiguous_and_stale_fail_closed(tmp_path):
    duplicate_time = _read(tmp_path, _payload([
        _observation(oid="one"),
        _observation(oid="two", regime="BEAR"),
    ]))
    report = bind_regime_at_entry(_closed(), duplicate_time)
    assert report["pit_join_contract_complete"] is False
    assert "ambiguous_latest_regime_observation" in report["missing_or_rejected"]
    assert report["matched_snapshots"] == []
    stale = _read(tmp_path, _payload([
        _observation(available="2025-12-20T09:40:00Z",
                     asof="2025-12-20T09:30:00Z")
    ]))
    assert "stale_pit_regime_observation" in bind_regime_at_entry(
        _closed(), stale
    )["missing_or_rejected"]


def test_missing_symbol_missing_source_and_bad_closed_ledger(tmp_path):
    feed = _read(tmp_path, _payload([{
        **_observation(), "symbol": "MSFT",
    }]))
    result = bind_regime_at_entry(_closed(), feed)
    assert "entry_missing_prior_pit_regime" in result["missing_or_rejected"]
    assert bind_regime_at_entry(_closed(), None)["matched_snapshots"] == []
    bad = deepcopy(_closed())
    bad["paired_closeout_reconciliation_verified"] = False
    assert "closed_position_evidence_unverified" in bind_regime_at_entry(
        bad, feed
    )["missing_or_rejected"]


def test_environment_reader_explicit_only_never_uses_manager_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_FILE", raising=False)
    monkeypatch.delenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_SHA256", raising=False)
    assert historical_regime_feed_from_env(research_end=END)["observations"] == []
    path, digest = _write(tmp_path, _payload())
    monkeypatch.setenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_FILE", str(path))
    monkeypatch.setenv("BACKTEST_RESEARCH_HISTORICAL_REGIME_SHA256", digest)
    assert historical_regime_feed_from_env(research_end=END)["contract_verified"]


def test_v8_preparation_uses_only_reconciled_trade_and_join_observations():
    joined = {
        "pit_join_contract_complete": True,
        "matched_snapshots": [{"regime": "BULL"}],
    }
    cost = {
        "simulated_execution_cost_decomposition_verified": True,
        "closed_positions": [
            {"fold_id": "nested-oos-1", "strategy_id": "sma",
             "historical_regime": {
                 "status": "timestamp_and_provenance_contract_consistent",
                 "regime": "BULL",
             },
             "engine_executed_net_pnl": 12,
             "modeled_slippage_cost": 1,
             "modeled_impact_cost": 2,
             "modeled_half_spread_cost": 0.5,
             "recorded_fees": 0.5},
        ],
    }
    out = phase13_v8_preparation(cost, joined)
    assert out["descriptive_regime_cost_evidence_available"] is True
    assert out["fold_regime_summaries"][0]["net_pnl"] == 12
    assert out["fold_regime_summaries"][0]["modeled_impact_cost"] == 2
    assert out["new_strategy_evaluations_run"] == 0
    assert out["strategy_v8_ready_for_promotion"] is False
    assert out["promotion_allowed"] is False
    assert out["sealed_holdout_opened"] is False


def test_failed_join_prevents_partial_regime_cost_grouping():
    cost = {"simulated_execution_cost_decomposition_verified": True,
            "closed_positions": [{"historical_regime": {"regime": "BULL"}}]}
    joined = {"pit_join_contract_complete": False}
    result = phase13_v8_preparation(cost, joined)
    assert not result["descriptive_regime_cost_evidence_available"]
    assert result["fold_regime_summaries"] == []
    assert "incomplete_regime_join_or_cost_evidence" in result["readiness_blockers"]


def test_existing_phase9_artifact_contains_fail_closed_phase13_not_fake_regime():
    artifact = phase9_oos_fill_evidence(None)
    assert artifact["phase13_historical_regime_evidence"]["pit_join_contract_complete"] is False
    assert artifact["phase13_historical_regime_evidence"]["matched_snapshots"] == []
    assert artifact["phase13_strategy_research_v8_preparation"][
        "strategy_v8_ready_for_promotion"
    ] is False
    assert artifact["execution_allowed"] is False


def test_malformed_json_or_future_date_cannot_influence_research(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{bad")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert read_historical_regime_feed(path, digest, research_end=END)["status"] == \
        "historical_feed_unreadable"
    assert not read_historical_regime_feed(
        path, digest, research_end="2026-01-03T16:00:00"
    )["contract_verified"]


def test_full_research_artifact_binds_regime_without_changing_trading_authority(tmp_path):
    # A real nested OOS report supplies simulated fills, never invented broker trades.
    fills = [
        {"symbol": "AAPL", "side": "buy", "quantity": 2, "price": 100.15,
         "execution_reference_price": 100, "modeled_slippage_bps": 10,
         "market_impact_bps": 5, "modeled_half_spread_bps": 0,
         "fees": 0.1, "timestamp": "2026-01-02T10:00:00Z",
         "realized_pnl": 0, "position_closed": False, "reason": "sma"},
        {"symbol": "AAPL", "side": "sell", "quantity": 2, "price": 109.78,
         "execution_reference_price": 110, "modeled_slippage_bps": 10,
         "market_impact_bps": 10, "modeled_half_spread_bps": 0,
         "fees": 0.1, "timestamp": "2026-01-02T15:00:00Z",
         "realized_pnl": 19.06, "round_trip_realized_pnl": 19.06,
         "position_closed": True, "reason": "take_profit"},
    ]
    window = SimpleNamespace(
        window=1, decision="TRADE", selected_strategy_id="sma",
        test_start="2026-01-02T09:30:00Z",
        test_end="2026-01-02T16:00:00Z",
        oos_fill_evidence={"source": "BacktestRunResult.trades",
                           "recorded": True, "fills": fills},
        oos_execution_costs={"fill_count": 2, "fees_paid": 0.2},
    )
    feed = _read(tmp_path, _payload(), end=END)
    report = phase9_oos_fill_evidence(
        SimpleNamespace(windows=[window]), historical_regime_source=feed
    )
    p13 = report["phase13_historical_regime_evidence"]
    p12 = report["phase12_execution_cost_regime_evidence"]
    assert p13["pit_join_contract_complete"] is True
    assert p12["simulated_execution_cost_decomposition_verified"] is True
    assert p12["closed_positions"][0]["historical_regime"]["regime"] == "BULL"
    assert report["phase13_strategy_research_v8_preparation"][
        "descriptive_regime_cost_evidence_available"
    ] is True
    assert report["phase13_strategy_research_v8_preparation"][
        "strategy_v8_ready_for_promotion"
    ] is False
    assert report["promotion_allowed"] is False
    assert report["execution_allowed"] is False
    assert report["sealed_holdout_opened"] is False
